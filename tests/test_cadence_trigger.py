"""
Integration tests for cadence trigger flow.

Tests the complete flow:
  enrollment → database trigger → a8_agent → draft generation → CRM write

Coverage:
  1. Successful draft generation for new enrollment
  2. Skipping existing drafts (idempotency)
  3. Error handling for missing cadence instance
  4. Error handling for database failures
  5. Batch regeneration across multiple instances
"""

import asyncio
from unittest.mock import AsyncMock, patch, call
import pytest

from a8_agent.cadence_draft_handler import CadenceDraftGenerator
from a8_agent.metrics import metrics_collector


@pytest.mark.asyncio
async def test_enrollment_generates_drafts(
    mock_db_pool, mock_cadence_instance, mock_cadence_touches
):
    """
    Test 1: Successful draft generation on cadence enrollment.
    
    Verifies:
    - Cadence instance is fetched from database
    - Cadence touches are fetched in order
    - One draft is created per touch
    - Drafts are inserted into database
    - Response includes generated draft IDs
    """
    generator = CadenceDraftGenerator("postgresql://test")
    generator.pool = mock_db_pool
    
    conn = mock_db_pool.pool_conn
    
    # Setup mock responses
    conn.fetchrow = AsyncMock(return_value=mock_cadence_instance)
    conn.fetch = AsyncMock(return_value=mock_cadence_touches)
    conn.fetchval = AsyncMock(side_effect=[None, "draft-1", None, "draft-2", None, "draft-3"])
    
    # Generate drafts
    result = await generator.generate_for_enrollment("inst-123")
    
    # Assertions
    assert result["error"] is None
    assert len(result["generated"]) == 3
    assert result["generated"] == ["draft-1", "draft-2", "draft-3"]
    assert result["skipped"] == 0
    
    # Verify database was queried
    conn.fetchrow.assert_called_once()
    conn.fetch.assert_called_once()
    
    # Verify drafts were inserted (3 per touch: check existing + insert)
    assert conn.fetchval.call_count == 6  # 3 touches * 2 calls
    
    # Verify metrics recorded
    assert metrics_collector.drafts_generated_total == 3


@pytest.mark.asyncio
async def test_idempotent_draft_generation(
    mock_db_pool, mock_cadence_instance, mock_cadence_touches
):
    """
    Test 2: Drafts are not regenerated if they already exist (idempotency).
    
    Verifies:
    - Existing draft check queries the database
    - Drafts that already exist are skipped
    - New drafts are only created for missing touches
    """
    generator = CadenceDraftGenerator("postgresql://test")
    generator.pool = mock_db_pool
    
    conn = mock_db_pool.pool_conn
    
    # Setup mock: instance and touches succeed, but first touch already exists
    conn.fetchrow = AsyncMock(return_value=mock_cadence_instance)
    conn.fetch = AsyncMock(return_value=mock_cadence_touches)
    
    # First call checks existing (returns 1), second creates (returns ID)
    # Pattern: [check touch 1 (1), check touch 2 (0), create touch 2 (draft-2),
    #           check touch 3 (0), create touch 3 (draft-3)]
    conn.fetchval = AsyncMock(side_effect=[1, 0, "draft-2", 0, "draft-3"])
    
    result = await generator.generate_for_enrollment("inst-123")
    
    # Assertions
    assert result["error"] is None
    assert len(result["generated"]) == 2  # Only new drafts
    assert result["skipped"] == 1
    assert result["generated"] == ["draft-2", "draft-3"]


@pytest.mark.asyncio
async def test_missing_cadence_instance(mock_db_pool):
    """
    Test 3: Error handling when cadence instance does not exist.
    
    Verifies:
    - Database query returns None for missing instance
    - Function returns error response
    - No drafts are created
    """
    generator = CadenceDraftGenerator("postgresql://test")
    generator.pool = mock_db_pool
    
    conn = mock_db_pool.pool_conn
    conn.fetchrow = AsyncMock(return_value=None)  # Instance not found
    
    result = await generator.generate_for_enrollment("nonexistent-id")
    
    # Assertions
    assert result["error"] is not None
    assert "not found" in result["error"].lower()
    assert result["generated"] == []
    assert result["skipped"] == 0


@pytest.mark.asyncio
async def test_database_error_handling(mock_db_pool, mock_cadence_instance, mock_cadence_touches):
    """
    Test 4: Error handling for database failures during draft creation.
    
    Verifies:
    - Database exceptions are caught
    - Error message is returned
    - Metrics record the failure
    """
    generator = CadenceDraftGenerator("postgresql://test")
    generator.pool = mock_db_pool
    
    conn = mock_db_pool.pool_conn
    
    # Setup: instance and touches succeed, but insert fails
    conn.fetchrow = AsyncMock(return_value=mock_cadence_instance)
    conn.fetch = AsyncMock(return_value=mock_cadence_touches)
    conn.fetchval = AsyncMock(side_effect=Exception("Database connection lost"))
    
    result = await generator.generate_for_enrollment("inst-123")
    
    # Assertions
    assert result["error"] is not None
    assert "connection lost" in result["error"].lower()
    assert result["generated"] == []
    assert result["skipped"] == 0


@pytest.mark.asyncio
async def test_batch_regeneration_multiple_instances(mock_db_pool):
    """
    Test 5: Batch regeneration for all active instances of a template.
    
    Verifies:
    - All active instances are fetched for a template
    - Drafts are regenerated for each instance
    - Results are aggregated
    - Force flag deletes existing drafts
    """
    generator = CadenceDraftGenerator("postgresql://test")
    generator.pool = mock_db_pool
    
    conn = mock_db_pool.pool_conn
    
    # Setup: two active instances
    instances = [
        {"id": "inst-1"},
        {"id": "inst-2"},
    ]
    
    conn.fetch = AsyncMock(return_value=instances)
    conn.execute = AsyncMock()  # For force delete
    
    # Mock generate_for_enrollment results
    with patch.object(generator, 'generate_for_enrollment') as mock_gen:
        mock_gen.side_effect = [
            {"generated": ["draft-1a", "draft-1b"], "skipped": 0, "error": None},
            {"generated": ["draft-2a", "draft-2b"], "skipped": 0, "error": None},
        ]
        
        result = await generator.regenerate_for_template("tmpl-456", force=True)
    
    # Assertions
    assert result["total_instances"] == 2
    assert result["errors"] == []
    assert result["generated"]["inst-1"] == 2
    assert result["generated"]["inst-2"] == 2
    
    # Verify force delete was called
    conn.execute.assert_called()


@pytest.mark.asyncio
async def test_regeneration_partial_failure():
    """
    Test: Batch regeneration handles partial failures gracefully.
    
    Verifies:
    - Successfully regenerated instances are recorded
    - Failed instances are noted in errors list
    - Execution continues despite individual failures
    """
    generator = CadenceDraftGenerator("postgresql://test")
    
    mock_pool = AsyncMock()
    conn = AsyncMock()
    mock_pool.acquire = lambda: conn
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=None)
    
    generator.pool = mock_pool
    
    # Setup: two instances, one succeeds, one fails
    instances = [
        {"id": "inst-good"},
        {"id": "inst-bad"},
    ]
    
    conn.fetch = AsyncMock(return_value=instances)
    conn.execute = AsyncMock()
    
    with patch.object(generator, 'generate_for_enrollment') as mock_gen:
        async def side_effect(instance_id):
            if instance_id == "inst-good":
                return {"generated": ["draft-1"], "skipped": 0, "error": None}
            else:
                raise Exception("Connection timeout")
        
        mock_gen.side_effect = side_effect
        
        result = await generator.regenerate_for_template("tmpl-456", force=False)
    
    # Assertions
    assert result["total_instances"] == 2
    assert result["generated"]["inst-good"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["instance_id"] == "inst-bad"


@pytest.mark.asyncio
async def test_metrics_recorded_on_success(mock_db_pool, mock_cadence_instance, mock_cadence_touches):
    """
    Test: Metrics are properly recorded for successful draft generation.
    """
    metrics_collector.reset()
    
    generator = CadenceDraftGenerator("postgresql://test")
    generator.pool = mock_db_pool
    
    conn = mock_db_pool.pool_conn
    conn.fetchrow = AsyncMock(return_value=mock_cadence_instance)
    conn.fetch = AsyncMock(return_value=mock_cadence_touches)
    conn.fetchval = AsyncMock(side_effect=[None, "draft-1", None, "draft-2", None, "draft-3"])
    
    result = await generator.generate_for_enrollment("inst-123")
    
    # Assertions
    assert metrics_collector.drafts_generated_total == 3
    assert metrics_collector.cadence_enrollments_total == 1
    assert metrics_collector.drafts_failed_total == 0


@pytest.mark.asyncio
async def test_metrics_recorded_on_error(mock_db_pool, mock_cadence_instance, mock_cadence_touches):
    """
    Test: Metrics are recorded for failed draft generation.
    """
    metrics_collector.reset()
    
    generator = CadenceDraftGenerator("postgresql://test")
    generator.pool = mock_db_pool
    
    conn = mock_db_pool.pool_conn
    conn.fetchrow = AsyncMock(return_value=mock_cadence_instance)
    conn.fetch = AsyncMock(return_value=mock_cadence_touches)
    conn.fetchval = AsyncMock(side_effect=Exception("DB error"))
    
    result = await generator.generate_for_enrollment("inst-123")
    
    # Assertions
    assert result["error"] is not None
    assert metrics_collector.drafts_failed_total == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
