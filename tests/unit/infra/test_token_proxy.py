"""Tests for the token counting proxy (S4-02).

Uses actual HTTP requests to verify the proxy works end-to-end.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any
from urllib.request import Request, urlopen

import pytest

from revolver.infra.token_proxy import (
    TokenCountingProxy,
    TokenUsage,
    estimate_cost,
)

pytestmark = [pytest.mark.unit]


# ── Fake LLM backend ─────────────────────────────────────────────────────────


class _FakeLLMHandler(BaseHTTPRequestHandler):
    """Minimal fake LLM server returning OpenAI-compatible responses."""

    # Class-level override for custom response
    custom_response: dict[str, Any] | None = None

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        _body = self.rfile.read(content_length) if content_length > 0 else b""

        if self.custom_response is not None:
            response = self.custom_response
        else:
            response = {
                "id": "chatcmpl-test",
                "choices": [{"message": {"content": "Hello"}}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 20,
                    "total_tokens": 30,
                },
            }

        body = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        body = json.dumps({"status": "ok"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Suppress logging


def _start_fake_llm(
    custom_response: dict[str, Any] | None = None,
) -> tuple[HTTPServer, int]:
    """Start a fake LLM server on a random port. Returns (server, port)."""
    if custom_response is not None:
        # Create a new handler class with the custom response
        handler_cls = type(
            "_CustomHandler",
            (_FakeLLMHandler,),
            {"custom_response": custom_response},
        )
    else:
        handler_cls = _FakeLLMHandler  # type: ignore[assignment]

    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


# ── TokenCountingProxy tests ─────────────────────────────────────────────────


class TestTokenCountingProxy:
    """Tests for TokenCountingProxy."""

    def test_captures_tokens(self) -> None:
        """Proxy captures prompt and completion tokens from mock responses."""
        fake_server, fake_port = _start_fake_llm()
        try:
            proxy = TokenCountingProxy(f"http://127.0.0.1:{fake_port}")
            proxy_url = proxy.start()

            # Send a request through the proxy
            req = Request(
                f"{proxy_url}/v1/chat/completions",
                data=json.dumps({"model": "test"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())

            assert data["usage"]["prompt_tokens"] == 10
            assert data["usage"]["completion_tokens"] == 20

            usage = proxy.stop()
            assert isinstance(usage, TokenUsage)
            assert usage.prompt_tokens == 10
            assert usage.completion_tokens == 20
            assert usage.total_tokens == 30
        finally:
            fake_server.shutdown()

    def test_accumulates_multiple_requests(self) -> None:
        """Proxy accumulates tokens across multiple requests."""
        fake_server, fake_port = _start_fake_llm()
        try:
            proxy = TokenCountingProxy(f"http://127.0.0.1:{fake_port}")
            proxy_url = proxy.start()

            for _ in range(3):
                req = Request(
                    f"{proxy_url}/v1/chat/completions",
                    data=json.dumps({"model": "test"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(req, timeout=5):
                    pass

            usage = proxy.stop()
            assert usage.prompt_tokens == 30  # 10 * 3
            assert usage.completion_tokens == 60  # 20 * 3
        finally:
            fake_server.shutdown()

    def test_handles_missing_usage(self) -> None:
        """Proxy gracefully handles responses without usage field."""
        no_usage_response = {
            "id": "chatcmpl-test",
            "choices": [{"message": {"content": "Hello"}}],
        }
        fake_server, fake_port = _start_fake_llm(custom_response=no_usage_response)
        try:
            proxy = TokenCountingProxy(f"http://127.0.0.1:{fake_port}")
            proxy_url = proxy.start()

            req = Request(
                f"{proxy_url}/v1/chat/completions",
                data=json.dumps({"model": "test"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=5):
                pass

            usage = proxy.stop()
            assert usage.prompt_tokens == 0
            assert usage.completion_tokens == 0
        finally:
            fake_server.shutdown()

    def test_forwards_get_requests(self) -> None:
        """Proxy forwards GET requests (health check, models list)."""
        fake_server, fake_port = _start_fake_llm()
        try:
            proxy = TokenCountingProxy(f"http://127.0.0.1:{fake_port}")
            proxy_url = proxy.start()

            req = Request(f"{proxy_url}/v1/models", method="GET")
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())

            assert data["status"] == "ok"

            usage = proxy.stop()
            assert usage.prompt_tokens == 0  # GET requests have no usage
        finally:
            fake_server.shutdown()

    def test_stop_returns_zero_without_requests(self) -> None:
        """Stopping a proxy with no requests returns zero counts."""
        fake_server, fake_port = _start_fake_llm()
        try:
            proxy = TokenCountingProxy(f"http://127.0.0.1:{fake_port}")
            proxy.start()
            usage = proxy.stop()
            assert usage.prompt_tokens == 0
            assert usage.completion_tokens == 0
            assert usage.total_tokens == 0
        finally:
            fake_server.shutdown()

    def test_proxy_url_format(self) -> None:
        """Proxy URL is a valid HTTP URL on localhost."""
        fake_server, fake_port = _start_fake_llm()
        try:
            proxy = TokenCountingProxy(f"http://127.0.0.1:{fake_port}")
            proxy_url = proxy.start()
            assert proxy_url.startswith("http://127.0.0.1:")
            proxy.stop()
        finally:
            fake_server.shutdown()


# ── estimate_cost tests ───────────────────────────────────────────────────────


class TestEstimateCost:
    """Tests for estimate_cost()."""

    def test_with_pricing(self) -> None:
        """Cost is computed correctly from token counts and pricing."""
        cost = estimate_cost(
            prompt_tokens=1_000_000,
            completion_tokens=500_000,
            input_cost_per_mtok=3.0,
            output_cost_per_mtok=15.0,
        )
        assert cost is not None
        # 1M * 3.0 / 1M + 0.5M * 15.0 / 1M = 3.0 + 7.5 = 10.5
        assert cost == pytest.approx(10.5)

    def test_zero_tokens(self) -> None:
        """Zero tokens yields zero cost."""
        cost = estimate_cost(
            prompt_tokens=0,
            completion_tokens=0,
            input_cost_per_mtok=3.0,
            output_cost_per_mtok=15.0,
        )
        assert cost == pytest.approx(0.0)

    def test_no_pricing(self) -> None:
        """Returns None when pricing is not configured."""
        cost = estimate_cost(
            prompt_tokens=1000,
            completion_tokens=500,
            input_cost_per_mtok=None,
            output_cost_per_mtok=None,
        )
        assert cost is None

    def test_partial_pricing(self) -> None:
        """Returns None when only one pricing is configured."""
        cost = estimate_cost(
            prompt_tokens=1000,
            completion_tokens=500,
            input_cost_per_mtok=3.0,
            output_cost_per_mtok=None,
        )
        assert cost is None

    def test_small_token_counts(self) -> None:
        """Small token counts produce correct fractional costs."""
        cost = estimate_cost(
            prompt_tokens=100,
            completion_tokens=50,
            input_cost_per_mtok=3.0,
            output_cost_per_mtok=15.0,
        )
        assert cost is not None
        # 100 * 3.0 / 1M + 50 * 15.0 / 1M = 0.0003 + 0.00075 = 0.00105
        assert cost == pytest.approx(0.00105)
