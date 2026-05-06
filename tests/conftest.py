"""Pytest fixtures for a8_agent tests."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

import pytest


@pytest.fixture
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_db_pool():
    """Mock asyncpg connection pool."""
    from contextlib import asynccontextmanager
    
    pool = MagicMock()
    conn = AsyncMock()
    
    @asynccontextmanager
    async def mock_acquire():
        yield conn
    
    pool.acquire = mock_acquire
    pool.pool_conn = conn  # For test access
    return pool


@pytest.fixture
def mock_cadence_instance():
    """Sample cadence instance data."""
    return {
        "id": "inst-123",
        "cadence_template_id": "tmpl-456",
        "contact_id": "contact-789",
        "name": "Onboarding Series",
        "status": "active",
    }


@pytest.fixture
def mock_cadence_touches():
    """Sample cadence touch templates."""
    return [
        {
            "id": "touch-1",
            "sequence_number": 1,
            "channel": "email",
            "hook": "Welcome to our platform",
            "expected_outcome": "Read email",
            "guidance": "Introduce the platform features",
            "cta": "Click to get started",
            "tone_guidance": "Friendly, welcoming",
            "suggested_length_words": 150,
        },
        {
            "id": "touch-2",
            "sequence_number": 2,
            "channel": "email",
            "hook": "Your first step",
            "expected_outcome": "Click link",
            "guidance": "Guide them to create account",
            "cta": "Create your account",
            "tone_guidance": "Helpful, encouraging",
            "suggested_length_words": 200,
        },
        {
            "id": "touch-3",
            "sequence_number": 3,
            "channel": "sms",
            "hook": "Quick checkin",
            "expected_outcome": "Reply",
            "guidance": "Check in on progress",
            "cta": "Reply with YES",
            "tone_guidance": "Casual, conversational",
            "suggested_length_words": 50,
        },
    ]


@pytest.fixture
def crm_api_mock():
    """Mock CRM API for testing."""
    mock = AsyncMock()
    
    async def mock_write_draft(draft_id: str, data: dict) -> bool:
        """Mock draft write."""
        return True
    
    async def mock_read_contact(contact_id: str) -> dict:
        """Mock contact read."""
        return {
            "id": contact_id,
            "name": "Test Contact",
            "email": "test@example.com",
        }
    
    mock.write_draft = mock_write_draft
    mock.read_contact = mock_read_contact
    
    return mock
