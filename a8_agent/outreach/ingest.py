"""
Ingestion layer for the outreach engine.

A ContactProfile is the *only* shape downstream code sees. The Postgres loader
joins contacts ↔ opcos ↔ techcos and projects everything into this dataclass.

Anyone who wants to drive the engine from a different source (CSV import,
LinkedIn webhook, manual paste) just builds a ContactProfile directly and skips
the loader.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional, Any, Mapping

# ---------------------------------------------------------------------------
# ContactProfile: the normalized input to the engine.
# ---------------------------------------------------------------------------

@dataclass
class ContactProfile:
    # Identity
    contact_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None

    # Company
    company: Optional[str] = None          # contacts.affiliation or opco/techco name
    sector: Optional[str] = None           # industry_vertical / opcos.industry / techcos summary tag
    region: Optional[str] = None           # parsed from notes if present
    website: Optional[str] = None

    # Background signals (free-text — used both for classification and as slot
    # material for the hook).
    prior_employer: Optional[str] = None
    tenure_years: Optional[int] = None
    recent_news: Optional[str] = None
    notes: Optional[str] = None

    # Ownership signals (used by classifier)
    ownership_type: Optional[str] = None         # opcos.ownership_type: founder_led / private_equity / family_owned / ...
    pe_sponsor: Optional[str] = None             # opcos.pe_investor_name
    founder_basis_status: Optional[str] = None
    family_signal: Optional[str] = None          # e.g. "three generations", "40 years"

    # Pillar signals (used by classifier)
    ip_signal: Optional[str] = None              # e.g. "ProWire patent portfolio", "proprietary firmware"
    distribution_signal: Optional[str] = None    # e.g. "12 DCs across the Southeast"
    metric_signal: Optional[str] = None          # e.g. "40% YoY growth", "$22m EBITDA"

    # Pre-tagged CRM segments — taken as hints, not overrides
    psychological_segment: Optional[str] = None  # contacts.psychological_segment
    vertical_specific_signals: Optional[str] = None
    is_decision_maker: bool = False

    # Channel
    channel: str = "email"                       # "email" | "sms"
    email: Optional[str] = None

    # Raw payload (kept around for debugging / future fields)
    raw: Mapping[str, Any] = field(default_factory=dict)

    def as_slot_dict(self) -> dict[str, str]:
        """
        Return only the fields suitable as template slots. A slot value of "" or
        None means "this slot cannot be filled" — variants requiring it will be
        rejected by the composer.

        Slot values are normalized to title-case for proper nouns that came out
        of the CRM in all-caps ("BRAVO SERVICES" → "Bravo Services") — those
        all-caps strings are a dead giveaway that the email is template-driven.
        """
        slots = {
            "first_name": self.first_name,
            "company": self.company,
            "sector": self.sector,
            "region": self.region,
            "prior_employer": _normalize_proper_noun(self.prior_employer),
            "pe_sponsor": _normalize_proper_noun(self.pe_sponsor),
            "family_signal": self.family_signal,
            "ip_signal": self.ip_signal,
            "distribution_signal": self.distribution_signal,
            "metric_signal": self.metric_signal,
        }
        return {k: (v.strip() if isinstance(v, str) else "") for k, v in slots.items() if v}


# ---------------------------------------------------------------------------
# Helpers — small, pure, easy to unit test.
# ---------------------------------------------------------------------------

_FIRST_NAME_HONORIFICS = re.compile(r"^(dr|mr|mrs|ms|prof)\.?\s+", re.IGNORECASE)

# Tokens that should stay all-caps if a proper-noun value contains them.
_PROPER_NOUN_ACRONYMS = {
    "LLC", "LP", "LLP", "PLC", "GP", "PE", "VC", "IP", "AI", "ML",
    "USA", "US", "UK", "EU", "NA", "EMEA", "APAC",
    "II", "III", "IV",
}


def _normalize_proper_noun(value: Optional[str]) -> Optional[str]:
    """
    Convert an ALL-CAPS proper noun from the CRM into something a human would
    type. "BRAVO SERVICES" → "Bravo Services". "VISTA EQUITY PARTNERS" →
    "Vista Equity Partners". Leaves already-mixed-case strings alone, and
    preserves known acronyms (LLC, LP, etc.).
    """
    if not value:
        return value
    s = value.strip()
    if not s:
        return s
    # Heuristic: only touch strings that are predominantly uppercase. Leave
    # "Property Affinity" or "Kohlberg & Company" untouched.
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return s
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    if upper_ratio < 0.7:
        return s

    parts = re.split(r"(\s+|&|,|\.|-)", s)
    out = []
    for part in parts:
        stripped = part.strip()
        if not stripped or not stripped.isalpha():
            out.append(part)
            continue
        if stripped.upper() in _PROPER_NOUN_ACRONYMS:
            out.append(stripped.upper())
        else:
            out.append(stripped.capitalize())
    return "".join(out)


def split_first_name(full_name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Best-effort first/last from a name string. Strips honorifics ("Dr. Glenn"
    → "Glenn"). Returns (first, last) — either may be None.
    """
    if not full_name:
        return None, None
    cleaned = _FIRST_NAME_HONORIFICS.sub("", full_name).strip()
    # Drop trailing credentials like ", DMD, MSD"
    cleaned = cleaned.split(",")[0].strip()
    parts = cleaned.split()
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])


_REGION_PAT = re.compile(
    r"\b(?:based in|out of|headquartered in)\s+([A-Z][\w\s,]+?)(?:\.|$|;|\n)",
    re.IGNORECASE,
)


def extract_region(notes: Optional[str]) -> Optional[str]:
    if not notes:
        return None
    m = _REGION_PAT.search(notes)
    if not m:
        return None
    region = m.group(1).strip().rstrip(".,")
    return region or None


_PRIOR_EMPLOYER_PAT = re.compile(
    # "prior experience at X" / "previously at X" / "formerly X" / "prior role at X"
    # / "ex-X" / "from X" (when prefaced by "joined from"/"came from")
    r"(?:"
    r"prior(?:ly)?(?:\s+(?:experience|role|position|stint|tenure))?\s+(?:at|with)\s+"
    r"|previously(?:\s+(?:at|with|ran|led|of))?\s+"
    r"|formerly(?:\s+(?:at|with|of))?\s+"
    r"|joined\s+from\s+"
    r"|came\s+from\s+"
    r"|ex[-\s]"
    r")"
    r"([A-Z][\w&\-\. ]{1,60}?)"
    r"(?=\s+and\b|\.|,|;|\s+\(|$)",
    re.IGNORECASE,
)


def extract_prior_employer(notes: Optional[str]) -> Optional[str]:
    """
    Return the most-recent prior employer name. We prefer the first match in
    the text — when a profile lists "Prior experience at A and B", A is almost
    always the more relevant one (most recent / most senior).
    """
    if not notes:
        return None
    m = _PRIOR_EMPLOYER_PAT.search(notes)
    if not m:
        return None
    name = m.group(1).strip().rstrip(".,")
    # Trim a trailing " and" if the lookahead let one through.
    name = re.sub(r"\s+and$", "", name, flags=re.IGNORECASE)
    return name or None


_FAMILY_TENURE_PAT = re.compile(
    r"\b(\d+\s+(?:years?|decades?)|three generations|four generations|two generations)\b",
    re.IGNORECASE,
)


def extract_family_signal(notes: Optional[str], vertical_signals: Optional[str]) -> Optional[str]:
    for src in (notes, vertical_signals):
        if not src:
            continue
        m = _FAMILY_TENURE_PAT.search(src)
        if m:
            return m.group(1).lower()
    return None


# ---------------------------------------------------------------------------
# Postgres loader. Optional — guarded import so this module is usable without
# asyncpg/psycopg present.
# ---------------------------------------------------------------------------

# This is the single SELECT used by the loader. Kept here (not in a .sql file)
# so the field projection lives next to the dataclass it populates.
_PROFILE_QUERY = """
SELECT
    c.id::text                                AS contact_id,
    c.name                                    AS full_name,
    c.title                                   AS title,
    c.affiliation                             AS affiliation,
    c.industry_vertical                       AS industry_vertical,
    c.notes                                   AS notes,
    c.psychological_segment                   AS psychological_segment,
    c.vertical_specific_signals               AS vertical_specific_signals,
    c.is_decision_maker                       AS is_decision_maker,
    c.email                                   AS email,
    o.name                                    AS opco_name,
    o.industry                                AS opco_industry,
    o.ownership_type                          AS opco_ownership_type,
    o.pe_investor_name                        AS opco_pe_investor_name,
    o.recent_news_summary                     AS opco_recent_news,
    o.website                                 AS opco_website,
    o.summary                                 AS opco_summary,
    o.revenue_latest_mm                       AS opco_revenue_mm,
    o.ebitda_latest_mm                        AS opco_ebitda_mm,
    o.revenue_growth_3yr_pct                  AS opco_growth_pct,
    o.founder_basis_status                    AS opco_founder_basis,
    t.name                                    AS techco_name,
    t.tech_description                        AS techco_tech_description,
    t.recent_news_summary                     AS techco_recent_news,
    t.summary                                 AS techco_summary,
    t.website                                 AS techco_website
FROM contacts c
LEFT JOIN opcos   o ON o.id = c.opco_id
LEFT JOIN techcos t ON t.id = c.techco_id
WHERE c.id = $1
"""


def profile_from_row(row: Mapping[str, Any]) -> ContactProfile:
    """
    Build a ContactProfile from a single joined contacts+opcos+techcos row.
    Pure function — easy to test without a DB.
    """
    first, last = split_first_name(row.get("full_name"))
    notes = row.get("notes")
    vertical_signals = row.get("vertical_specific_signals")

    # Company name resolution: prefer the joined entity name over the free-text
    # affiliation, since the affiliation field is sometimes stale/dirty.
    company = (
        row.get("opco_name")
        or row.get("techco_name")
        or row.get("affiliation")
    )

    # Sector: industry_vertical on the contact wins, then the entity's industry.
    sector = (
        row.get("industry_vertical")
        or row.get("opco_industry")
        or _summary_tag(row.get("techco_summary"))
    )

    recent_news = row.get("opco_recent_news") or row.get("techco_recent_news")

    # Metric signal — built from financials if present
    metric_signal = _format_metric_signal(
        revenue_mm=row.get("opco_revenue_mm"),
        ebitda_mm=row.get("opco_ebitda_mm"),
        growth_pct=row.get("opco_growth_pct"),
    )

    # IP signal — derived from techco description if there's a real tech entity
    ip_signal = _format_ip_signal(row.get("techco_tech_description"))

    # PE sponsor: opco.pe_investor_name wins. Otherwise, if the contact's
    # affiliation differs from the company name and the title looks like an
    # operating-partner role, the affiliation IS the sponsor firm.
    pe_sponsor = row.get("opco_pe_investor_name") or _infer_sponsor_from_affiliation(
        affiliation=row.get("affiliation"),
        title=row.get("title"),
        company=company,
    )

    return ContactProfile(
        contact_id=row.get("contact_id"),
        first_name=first,
        last_name=last,
        title=row.get("title"),
        company=company,
        sector=sector,
        region=extract_region(notes),
        website=row.get("opco_website") or row.get("techco_website"),
        prior_employer=extract_prior_employer(notes),
        recent_news=recent_news,
        notes=notes,
        ownership_type=row.get("opco_ownership_type"),
        pe_sponsor=pe_sponsor,
        founder_basis_status=row.get("opco_founder_basis"),
        family_signal=extract_family_signal(notes, vertical_signals),
        ip_signal=ip_signal,
        distribution_signal=_format_distribution_signal(row.get("opco_summary"), notes),
        metric_signal=metric_signal,
        psychological_segment=row.get("psychological_segment"),
        vertical_specific_signals=vertical_signals,
        is_decision_maker=bool(row.get("is_decision_maker")),
        email=row.get("email"),
        raw=dict(row),
    )


def _summary_tag(summary: Optional[str]) -> Optional[str]:
    if not summary:
        return None
    # Take the first comma/period-delimited noun chunk as a coarse sector hint.
    head = re.split(r"[.,]", summary, maxsplit=1)[0].strip()
    return head or None


def _format_metric_signal(
    revenue_mm: Optional[float],
    ebitda_mm: Optional[float],
    growth_pct: Optional[float],
) -> Optional[str]:
    pieces: list[str] = []
    if growth_pct is not None and growth_pct > 0:
        pieces.append(f"{int(round(float(growth_pct)))}% growth")
    if ebitda_mm is not None and float(ebitda_mm) > 0:
        pieces.append(f"${float(ebitda_mm):.0f}m EBITDA")
    elif revenue_mm is not None and float(revenue_mm) > 0:
        pieces.append(f"${float(revenue_mm):.0f}m revenue")
    if not pieces:
        return None
    return " on ".join(pieces) if len(pieces) == 2 else pieces[0]


def _format_ip_signal(tech_description: Optional[str]) -> Optional[str]:
    if not tech_description:
        return None
    # First clause, trimmed — keeps the hook tight.
    first_clause = re.split(r"[.;]", tech_description, maxsplit=1)[0].strip()
    if len(first_clause) < 4 or len(first_clause) > 90:
        return None
    return first_clause


_PE_OP_TITLE_RE = re.compile(
    r"\b(operating partner|operating advisor|operating executive|"
    r"chairman of the board|board chairman|industry partner|"
    r"executive partner|venture partner)\b",
    re.IGNORECASE,
)


def _infer_sponsor_from_affiliation(
    affiliation: Optional[str],
    title: Optional[str],
    company: Optional[str],
) -> Optional[str]:
    """
    When the contact's listed affiliation differs from the portfolio company
    they oversee AND the title looks like a PE operating role, the affiliation
    IS the sponsor firm. (E.g., Matt Jennings — affiliation "Kohlberg & Company",
    company "Spinal Elements", title "Senior Operating Partner, Chairman".)
    """
    if not affiliation or not title or not company:
        return None
    if affiliation.strip().lower() == company.strip().lower():
        return None
    if not _PE_OP_TITLE_RE.search(title):
        return None
    return affiliation.strip()


def _format_distribution_signal(
    opco_summary: Optional[str], notes: Optional[str]
) -> Optional[str]:
    """
    Pull a distribution-pattern detail (route density, DC count, region coverage)
    out of free text. Conservative: only returns a value if a recognizable
    pattern is present.
    """
    for src in (opco_summary, notes):
        if not src:
            continue
        m = re.search(
            r"\b(\d+\s+(?:DCs?|distribution centers?|hubs?|warehouses?|routes?|trucks?)|"
            r"\d+-state|\d+\s+states?)\b",
            src,
            re.IGNORECASE,
        )
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Public loader — wraps asyncpg. Sync wrapper provided for CLI / tests.
# ---------------------------------------------------------------------------

async def load_profile(conn, contact_id: str) -> Optional[ContactProfile]:
    """
    Fetch one ContactProfile by contact UUID. Pass any asyncpg-compatible
    connection or pool.acquire() context.
    """
    row = await conn.fetchrow(_PROFILE_QUERY, contact_id)
    if row is None:
        return None
    return profile_from_row(dict(row))


def load_profile_sync(contact_id: str, dsn: Optional[str] = None) -> Optional[ContactProfile]:
    """Synchronous convenience for CLI / scripts. Spins its own event loop."""
    import asyncio
    import asyncpg
    import os

    dsn = dsn or os.environ.get("DATABASE_URL") or "postgresql:///a8"

    async def _run():
        conn = await asyncpg.connect(dsn)
        try:
            return await load_profile(conn, contact_id)
        finally:
            await conn.close()

    return asyncio.run(_run())
