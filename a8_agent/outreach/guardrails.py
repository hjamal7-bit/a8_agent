"""
Output guardrails for the new outreach engine.

These are *enforced*, not stylistic suggestions. A draft that fails a guardrail
is rejected by the engine and the matrix cell's fallback is used instead. If
the fallback also fails (rare — only if the cell author leaves a bug), the
global_fallback from strategy.yaml is used.

Banned-word list lives here, not in the YAML, because it's a hard constraint
that should NOT be edited casually by template authors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Hard banned tokens — any draft containing one of these (case-insensitive,
# word-boundary) is rejected. Phrases use \b-aware matching to avoid catching
# them inside larger words.
BANNED_TOKENS = (
    # Corporate jargon
    "synergy", "synergies", "value-add", "value add", "leverage", "leveraging",
    "optimize", "optimization", "ecosystem", "robust", "world-class",
    "best-in-class", "mission-critical", "thought leader", "deep dive",
    "going forward", "at scale", "holistic", "paradigm", "actionable",
    "circle back", "touch base", "touching base",
    # Generic fluff openers
    "hope this finds you well", "hope this email finds you well",
    "i hope you are doing well", "trust this finds you well",
    "i hope you're doing well", "happy monday", "happy friday",
    # Salesy filler
    "unlock value", "drive value", "move the needle",
    # Mind-reading phrases that interpret the recipient's signals out loud.
    # The discipline is "show you saw it, don't interpret it" — these phrases
    # always cross that line.
    "ahead of something", "before something bigger", "runs ahead of",
    "sounds like you're planning", "sounds like you are planning",
    "looks like you're planning", "looks like you are planning",
    "you're probably thinking about", "you are probably thinking about",
    "tipping your hand", "reading the tea leaves",
)

# Big words where small ones work. Replace, don't reject (those are noise, not
# style breaks worth blocking on).
BIG_WORD_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\butilize\b", "use"),
    (r"\butilization\b", "use"),
    (r"\bcommence\b", "start"),
    (r"\bterminate\b", "end"),
    (r"\bassist\b", "help"),
    (r"\bendeavor\b", "try"),
    (r"\bfacilitate\b", "help"),
    (r"\bdemonstrate\b", "show"),
    (r"\battempt\b", "try"),
    (r"\bsubsequent to\b", "after"),
    (r"\bprior to\b", "before"),
    (r"\bin order to\b", "to"),
)

# Pattern for *any* leftover slot placeholder — e.g. "{first_name}", "[company]",
# "<sector>". If this matches the rendered output we have a bug in the variant
# selector and must NOT ship the draft.
LEFTOVER_PLACEHOLDER_PAT = re.compile(r"[\{\[\<][a-z_]{2,40}[\}\]\>]", re.IGNORECASE)

MAX_SENTENCES = 4
MAX_SUBJECT_CHARS = 60


@dataclass(frozen=True)
class GuardrailResult:
    ok: bool
    reasons: tuple[str, ...]      # populated when ok=False
    polished: str                 # body with big-word replacements applied


def _count_sentences(body: str) -> int:
    # Sentences end with . ! ? — collapse blank lines so paragraph breaks don't
    # change the count. We treat consecutive sentence-enders as one.
    chunks = re.split(r"[.!?]+(?:\s|$)", body.strip())
    return sum(1 for c in chunks if c.strip())


def _apply_big_word_replacements(body: str) -> str:
    out = body
    for pat, repl in BIG_WORD_REPLACEMENTS:
        out = re.sub(pat, repl, out, flags=re.IGNORECASE)
    return out


def _find_banned(text: str) -> list[str]:
    hits: list[str] = []
    lower = text.lower()
    for token in BANNED_TOKENS:
        # Phrases (containing space or hyphen) match as substring; single words
        # use word-boundary regex.
        if " " in token or "-" in token:
            if token in lower:
                hits.append(token)
        else:
            if re.search(rf"\b{re.escape(token)}\b", lower):
                hits.append(token)
    return hits


def check(subject: str, body: str) -> GuardrailResult:
    """
    Run all guardrails. Returns GuardrailResult with .ok=False (and reasons) if
    the draft must be rejected, or .ok=True with a polished body.
    """
    reasons: list[str] = []

    if not subject or not subject.strip():
        reasons.append("empty subject")
    elif len(subject) > MAX_SUBJECT_CHARS:
        reasons.append(f"subject too long ({len(subject)} > {MAX_SUBJECT_CHARS})")
    elif "—" in subject and subject.count("—") > 1:
        # Single em-dash is allowed (used in cell variants). Multiple suggests
        # a botched template render.
        reasons.append("multiple em-dashes in subject")

    if not body or not body.strip():
        reasons.append("empty body")

    leftovers = LEFTOVER_PLACEHOLDER_PAT.findall(f"{subject}\n{body}")
    if leftovers:
        reasons.append(f"unresolved placeholders: {leftovers}")

    sentence_count = _count_sentences(body or "")
    if sentence_count > MAX_SENTENCES:
        reasons.append(f"too many sentences ({sentence_count} > {MAX_SENTENCES})")
    if sentence_count == 0:
        reasons.append("zero sentences in body")

    banned = _find_banned(f"{subject}\n{body}")
    if banned:
        reasons.append(f"banned tokens: {banned}")

    if reasons:
        return GuardrailResult(ok=False, reasons=tuple(reasons), polished=body or "")

    return GuardrailResult(ok=True, reasons=(), polished=_apply_big_word_replacements(body))
