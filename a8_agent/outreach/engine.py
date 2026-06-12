"""
Single public entry point for the new outreach draft engine.

    profile = await load_profile(conn, contact_id)
    draft   = generate_draft(profile)
    # draft.subject, draft.body, draft.metadata

If `profile` is None or missing first_name + company, we still return a
GeneratedDraft using the global fallback. We never raise; the worst case is a
generic-but-human draft. That's the contract callers (the cadence handler,
the regenerate endpoint, the CLI) rely on.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

from a8_agent.outreach.classify import classify, Classification
from a8_agent.outreach.compose import compose, ComposedDraft
from a8_agent.outreach.guardrails import check, GuardrailResult
from a8_agent.outreach.ingest import ContactProfile


@dataclass(frozen=True)
class GeneratedDraft:
    subject: str
    body: str
    cell: str                           # which matrix cell was selected
    pillar: str                         # classification.pillar.value
    archetype: str                      # classification.archetype.value
    pillar_confidence: float
    archetype_confidence: float
    used_fallback: bool
    used_global_fallback: bool
    classifier_reasons: tuple[str, ...]
    variants_tried: tuple[str, ...]
    guardrail_reasons: tuple[str, ...]  # populated only when guardrails forced a downgrade

    def to_dict(self) -> dict:
        return asdict(self)


def _empty_profile() -> ContactProfile:
    return ContactProfile()


def generate_draft(
    profile: Optional[ContactProfile],
    *,
    seed: Optional[int] = None,
) -> GeneratedDraft:
    """
    Drive a single profile through classify → compose → guardrails. Never
    raises; never returns an empty draft; never lets a [bracket_token] escape.
    """
    profile = profile or _empty_profile()
    classification: Classification = classify(profile)

    guardrail_reasons: list[str] = []
    composed: ComposedDraft = compose(profile, classification, seed=seed)

    # First guardrail pass on the chosen composition.
    g: GuardrailResult = check(composed.subject, composed.body)
    if not g.ok:
        # Composition failed guardrails (banned word in a variant, etc).
        # Force the cell-fallback path by composing with an empty slot dict —
        # the composer will degrade to cell fallback, then global fallback.
        guardrail_reasons.extend(g.reasons)
        composed = compose(_empty_profile(), classification, seed=seed)
        g = check(composed.subject, composed.body)
        if not g.ok:
            # Even global fallback failed guardrails — shouldn't happen unless
            # someone edited strategy.yaml to include a banned word. Strip the
            # body to a known-safe last resort.
            guardrail_reasons.extend(g.reasons)
            return GeneratedDraft(
                subject="quick question",
                body="Saw your name come across our deal list. Open to a short call?",
                cell=composed.cell,
                pillar=classification.pillar.value,
                archetype=classification.archetype.value,
                pillar_confidence=classification.pillar_confidence,
                archetype_confidence=classification.archetype_confidence,
                used_fallback=False,
                used_global_fallback=True,
                classifier_reasons=classification.reasons,
                variants_tried=composed.variants_tried,
                guardrail_reasons=tuple(guardrail_reasons),
            )

    return GeneratedDraft(
        subject=composed.subject,
        body=g.polished,
        cell=composed.cell,
        pillar=classification.pillar.value,
        archetype=classification.archetype.value,
        pillar_confidence=classification.pillar_confidence,
        archetype_confidence=classification.archetype_confidence,
        used_fallback=composed.used_fallback,
        used_global_fallback=composed.used_global_fallback,
        classifier_reasons=classification.reasons,
        variants_tried=composed.variants_tried,
        guardrail_reasons=tuple(guardrail_reasons),
    )
