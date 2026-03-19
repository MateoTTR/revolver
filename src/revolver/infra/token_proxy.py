"""Transparent HTTP proxy for token usage tracking.

Intercepts OpenAI-compatible API responses and extracts
``usage.prompt_tokens`` / ``usage.completion_tokens`` fields
for accumulation. Uses only stdlib (``http.server``, ``threading``,
``urllib.request``) per project constraints.

Includes upstream error forwarding (FB-01) and optional 429 backoff (FB-04).

Traceable to: DES-005 §4.5 (DD-14), FR-RUN-028/029/030.
"""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import socket
import sys
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Hop-by-hop headers that must not be forwarded by proxies (RFC 2616 §13.5.1).
_HOP_BY_HOP = frozenset(
    {
        "transfer-encoding",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "upgrade",
    }
)

# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class TokenUsage:
    """Accumulated token counts from proxy interception.

    Attributes:
        prompt_tokens: Total prompt tokens observed.
        completion_tokens: Total completion tokens observed.
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Total tokens (prompt + completion)."""
        return self.prompt_tokens + self.completion_tokens


# ── Cost estimation utility ───────────────────────────────────────────────────


def estimate_cost(
    prompt_tokens: int,
    completion_tokens: int,
    input_cost_per_mtok: float | None = None,
    output_cost_per_mtok: float | None = None,
) -> float | None:
    """Estimate cost in USD from token counts and per-million-token pricing.

    Args:
        prompt_tokens: Number of prompt/input tokens.
        completion_tokens: Number of completion/output tokens.
        input_cost_per_mtok: Cost per million input tokens (USD).
        output_cost_per_mtok: Cost per million output tokens (USD).

    Returns:
        Estimated cost in USD, or ``None`` if pricing is not configured.
    """
    if input_cost_per_mtok is None or output_cost_per_mtok is None:
        return None
    return (
        prompt_tokens * input_cost_per_mtok + completion_tokens * output_cost_per_mtok
    ) / 1_000_000


# ── Token counting proxy ─────────────────────────────────────────────────────


class TokenCountingProxy:
    """Transparent HTTP proxy that counts tokens from OpenAI-compatible responses.

    Forwards all requests to the real LLM endpoint and intercepts response
    bodies to extract token usage from the ``usage`` field.

    Note: when ``backoff_on_429=True``, the proxy blocks the single server
    thread during sleep, so all concurrent requests are queued until the
    backoff completes.

    Args:
        target_url: The real LLM endpoint URL (e.g., ``http://localhost:11434/v1``).
        backoff_on_429: When ``True``, the proxy sleeps for the duration
            indicated by the upstream ``Retry-After`` header on 429 responses
            before forwarding the response to the client (capped at 60 s).
    """

    def __init__(self, target_url: str, *, backoff_on_429: bool = False) -> None:
        self.target_url = target_url.rstrip("/")
        self.backoff_on_429 = backoff_on_429
        self._lock = threading.Lock()
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        """Start the proxy server on a random available port.

        Returns:
            Local proxy URL (e.g., ``http://127.0.0.1:54321``).
        """
        port = _find_free_port()
        proxy = self

        class _Handler(BaseHTTPRequestHandler):
            """HTTP request handler that proxies to the target and counts tokens."""

            def do_POST(self) -> None:
                """Handle POST requests (chat completions, etc.)."""
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length) if content_length > 0 else b""

                target = proxy.target_url + self.path
                req = Request(
                    target,
                    data=body,
                    method="POST",
                )
                # Forward relevant headers
                for header_name in ("Content-Type", "Authorization", "Accept"):
                    value = self.headers.get(header_name)
                    if value:
                        req.add_header(header_name, value)

                try:
                    with urlopen(req, timeout=300) as resp:
                        resp_body = resp.read()
                        status = resp.status
                        resp_headers: list[tuple[str, str]] = list(resp.getheaders())
                except HTTPError as exc:
                    # Upstream returned an HTTP error — forward status,
                    # body, and headers so the client sees the real error
                    # (e.g. 400, 429, 500) instead of a generic 502.
                    resp_body = exc.read()
                    status = exc.code
                    resp_headers = [
                        (k, v) for k, v in exc.headers.items() if k.lower() not in _HOP_BY_HOP
                    ]

                    # Still extract token usage if present (some providers
                    # include billing info even in error responses).
                    proxy._extract_usage(resp_body)

                    # Optional backoff on 429 (FB-04)
                    if proxy.backoff_on_429 and status == 429:
                        retry_after = exc.headers.get("Retry-After")
                        if retry_after is not None:
                            try:
                                wait = min(float(retry_after), 60.0)
                                sys.stderr.write(
                                    f"[proxy] 429 received, backing off {wait}s (Retry-After)\n"
                                )
                                time.sleep(wait)
                            except ValueError:
                                # Only numeric Retry-After values supported; date format ignored
                                pass

                    self.send_response(status)
                    for name, value in resp_headers:
                        self.send_header(name, value)
                    self.send_header("Content-Length", str(len(resp_body)))
                    self.end_headers()
                    self.wfile.write(resp_body)
                    return
                except URLError as exc:
                    # Non-HTTP errors (DNS failure, connection refused, etc.)
                    error_msg = json.dumps({"error": str(exc)}).encode()
                    self.send_response(502)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(error_msg)))
                    self.end_headers()
                    self.wfile.write(error_msg)
                    return

                # Extract token usage from response
                proxy._extract_usage(resp_body)

                # Forward response to client
                self.send_response(status)
                for name, value in resp_headers:
                    # Skip hop-by-hop headers
                    if name.lower() in _HOP_BY_HOP:
                        continue
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)

            def do_GET(self) -> None:
                """Handle GET requests (health checks, models list, etc.)."""
                target = proxy.target_url + self.path
                req = Request(target, method="GET")
                for header_name in ("Accept", "Authorization"):
                    value = self.headers.get(header_name)
                    if value:
                        req.add_header(header_name, value)

                try:
                    with urlopen(req, timeout=30) as resp:
                        resp_body = resp.read()
                        status = resp.status
                        resp_headers = list(resp.getheaders())
                except HTTPError as exc:
                    # Forward upstream HTTP error status, body, and headers.
                    resp_body = exc.read()
                    status = exc.code
                    resp_headers = [
                        (k, v) for k, v in exc.headers.items() if k.lower() not in _HOP_BY_HOP
                    ]

                    self.send_response(status)
                    for name, value in resp_headers:
                        self.send_header(name, value)
                    self.send_header("Content-Length", str(len(resp_body)))
                    self.end_headers()
                    self.wfile.write(resp_body)
                    return
                except URLError as exc:
                    # Non-HTTP errors (DNS failure, connection refused, etc.)
                    error_msg = json.dumps({"error": str(exc)}).encode()
                    self.send_response(502)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(error_msg)))
                    self.end_headers()
                    self.wfile.write(error_msg)
                    return

                self.send_response(status)
                for name, value in resp_headers:
                    if name.lower() in _HOP_BY_HOP:
                        continue
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(resp_body)))
                self.end_headers()
                self.wfile.write(resp_body)

            def log_message(self, format: str, *args: Any) -> None:
                """Suppress default request logging."""

        self._server = HTTPServer(("127.0.0.1", port), _Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )
        self._thread.start()
        return f"http://127.0.0.1:{port}"

    def stop(self) -> TokenUsage:
        """Stop the proxy server and return accumulated token counts.

        Returns:
            TokenUsage with accumulated prompt and completion token counts.
        """
        if self._server is not None:
            self._server.shutdown()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

        with self._lock:
            return TokenUsage(
                prompt_tokens=self._prompt_tokens,
                completion_tokens=self._completion_tokens,
            )

    def _extract_usage(self, response_body: bytes) -> None:
        """Parse response body and accumulate token counts if present.

        Handles OpenAI-compatible responses with a ``usage`` field:
        ``{"usage": {"prompt_tokens": N, "completion_tokens": M}}``.

        Silently ignores responses that don't contain usage data.
        """
        try:
            data = json.loads(response_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        if not isinstance(data, dict):
            return

        usage = data.get("usage")
        if not isinstance(usage, dict):
            return

        prompt = usage.get("prompt_tokens", 0)
        completion = usage.get("completion_tokens", 0)

        if isinstance(prompt, int) and isinstance(completion, int):
            with self._lock:
                self._prompt_tokens += prompt
                self._completion_tokens += completion


# ── Helpers ───────────────────────────────────────────────────────────────────


def _find_free_port() -> int:
    """Find a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])
