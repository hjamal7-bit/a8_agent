"""
Pillar + archetype classifier.

Deterministic, rule-based. Each classification returns a Tag plus a confidence
score and the reason it picked that bucket — the engine logs reasons so a human
can audit why a draft was routed a given way.

The classifier is split into two stages because they're independent:
  pillar    — what kind of company is this?    (IP-Rich vs Distribution-Heavy)
  archetype — who is sitting across the table? (Founder / Corp Exec / PE / Family)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from a8_agent.outreach.ingest import ContactProfile


class Pillar(str, Enum):
    IP_RICH = "ip_rich"
    DISTRIBUTION_HEAVY = "distribution_heavy"


class Archetype(str, Enum):
    FOUNDER_BOOTSTRAPPED = "founder_bootstrapped"
    CORPORATE_EXECUTIVE = "corporate_executive"
    PE_OWNED = "pe_owned"
    GENERATIONAL_FAMILY = "generational_family"


@dataclass(frozen=True)
class Classification:
    pillar: Pillar
    archetype: Archetype
    pillar_confidence: float        # 0.0 – 1.0
    archetype_confidence: float
    reasons: tuple[str, ...]        # human-readable trail of which rules fired


# ---------------------------------------------------------------------------
# Lexicons. Kept as module-level constants so they're cheap and grep-able.
# Tune these as new sectors come into the funnel.
# ---------------------------------------------------------------------------

_IP_RICH_SECTOR_TOKENS = {
    "software", "saas", "tech", "ai", "ml", "ag tech", "med tech", "data tech",
    "platform", "biotech", "medtech", "fintech", "deeptech", "deep tech",
    "robotics", "iot", "patent", "patents", "proprietary",
}

_DISTRIBUTION_SECTOR_TOKENS = {
    "distribution", "logistics", "supply chain", "trucking", "freight",
    "warehouse", "warehousing", "fulfillment", "last mile", "last-mile",
    "delivery", "dealer", "wholesale", "wholesaler", "industrial gas distribution",
    "retail", "route", "fleet",
}

_IP_RICH_TEXT_TOKENS = {
    "patent", "patents", "proprietary", "firmware", "algorithm", "ip portfolio",
    "trademark", "license", "licensing", "software", "platform",
}

_DISTRIBUTION_TEXT_TOKENS = {
    "route", "routes", "distribution center", "dc network", "depot", "depots",
    "fleet", "warehouse", "warehouses", "service area", "territory",
    "regional dominance", "market share in",
}

# Ownership-type values seen in opcos.ownership_type — mapped to archetypes.
_OWNERSHIP_TYPE_TO_ARCHETYPE = {
    "founder_led": Archetype.FOUNDER_BOOTSTRAPPED,
    "private_equity": Archetype.PE_OWNED,
    "pe_backed": Archetype.PE_OWNED,
    "family_owned": Archetype.GENERATIONAL_FAMILY,
    "family_office": Archetype.GENERATIONAL_FAMILY,
    "subsidiary": Archetype.CORPORATE_EXECUTIVE,
}

_FOUNDER_TITLE_TOKENS = {
    "founder", "co-founder", "cofounder", "founding", "creator", "owner",
}

_EXEC_TITLE_TOKENS = {
    "ceo", "president", "coo", "cfo", "cto", "general manager",
    "managing director", "evp", "svp",
}

# A title containing one of these tokens — combined with an affiliation that
# differs from the portfolio company name — is the operating-partner signature.
_PE_OPERATING_TITLE_TOKENS = {
    "operating partner", "operating advisor", "operating executive",
    "chairman of the board", "board chairman",
    "industry partner", "executive partner", "venture partner",
}

# ---------------------------------------------------------------------------

# Phrases that flag a contact as the *hired* operator (not the founder), even
# when the company itself is still founder-owned. The presence of any one of
# these in the contact's notes is enough.
_HIRED_OPERATOR_PHRASES = (
    "non-clinical ceo", "non-founder ceo", "professional ceo", "hired ceo",
    "hired in to run", "brought in to run", "brought in as ceo",
    "ceo hire", "external ceo", "outside ceo", "non-clinical operator",
)


def _looks_like_hired_operator(profile: "ContactProfile") -> bool:
    notes = (profile.notes or "").lower()
    if not notes:
        return False
    return any(p in notes for p in _HIRED_OPERATOR_PHRASES)


def _contains_any(haystack: str, tokens: set[str]) -> Optional[str]:
    """Return the first matching token, or None."""
    h = haystack.lower()
    for t in tokens:
        # Word-boundary match so "ip" doesn't fire on "ship".
        if re.search(rf"\b{re.escape(t)}\b", h):
            return t
    return None


def _classify_pillar(profile: "ContactProfile") -> tuple[Pillar, float, list[str]]:
    reasons: list[str] = []
    ip_score = 0
    dist_score = 0

    # Direct signals from ingest already extracted these — they're worth a lot.
    if profile.ip_signal:
        ip_score += 3
        reasons.append("ip_signal present")
    if profile.distribution_signal:
        dist_score += 3
        reasons.append("distribution_signal present")

    # Note: company name is intentionally NOT in the haystack — "Dental Depot"
    # would falsely fire the "depot" distribution token.
    haystack = " ".join(
        s for s in [
            profile.sector,
            profile.vertical_specific_signals,
            profile.notes,
            profile.recent_news,
        ] if s
    )

    if haystack:
        if hit := _contains_any(haystack, _IP_RICH_SECTOR_TOKENS):
            ip_score += 2
            reasons.append(f"ip-rich sector token: '{hit}'")
        if hit := _contains_any(haystack, _DISTRIBUTION_SECTOR_TOKENS):
            dist_score += 2
            reasons.append(f"distribution sector token: '{hit}'")
        if hit := _contains_any(haystack, _IP_RICH_TEXT_TOKENS):
            ip_score += 1
            reasons.append(f"ip-rich body token: '{hit}'")
        if hit := _contains_any(haystack, _DISTRIBUTION_TEXT_TOKENS):
            dist_score += 1
            reasons.append(f"distribution body token: '{hit}'")

    # Tie-breaker: default to IP-rich. Most of the deal book skews that way, and
    # the IP-rich copy still reads well for borderline cases.
    if ip_score >= dist_score:
        pillar = Pillar.IP_RICH
        total = ip_score + dist_score
        conf = (ip_score / total) if total > 0 else 0.5
    else:
        pillar = Pillar.DISTRIBUTION_HEAVY
        total = ip_score + dist_score
        conf = (dist_score / total) if total > 0 else 0.5

    if total == 0:
        reasons.append("no pillar signals; defaulting to ip_rich at 0.5")

    return pillar, conf, reasons


def _classify_archetype(profile: "ContactProfile") -> tuple[Archetype, float, list[str]]:
    reasons: list[str] = []

    # Strongest signal: explicit ownership_type on the opco. We trust it —
    # EXCEPT when the contact themselves is clearly a hired operator at a
    # founder-owned shop. In that case, opco is still founder_led at the
    # cap-table level, but the *person we're writing to* is the professional
    # CEO. Route to corporate_executive so the copy doesn't tell a hired CEO
    # "what you built" — he didn't build it.
    if profile.ownership_type:
        mapped = _OWNERSHIP_TYPE_TO_ARCHETYPE.get(profile.ownership_type.lower())
        if mapped is not None:
            if mapped == Archetype.FOUNDER_BOOTSTRAPPED and _looks_like_hired_operator(profile):
                reasons.append(
                    f"opco.ownership_type='{profile.ownership_type}' but contact "
                    f"notes flag hired-operator pattern → corporate_executive"
                )
                return Archetype.CORPORATE_EXECUTIVE, 0.85, reasons
            reasons.append(f"opco.ownership_type='{profile.ownership_type}'")
            return mapped, 0.9, reasons

    # Second-strongest: explicit PE sponsor named on the opco.
    if profile.pe_sponsor:
        reasons.append(f"pe_sponsor='{profile.pe_sponsor}'")
        return Archetype.PE_OWNED, 0.85, reasons

    # Operating-partner signature: title contains a PE-board/operating-partner
    # token AND the contact's affiliation differs from the company they oversee
    # (i.e., the affiliation IS the sponsor firm — e.g., Kohlberg overseeing
    # Spinal Elements). Strong signal even when opco.ownership_type='unknown'.
    title_lower = (profile.title or "").lower()
    if title_lower and _contains_any(title_lower, _PE_OPERATING_TITLE_TOKENS):
        aff = (profile.raw.get("affiliation") or "").strip() if profile.raw else ""
        if aff and profile.company and aff.lower() != profile.company.lower():
            reasons.append(
                f"PE operating-partner pattern: title='{profile.title}', "
                f"affiliation='{aff}' != company='{profile.company}'"
            )
            return Archetype.PE_OWNED, 0.8, reasons
        # Even without an affiliation gap, the title alone is a meaningful hint.
        reasons.append(f"PE operating-partner title: '{profile.title}'")
        return Archetype.PE_OWNED, 0.65, reasons

    # CRM psychological_segment is often a curated tag — honor it when present.
    seg = (profile.psychological_segment or "").lower()
    if seg == "founder_legacy":
        reasons.append("psych_segment='founder_legacy'")
        return Archetype.FOUNDER_BOOTSTRAPPED, 0.8, reasons
    if seg in {"family_steward", "generational"}:
        reasons.append(f"psych_segment='{seg}'")
        return Archetype.GENERATIONAL_FAMILY, 0.8, reasons
    if seg in {"corporate_operator", "professional_executive"}:
        reasons.append(f"psych_segment='{seg}'")
        return Archetype.CORPORATE_EXECUTIVE, 0.8, reasons

    # Title-based heuristic.
    title = (profile.title or "").lower()
    if title:
        if _contains_any(title, _FOUNDER_TITLE_TOKENS):
            reasons.append(f"title contains founder token: '{title}'")
            return Archetype.FOUNDER_BOOTSTRAPPED, 0.65, reasons
        if _contains_any(title, _EXEC_TITLE_TOKENS):
            reasons.append(f"title contains exec token: '{title}'")
            # Without ownership context, an exec defaults to corporate executive.
            return Archetype.CORPORATE_EXECUTIVE, 0.55, reasons

    # Notes-based heuristic for family ownership.
    if profile.family_signal:
        reasons.append(f"family_signal='{profile.family_signal}'")
        return Archetype.GENERATIONAL_FAMILY, 0.6, reasons

    # Fall back. CORPORATE_EXECUTIVE is the safest neutral voice — never overly
    # familiar, never assumes a sponsor, never wrongly thanks them for "what
    # you built".
    reasons.append("no archetype signals; defaulting to corporate_executive at 0.4")
    return Archetype.CORPORATE_EXECUTIVE, 0.4, reasons


def classify(profile: "ContactProfile") -> Classification:
    """
    Tag a ContactProfile with its pillar + archetype.

    Returns a Classification with confidence scores and a human-readable list of
    which rules fired. The engine passes the Classification through to the
    composer so the matrix cell is picked deterministically.
    """
    pillar, p_conf, p_reasons = _classify_pillar(profile)
    archetype, a_conf, a_reasons = _classify_archetype(profile)
    return Classification(
        pillar=pillar,
        archetype=archetype,
        pillar_confidence=round(p_conf, 2),
        archetype_confidence=round(a_conf, 2),
        reasons=tuple(["pillar: " + r for r in p_reasons]
                      + ["archetype: " + r for r in a_reasons]),
    )
