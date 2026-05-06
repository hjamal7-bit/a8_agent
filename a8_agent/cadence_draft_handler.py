"""
Cadence Draft Generation Handler

Generates drafts automatically when a contact enrolls in a cadence.
Uses Postgres LISTEN/NOTIFY for event-driven generation.

INTEGRATION:
1. FastAPI lifespan initializes the handler and starts listener
2. Database trigger sends notification on cadence_instances INSERT
3. Handler auto-generates drafts for the enrolled contact
4. Manual endpoints also available for regeneration
"""

import asyncio
import time
from datetime import datetime
from typing import Optional
from contextlib import asynccontextmanager

import asyncpg
from fastapi import APIRouter, HTTPException

from a8_agent.metrics import metrics_collector

router = APIRouter(tags=["cadence"])


class CadenceDraftGenerator:
    """Handles cadence draft generation on-demand and on enrollment via LISTEN/NOTIFY."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.pool: Optional[asyncpg.pool.Pool] = None
        self.listener_task: Optional[asyncio.Task] = None
        self.listener_conn: Optional[asyncpg.Connection] = None

    async def initialize(self):
        """Create connection pool and start listener."""
        self.pool = await asyncpg.create_pool(self.db_url, min_size=2, max_size=10)
        # Start listener in background
        self.listener_task = asyncio.create_task(self._start_listener())

    async def close(self):
        """Close connection pool and listener."""
        if self.listener_task:
            self.listener_task.cancel()
            try:
                await self.listener_task
            except asyncio.CancelledError:
                pass
        if self.listener_conn:
            await self.listener_conn.close()
        if self.pool:
            await self.pool.close()

    async def _start_listener(self):
        """Listen for cadence enrollments and auto-generate drafts."""
        try:
            self.listener_conn = await asyncpg.connect(self.db_url)
            await self.listener_conn.add_listener('cadence_enroll', self._on_cadence_enroll)
            print("✓ Cadence enrollment listener started")
            # Keep listening
            while True:
                await asyncio.sleep(3600)  # Just keep the task alive
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"✗ Listener error: {e}")

    def _on_cadence_enroll(self, connection, pid, channel, payload):
        """Callback when cadence enrollment notification is received."""
        # Schedule the generation in the event loop
        asyncio.create_task(self.generate_for_enrollment(payload))
        print(f"Auto-generating drafts for cadence instance {payload}")

    async def generate_for_enrollment(self, cadence_instance_id: str) -> dict:
        """
        Generate drafts when a contact is enrolled in a cadence.
        Called via:
          1. Database trigger (automatic on INSERT)
          2. POST /cadence/{cadence_instance_id}/generate-on-enroll (manual)

        For each touch in the cadence template, create one draft.

        Args:
            cadence_instance_id: UUID of newly created cadence_instance

        Returns:
            {
                "generated": [draft_ids],
                "skipped": int,
                "error": null or error message
            }
        """
        if not self.pool:
            raise RuntimeError("CadenceDraftGenerator not initialized")

        start_time = time.time()
        async with self.pool.acquire() as conn:
            try:
                # Get cadence instance and template
                instance = await conn.fetchrow(
                    """
                    SELECT ci.id, ci.cadence_template_id, ci.contact_id,
                           ct.name
                    FROM cadence_instances ci
                    JOIN cadence_templates ct ON ci.cadence_template_id = ct.id
                    WHERE ci.id = $1
                    """,
                    cadence_instance_id,
                )

                if not instance:
                    return {"error": f"Cadence instance {cadence_instance_id} not found"}

                template_name = instance["name"]
                template_id = instance["cadence_template_id"]
                contact_id = instance["contact_id"]

                # Get all touches for this template, ordered by sequence
                touches = await conn.fetch(
                    """
                    SELECT id, sequence_number, channel, hook, expected_outcome,
                           guidance, cta, tone_guidance, suggested_length_words
                    FROM cadence_touches
                    WHERE cadence_template_id = $1
                    ORDER BY sequence_number ASC
                    """,
                    template_id,
                )

                # Generate one draft per touch
                drafted_ids = []
                for touch in touches:
                    touch_seq = touch["sequence_number"]
                    
                    # Check if draft already exists for this touch
                    existing = await conn.fetchval(
                        """
                        SELECT COUNT(*) FROM drafts 
                        WHERE cadence_instance_id = $1 AND cadence_touch_id = $2
                        """,
                        cadence_instance_id,
                        touch["id"],
                    )

                    if existing > 0:
                        continue  # Skip, already drafted

                    # Create draft from touch template
                    draft_id = await conn.fetchval(
                        """
                        INSERT INTO drafts (
                            cadence_instance_id, cadence_touch_id, contact_id,
                            channel, subject, body, hook, expected_outcome,
                            sequence_number, is_cadence_draft, status,
                            created_from, created_at
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, true, 'pending_approval', 'cadence', NOW())
                        RETURNING id
                        """,
                        cadence_instance_id,
                        touch["id"],
                        contact_id,
                        touch["channel"],
                        touch["hook"],  # Use hook as subject for now
                        touch["guidance"] or "",  # Use guidance as body
                        touch["hook"],
                        touch["expected_outcome"],
                        touch_seq,
                    )

                    drafted_ids.append(draft_id)
                    metrics_collector.record_draft_generated()

                metrics_collector.record_cadence_enrollment()
                latency_ms = (time.time() - start_time) * 1000
                return {
                    "generated": drafted_ids,
                    "skipped": len(touches) - len(drafted_ids),
                    "error": None,
                    "latency_ms": latency_ms,
                }

            except Exception as e:
                metrics_collector.record_error("generate_for_enrollment")
                return {"error": str(e), "generated": [], "skipped": 0}

    async def regenerate_for_template(self, template_id: str, force: bool = False) -> dict:
        """
        Manually regenerate drafts for all active instances of a cadence template.

        Args:
            template_id: UUID of cadence_template
            force: If True, regenerate even if drafts exist

        Returns:
            {"total_instances": N, "generated": {instance_id: count}, "errors": []}
        """
        if not self.pool:
            raise RuntimeError("CadenceDraftGenerator not initialized")

        async with self.pool.acquire() as conn:
            # Get all active instances of this template
            instances = await conn.fetch(
                """
                SELECT id FROM cadence_instances
                WHERE cadence_template_id = $1 AND status = 'active'
                """,
                template_id,
            )

            results = {}
            errors = []

            for instance_row in instances:
                instance_id = instance_row["id"]
                try:
                    if force:
                        # Delete existing drafts for this instance
                        await conn.execute(
                            "DELETE FROM drafts WHERE cadence_instance_id = $1 AND is_cadence_draft = true",
                            instance_id,
                        )

                    # Generate new drafts
                    result = await self.generate_for_enrollment(instance_id)
                    results[instance_id] = len(result.get("generated", []))

                except Exception as e:
                    errors.append({"instance_id": instance_id, "error": str(e)})

            return {
                "total_instances": len(instances),
                "generated": results,
                "errors": errors,
            }


# Module-level instance (initialized in FastAPI lifespan)
_cadence_generator: Optional[CadenceDraftGenerator] = None


@asynccontextmanager
async def cadence_lifespan(app):
    """FastAPI lifespan context: initialize cadence handler on startup."""
    global _cadence_generator

    db_url = app.state.database_url
    _cadence_generator = CadenceDraftGenerator(db_url)
    await _cadence_generator.initialize()

    yield

    # Cleanup
    await _cadence_generator.close()


@router.post("/{cadence_instance_id}/generate-on-enroll")
async def enroll_generate(cadence_instance_id: str):
    """
    Generate all drafts for an enrolled contact immediately.

    Usage: POST /cadence/{uuid}/generate-on-enroll
    """
    if not _cadence_generator:
        raise HTTPException(500, "Cadence handler not initialized")

    result = await _cadence_generator.generate_for_enrollment(cadence_instance_id)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.post("/template/{template_id}/regenerate")
async def regenerate_template(template_id: str, force: bool = False):
    """
    Manual endpoint: regenerate drafts for all active instances of a template.

    Usage: POST /cadence/template/{uuid}/regenerate?force=true
    """
    if not _cadence_generator:
        raise HTTPException(500, "Cadence handler not initialized")

    result = await _cadence_generator.regenerate_for_template(template_id, force)
    return result
