"""Shared fixtures for L3 E2E tests (val-e2e-tests.md section 2.2).

Provides the ``fake_llm_server`` fixture: a started
:class:`~tests.fixtures.fake_llm_server.FakeLLMServer` on a random port,
shut down on teardown. Tests script the "LLM" by assigning
``fake_llm_server.response_content`` (static string or
``callable(payload) -> str``).
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from tests.fixtures.fake_llm_server import FakeLLMServer


@pytest.fixture()
def fake_llm_server() -> Generator[FakeLLMServer, None, None]:
    """Start a fake OpenAI-compatible LLM server on a random port."""
    server = FakeLLMServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()
