"""Fake OpenAI-compatible LLM server for L3 E2E tests.

Implements the lightweight fake server described in
``docs/validation/val-e2e-tests.md`` section 2.2: a stdlib-only HTTP
server started on a random port that replaces a real LLM in E2E
scenarios. It serves:

- ``POST /v1/chat/completions`` — OpenAI-compatible chat completion with
  deterministic content and ``usage.prompt_tokens`` /
  ``usage.completion_tokens`` (plain chat completions only — no
  structured output, matching the local OpenAI-compatible path of the
  evolution engines);
- ``GET /`` — 200 OK (Ollama health check);
- ``GET /api/version`` — Ollama-style version JSON;
- ``POST /api/show`` — Ollama-style model info JSON.

The Ollama-native endpoints let tests register the fake server as a
*local* LLM through the real ``revolver llm add --source local`` path
without a running Ollama instance.

Responses are produced by the ``response_content`` attribute: either a
static string or a callable receiving the parsed request payload and
returning the assistant message content. Tests mutate it to script the
"LLM" behavior per scenario.
"""

from __future__ import annotations

from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from typing import Any

# Default deterministic usage numbers (val-e2e-tests.md section 2.3).
DEFAULT_PROMPT_TOKENS = 150
DEFAULT_COMPLETION_TOKENS = 50

ResponseContent = str | Callable[[dict[str, Any]], str]


class FakeLLMServer:
    """Deterministic fake LLM server on a random localhost port.

    Usage::

        server = FakeLLMServer(response_content="hello")
        server.start()
        try:
            ...  # point clients at server.openai_base_url
        finally:
            server.stop()

    Attributes:
        response_content: Static string or ``callable(payload) -> str``
            producing the assistant message content. Mutable at runtime.
        latency_s: Artificial latency per chat request (seconds).
        chat_requests: Captured ``/v1/chat/completions`` payloads, in
            arrival order.
    """

    def __init__(
        self,
        response_content: ResponseContent = "ok",
        *,
        latency_s: float = 0.0,
        version: str = "0.0.0-fake",
    ) -> None:
        self.response_content: ResponseContent = response_content
        self.latency_s = latency_s
        self.version = version
        self.chat_requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> str:
        """Start the server on a random port and return its root URL.

        Raises:
            RuntimeError: When the server is already running (a second
                start would leak the first server thread).
        """
        if self._server is not None:
            raise RuntimeError("FakeLLMServer is already started — call stop() first.")
        fake = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass  # keep test output clean

            def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                if self.path == "/":
                    # Ollama health check (GET / -> 200)
                    body = b"Ollama is running"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/api/version":
                    self._send_json({"version": fake.version})
                else:
                    self._send_json({"error": "not found"}, status=404)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    payload = {}

                if self.path.endswith("/chat/completions"):
                    self._send_json(fake._chat_completion(payload))
                elif self.path == "/api/show":
                    # Ollama model info (enough for OllamaClient.show_model)
                    self._send_json(
                        {
                            "details": {
                                "family": "fake",
                                "parameter_size": "0.5B",
                                "quantization_level": "Q4_0",
                            },
                            "digest": "sha256:fake-digest",
                            "model_info": {},
                        }
                    )
                else:
                    self._send_json({"error": "not found"}, status=404)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.root_url

    def stop(self) -> None:
        """Shut the server down and join its thread."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    # ── Introspection ────────────────────────────────────────────────────────

    @property
    def port(self) -> int:
        """The bound port (server must be started)."""
        assert self._server is not None, "server not started"
        return int(self._server.server_address[1])

    @property
    def root_url(self) -> str:
        """Root URL, e.g. ``http://127.0.0.1:43210``."""
        return f"http://127.0.0.1:{self.port}"

    @property
    def openai_base_url(self) -> str:
        """OpenAI-compatible base URL, e.g. ``http://127.0.0.1:43210/v1``."""
        return f"{self.root_url}/v1"

    @property
    def chat_request_count(self) -> int:
        """Number of ``/v1/chat/completions`` requests served so far."""
        with self._lock:
            return len(self.chat_requests)

    # ── Response building ────────────────────────────────────────────────────

    def _chat_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Build a deterministic OpenAI chat completion for *payload*."""
        if self.latency_s > 0:
            time.sleep(self.latency_s)
        with self._lock:
            self.chat_requests.append(payload)
            request_index = len(self.chat_requests)
        content = self.response_content
        if callable(content):
            content = content(payload)
        return {
            "id": f"chatcmpl-fake-{request_index}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": payload.get("model", "fake-model"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": DEFAULT_PROMPT_TOKENS,
                "completion_tokens": DEFAULT_COMPLETION_TOKENS,
                "total_tokens": DEFAULT_PROMPT_TOKENS + DEFAULT_COMPLETION_TOKENS,
            },
        }


__all__ = [
    "DEFAULT_COMPLETION_TOKENS",
    "DEFAULT_PROMPT_TOKENS",
    "FakeLLMServer",
]
