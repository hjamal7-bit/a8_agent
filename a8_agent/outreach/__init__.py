"""
a8_agent.outreach — cold outreach draft generation, rebuilt from scratch.

This module replaces the legacy hook/guidance copy-into-draft path in
cadence_draft_handler.py. Nothing in here imports from or references the
legacy generator; all template logic, prompt strings, and slot tokens are
new.

Entry point:
    from a8_agent.outreach.engine import generate_draft
    draft = generate_draft(profile)
"""

from a8_agent.outreach.engine import generate_draft, GeneratedDraft
from a8_agent.outreach.ingest import ContactProfile, load_profile
from a8_agent.outreach.classify import Pillar, Archetype, classify

__all__ = [
    "generate_draft",
    "GeneratedDraft",
    "ContactProfile",
    "load_profile",
    "Pillar",
    "Archetype",
    "classify",
]
