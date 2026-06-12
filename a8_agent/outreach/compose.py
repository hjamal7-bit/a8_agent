"""
The composer.

Reads the strategy matrix (strategy.yaml), picks the right cell using a
Classification, then selects the highest-priority variant whose required slots
are all resolvable from the ContactProfile.

This file deliberately knows nothing about Postgres or the legacy draft tables;
it consumes a ContactProfile + Classification and emits a (subject, body) pair.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:
    import yaml  # type: ignore
except ImportError as e:  # pragma: no cover
    raise RuntimeError(
        "PyYAML is required for the outreach composer. "
        "pip install pyyaml"
    ) from e

from a8_agent.outreach.classify import Classification, Pillar, Archetype
from a8_agent.outreach.ingest import ContactProfile


_STRATEGY_PATH = Path(__file__).parent / "strategy.yaml"


@dataclass(frozen=True)
class ComposedDraft:
    subject: str
    body: str
    cell: str                       # "ip_rich.founder_bootstrapped"
    used_fallback: bool             # cell-level fallback used (not global)
    used_global_fallback: bool      # global generic fallback used
    variants_tried: tuple[str, ...] # debug trail


class _StrategyCache:
    """Read strategy.yaml once per process — re-read if mtime changes."""

    def __init__(self, path: Path):
        self.path = path
        self._loaded: Optional[dict] = None
        self._mtime: Optional[float] = None

    def get(self) -> dict:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError as e:
            raise RuntimeError(f"strategy.yaml not found at {self.path}") from e
        if self._loaded is None or mtime != self._mtime:
            with self.path.open("r", encoding="utf-8") as f:
                self._loaded = yaml.safe_load(f)
            self._mtime = mtime
        return self._loaded


_cache = _StrategyCache(_STRATEGY_PATH)


def _resolve_slots(text: str, slot_dict: dict[str, str]) -> Optional[str]:
    """
    Replace `{slot_name}` tokens with slot_dict values. Returns None if any
    `{...}` placeholder remains unresolvable (i.e. variant doesn't fit profile).

    We intentionally do not use str.format — it explodes on missing keys with
    KeyError; we want a sentinel that lets the caller fall back gracefully.
    """
    import re

    def sub(match: "re.Match[str]") -> str:
        key = match.group(1)
        val = slot_dict.get(key)
        return val if val else f"\x00MISSING:{key}\x00"

    rendered = re.sub(r"\{([a-z_]+)\}", sub, text)
    if "\x00MISSING:" in rendered:
        return None
    return rendered


def _pick_variant(
    variants: list[dict[str, Any]],
    slot_dict: dict[str, str],
    rng: random.Random,
    tried: list[str],
    label: str,
) -> Optional[str]:
    """
    Iterate variants in declaration order; first one whose slots all resolve
    wins. If multiple variants have NO required slots (the empty-slots case),
    randomize among them so we don't ship the same bridge sentence to everyone.
    """
    eligible: list[dict[str, Any]] = []
    for v in variants:
        required = v.get("slots") or []
        if all(slot_dict.get(s) for s in required):
            eligible.append(v)
            tried.append(f"{label}:{v['text'][:40]!r}")

    if not eligible:
        return None

    # If the first eligible has required slots, that's a profile-specific
    # variant — prefer it deterministically (don't randomize). If everything
    # eligible is the no-slot generic case, pick one at random.
    profile_specific = [v for v in eligible if v.get("slots")]
    if profile_specific:
        chosen = profile_specific[0]
    else:
        chosen = rng.choice(eligible)

    return _resolve_slots(chosen["text"], slot_dict)


def _get_cell(strategy: dict, pillar: Pillar, archetype: Archetype) -> dict:
    pillars = strategy.get("pillars", {})
    p = pillars.get(pillar.value)
    if p is None:
        raise KeyError(f"pillar '{pillar.value}' missing from strategy.yaml")
    a = (p.get("archetypes") or {}).get(archetype.value)
    if a is None:
        raise KeyError(
            f"archetype '{archetype.value}' missing under pillar '{pillar.value}'"
        )
    return a


def _global_fallback(strategy: dict, profile: ContactProfile) -> tuple[str, str]:
    gf = strategy.get("global_fallback") or {}
    subject = gf.get("subject") or "quick question"
    body = gf.get("body") or "Saw your name come across this week. Open to a short call?"
    # The global fallback intentionally has NO slots, so this is safe.
    return subject, body.strip()


def compose(
    profile: ContactProfile,
    classification: Classification,
    seed: Optional[int] = None,
) -> ComposedDraft:
    """
    Build a (subject, body) draft from a profile + classification.

    `seed` is an optional RNG seed for deterministic tests. In production, leave
    it None — the composer uses the contact_id as the seed so the same contact
    gets the same draft on repeat runs (no thrash) but different contacts get
    different generic-bridge picks.
    """
    strategy = _cache.get()
    cell_name = f"{classification.pillar.value}.{classification.archetype.value}"
    cell = _get_cell(strategy, classification.pillar, classification.archetype)
    slot_dict = profile.as_slot_dict()
    rng = random.Random(seed if seed is not None else (profile.contact_id or cell_name))
    tried: list[str] = []

    subject = _pick_variant(cell.get("subject_variants", []), slot_dict, rng, tried, "subject")
    thesis = _pick_variant(cell.get("thesis_variants", []), slot_dict, rng, tried, "thesis")
    ask = _pick_variant(cell.get("ask_variants", []), slot_dict, rng, tried, "ask")

    # Thesis is the load-bearing sentence — it MUST contain a profile-specific
    # reference AND state why that reference is the reason for writing. If we
    # couldn't fill a real one, drop to the cell fallback.
    if not (subject and thesis and ask):
        return _cell_fallback(strategy, cell, cell_name, slot_dict, profile, tried)

    body = f"{thesis.strip()}\n\n{ask.strip()}"
    return ComposedDraft(
        subject=subject,
        body=body,
        cell=cell_name,
        used_fallback=False,
        used_global_fallback=False,
        variants_tried=tuple(tried),
    )


def _cell_fallback(
    strategy: dict,
    cell: dict,
    cell_name: str,
    slot_dict: dict[str, str],
    profile: ContactProfile,
    tried: list[str],
) -> ComposedDraft:
    fb = cell.get("fallback")
    if fb:
        required = fb.get("slots") or []
        if all(slot_dict.get(s) for s in required):
            subj_rendered = _resolve_slots(fb["subject"], slot_dict)
            body_rendered = _resolve_slots(fb["body"], slot_dict)
            if subj_rendered and body_rendered:
                tried.append(f"fallback:{cell_name}")
                return ComposedDraft(
                    subject=subj_rendered,
                    body=body_rendered.strip(),
                    cell=cell_name,
                    used_fallback=True,
                    used_global_fallback=False,
                    variants_tried=tuple(tried),
                )

    subject, body = _global_fallback(strategy, profile)
    tried.append("fallback:global")
    return ComposedDraft(
        subject=subject,
        body=body,
        cell=cell_name,
        used_fallback=False,
        used_global_fallback=True,
        variants_tried=tuple(tried),
    )
