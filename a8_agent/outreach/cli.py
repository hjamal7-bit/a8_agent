"""
CLI for the new outreach engine.

    python -m a8_agent.outreach.cli <contact_id>
    python -m a8_agent.outreach.cli --sample      # run against a few real contacts

Designed for quick eyeballing — not part of the production draft path.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import textwrap
from typing import Optional

from a8_agent.outreach.engine import generate_draft
from a8_agent.outreach.ingest import load_profile, profile_from_row


def _print_draft(label: str, profile, draft) -> None:
    print("=" * 72)
    print(f"  {label}")
    print("-" * 72)
    print(f"  contact      : {profile.first_name} {profile.last_name or ''} — {profile.title or '?'}")
    print(f"  company      : {profile.company or '?'}")
    print(f"  sector       : {profile.sector or '?'}")
    print(f"  cell         : {draft.cell}  (p={draft.pillar_confidence}, a={draft.archetype_confidence})")
    print(f"  fallback     : cell={draft.used_fallback}  global={draft.used_global_fallback}")
    if draft.classifier_reasons:
        print(f"  why          : {' | '.join(draft.classifier_reasons[:4])}")
    print()
    print(f"  Subject: {draft.subject}")
    print()
    print(textwrap.indent(draft.body, "  "))
    print()


async def _run_single(contact_id: str, dsn: str) -> int:
    import asyncpg
    conn = await asyncpg.connect(dsn)
    try:
        profile = await load_profile(conn, contact_id)
    finally:
        await conn.close()

    if profile is None:
        print(f"contact {contact_id} not found", file=sys.stderr)
        return 1

    draft = generate_draft(profile)
    _print_draft(f"contact_id={contact_id}", profile, draft)
    return 0


async def _run_sample(dsn: str, limit: int) -> int:
    import asyncpg
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT c.id::text AS contact_id
            FROM contacts c
            LEFT JOIN opcos o ON o.id = c.opco_id
            WHERE c.is_test_data = false
              AND c.deleted_at IS NULL
              AND c.name IS NOT NULL
              AND (c.affiliation IS NOT NULL OR o.name IS NOT NULL)
            ORDER BY c.updated_at DESC
            LIMIT $1
            """,
            limit,
        )
        for row in rows:
            profile = await load_profile(conn, row["contact_id"])
            if profile is None:
                continue
            draft = generate_draft(profile)
            _print_draft(f"contact_id={row['contact_id']}", profile, draft)
    finally:
        await conn.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate a cold outreach draft.")
    ap.add_argument("contact_id", nargs="?", help="UUID of the contact (omit with --sample).")
    ap.add_argument("--sample", action="store_true", help="Run against N recent contacts.")
    ap.add_argument("--limit", type=int, default=5, help="With --sample, how many.")
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL", "postgresql:///a8"))
    args = ap.parse_args()

    if args.sample:
        return asyncio.run(_run_sample(args.dsn, args.limit))
    if not args.contact_id:
        ap.error("contact_id required (or pass --sample)")
    return asyncio.run(_run_single(args.contact_id, args.dsn))


if __name__ == "__main__":
    sys.exit(main())
