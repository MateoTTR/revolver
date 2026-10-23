"""Tests for the token counting proxy (S4-02 + S4b FB-01/03/04).

Uses actual HTTP requests to verify the proxy works end-to-end.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from threading import Thread
from typing import Any, ClassVar
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from revolver.infra.token_proxy import (
    TokenCountingProxy,
    TokenUsage,
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


# ── Fake error LLM backend ──────────────────────────────────────────────────


class _FakeErrorHandler(BaseHTTPRequestHandler):
    """Fake LLM server that returns a configurable HTTP error status."""

    # Class-level overrides
    error_code: int = 400
    error_body: bytes = b'{"error":"bad request"}'
    extra_headers: ClassVar[dict[str, str]] = {}

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            self.rfile.read(content_length)

        self.send_response(self.error_code)
        self.send_header("Content-Type", "application/json")
        for name, value in self.extra_headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(self.error_body)))
        self.end_headers()
        self.wfile.write(self.error_body)

    def do_GET(self) -> None:
        self.send_response(self.error_code)
        self.send_header("Content-Type", "application/json")
        for name, value in self.extra_headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(self.error_body)))
        self.end_headers()
        self.wfile.write(self.error_body)

    def log_message(self, format: str, *args: Any) -> None:
        pass


def _start_fake_error_llm(
    error_code: int = 400,
    error_body: bytes = b'{"error":"bad request"}',
    extra_headers: dict[str, str] | None = None,
) -> tuple[HTTPServer, int]:
    """Start a fake LLM server that always returns an HTTP error."""
    handler_cls = type(
        "_ErrorHandler",
        (_FakeErrorHandler,),
        {
            "error_code": error_code,
            "error_body": error_body,
            "extra_headers": extra_headers or {},
        },
    )
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


# ── FB-01: Forward upstream HTTP status codes ────────────────────────────────


class TestProxyErrorForwarding:
    """Tests for HTTP error forwarding (FB-01)."""

    def test_proxy_forwards_400_status(self) -> None:
        """Proxy forwards 400 status and body from upstream."""
        error_body = b'{"error":"bad request","message":"invalid model"}'
        fake_server, fake_port = _start_fake_error_llm(error_code=400, error_body=error_body)
        try:
            proxy = TokenCountingProxy(f"http://127.0.0.1:{fake_port}")
            proxy_url = proxy.start()

            req = Request(
                f"{proxy_url}/v1/chat/completions",
                data=json.dumps({"model": "test"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(HTTPError) as exc_info:
                urlopen(req, timeout=5)

            assert exc_info.value.code == 400
            body = exc_info.value.read()
            assert b"bad request" in body

            proxy.stop()
        finally:
            fake_server.shutdown()

    def test_proxy_forwards_429_with_body(self) -> None:
        """Proxy forwards 429 status and body from upstream."""
        error_body = b'{"error":"rate limited"}'
        fake_server, fake_port = _start_fake_error_llm(error_code=429, error_body=error_body)
        try:
            proxy = TokenCountingProxy(f"http://127.0.0.1:{fake_port}")
            proxy_url = proxy.start()

            req = Request(
                f"{proxy_url}/v1/chat/completions",
                data=json.dumps({"model": "test"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(HTTPError) as exc_info:
                urlopen(req, timeout=5)

            assert exc_info.value.code == 429
            body = exc_info.value.read()
            assert b"rate limited" in body

            proxy.stop()
        finally:
            fake_server.shutdown()

    def test_proxy_forwards_502_status(self) -> None:
        """Proxy forwards an upstream 502 status and body verbatim (A5 / #317).

        A subscription-backed local OpenAI-compatible shim under sustained load
        can return ``502 Bad Gateway``. Because urllib raises ``HTTPError`` for
        5xx, this exercises the FB-01 forwarding branch — the client must see
        the real 502 + body, not a generic proxy error that masks the cause.
        """
        error_body = b'{"error":"bad gateway","message":"bridge upstream failed"}'
        fake_server, fake_port = _start_fake_error_llm(error_code=502, error_body=error_body)
        try:
            proxy = TokenCountingProxy(f"http://127.0.0.1:{fake_port}")
            proxy_url = proxy.start()

            req = Request(
                f"{proxy_url}/v1/chat/completions",
                data=json.dumps({"model": "test"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(HTTPError) as exc_info:
                urlopen(req, timeout=5)

            assert exc_info.value.code == 502
            body = exc_info.value.read()
            assert b"bad gateway" in body
            assert b"bridge upstream failed" in body

            proxy.stop()
        finally:
            fake_server.shutdown()

    def test_proxy_returns_502_on_connection_error(self) -> None:
        """Proxy returns 502 for non-HTTP errors (connection refused)."""
        # Point at a port that is not listening
        proxy = TokenCountingProxy("http://127.0.0.1:1")
        proxy_url = proxy.start()

        req = Request(
            f"{proxy_url}/v1/chat/completions",
            data=json.dumps({"model": "test"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as exc_info:
            urlopen(req, timeout=5)

        assert exc_info.value.code == 502
        body = json.loads(exc_info.value.read())
        assert "error" in body

        proxy.stop()

    def test_proxy_token_counting_unchanged(self) -> None:
        """Normal 200 responses still count tokens after changes."""
        fake_server, fake_port = _start_fake_llm()
        try:
            proxy = TokenCountingProxy(f"http://127.0.0.1:{fake_port}")
            proxy_url = proxy.start()

            req = Request(
                f"{proxy_url}/v1/chat/completions",
                data=json.dumps({"model": "test"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())

            assert data["usage"]["prompt_tokens"] == 10
            usage = proxy.stop()
            assert usage.prompt_tokens == 10
            assert usage.completion_tokens == 20
        finally:
            fake_server.shutdown()

    def test_proxy_forwards_500_on_get(self) -> None:
        """Proxy forwards 500 error on GET request."""
        error_body = b'{"error":"internal server error"}'
        fake_server, fake_port = _start_fake_error_llm(error_code=500, error_body=error_body)
        try:
            proxy = TokenCountingProxy(f"http://127.0.0.1:{fake_port}")
            proxy_url = proxy.start()

            req = Request(f"{proxy_url}/v1/models", method="GET")
            with pytest.raises(HTTPError) as exc_info:
                urlopen(req, timeout=5)

            assert exc_info.value.code == 500

            proxy.stop()
        finally:
            fake_server.shutdown()


# ── FB-03: Forward Retry-After header ────────────────────────────────────────


class TestProxyRetryAfterForwarding:
    """Tests for Retry-After header forwarding (FB-03)."""

    def test_proxy_forwards_retry_after_header(self) -> None:
        """Proxy forwards Retry-After header from 429 responses."""
        fake_server, fake_port = _start_fake_error_llm(
            error_code=429,
            error_body=b'{"error":"rate limited"}',
            extra_headers={"Retry-After": "30"},
        )
        try:
            proxy = TokenCountingProxy(f"http://127.0.0.1:{fake_port}")
            proxy_url = proxy.start()

            req = Request(
                f"{proxy_url}/v1/chat/completions",
                data=json.dumps({"model": "test"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(HTTPError) as exc_info:
                urlopen(req, timeout=5)

            assert exc_info.value.code == 429
            retry_after = exc_info.value.headers.get("Retry-After")
            assert retry_after == "30"

            proxy.stop()
        finally:
            fake_server.shutdown()


# ── FB-04: Optional backoff on 429 ──────────────────────────────────────────


class TestProxyBackoffOn429:
    """Tests for optional proxy-level backoff on 429 (FB-04)."""

    def test_proxy_backoff_waits_on_429(self) -> None:
        """With backoff_on_429=True, proxy sleeps for Retry-After duration."""
        fake_server, fake_port = _start_fake_error_llm(
            error_code=429,
            error_body=b'{"error":"rate limited"}',
            extra_headers={"Retry-After": "2"},
        )
        try:
            proxy = TokenCountingProxy(f"http://127.0.0.1:{fake_port}", backoff_on_429=True)
            proxy_url = proxy.start()

            req = Request(
                f"{proxy_url}/v1/chat/completions",
                data=json.dumps({"model": "test"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with patch("revolver.infra.token_proxy.time.sleep") as mock_sleep:
                with pytest.raises(HTTPError) as exc_info:
                    urlopen(req, timeout=10)

                assert exc_info.value.code == 429
                mock_sleep.assert_called_once_with(2.0)

            proxy.stop()
        finally:
            fake_server.shutdown()

    def test_proxy_no_backoff_by_default(self) -> None:
        """Default backoff_on_429=False means no sleep on 429."""
        fake_server, fake_port = _start_fake_error_llm(
            error_code=429,
            error_body=b'{"error":"rate limited"}',
            extra_headers={"Retry-After": "2"},
        )
        try:
            proxy = TokenCountingProxy(f"http://127.0.0.1:{fake_port}")
            proxy_url = proxy.start()

            req = Request(
                f"{proxy_url}/v1/chat/completions",
                data=json.dumps({"model": "test"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with patch("revolver.infra.token_proxy.time.sleep") as mock_sleep:
                with pytest.raises(HTTPError):
                    urlopen(req, timeout=5)

                mock_sleep.assert_not_called()

            proxy.stop()
        finally:
            fake_server.shutdown()

    def test_proxy_backoff_capped_at_60s(self) -> None:
        """Backoff is capped at 60 seconds even if Retry-After is larger."""
        fake_server, fake_port = _start_fake_error_llm(
            error_code=429,
            error_body=b'{"error":"rate limited"}',
            extra_headers={"Retry-After": "300"},
        )
        try:
            proxy = TokenCountingProxy(f"http://127.0.0.1:{fake_port}", backoff_on_429=True)
            proxy_url = proxy.start()

            req = Request(
                f"{proxy_url}/v1/chat/completions",
                data=json.dumps({"model": "test"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with patch("revolver.infra.token_proxy.time.sleep") as mock_sleep:
                with pytest.raises(HTTPError):
                    urlopen(req, timeout=10)

                mock_sleep.assert_called_once_with(60.0)

            proxy.stop()
        finally:
            fake_server.shutdown()
