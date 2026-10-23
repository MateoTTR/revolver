#!/usr/bin/env python3
"""Spike #320 repro — ShinkaEvolve mid-run stall against a hung LLM endpoint.

Reproduces the "qwen15 mid-run deadlock" (backlog #320) model-independently:
a fake OpenAI-compatible endpoint accepts the TCP connection and the HTTP
request for POST /v1/chat/completions but NEVER sends a single response
byte. A tiny ShinkaEvolveRunner run (constructed exactly the way Revolver's
``ShinkaBackend._run_engine`` does — including NOT passing
``max_proposal_jobs`` to the constructor) is pointed at it and observed.

Expected observations (see docs/analysis/spike-320-qwen15-deadlock.md):

- ``stall`` mode (default, real constants): the run wedges on the first
  proposal. The child process sits inside
  ``shinka/llm/providers/local_openai.py::query_local_openai_async`` →
  ``openai``/``httpx`` socket read, bounded only by the hard-coded 1200 s
  client timeout (shinka/llm/constants.py::TIMEOUT). No "STUCK SYSTEM
  DETECTED" watchdog line ever appears: the watchdog requires
  ``running_proposal_jobs == 0`` and the wedged proposal keeps it at >= 1.
  (Observed 2026-07-05: 1 stalled connection held open for 150 s, zero
  watchdog lines, zero progress, child alive. With this tiny run the
  adaptive proposal pipeline starts a single proposal, so the dropped
  ``max_proposal_jobs`` pin — see the analysis doc §4 — does not multiply
  connections here; it is established from the code path instead.)

- ``fast`` mode (patches ``shinka.llm.client.TIMEOUT`` to 8 s BEFORE any
  client is built — the module global is read at call time, so this is the
  same code path with a shrunk L1 timeout): within ~3 minutes the full
  retry cascade becomes visible — openai SDK internal retries (2), then the
  ``backoff`` decorator retries ("Local OpenAI - Retry N ..."), then
  ``llm.py`` MAX_RETRIES, then ``max_patch_attempts`` — with a NEW request
  hitting the fake endpoint for every retry (retry amplification), and
  still zero watchdog lines and zero generation progress.
  (Observed 2026-07-05: 23 stalled connections in ~4 minutes for ONE
  logical ``llm.query`` call — 7 backoff-level retries, each preceded by
  the openai SDK's 2 internal retries.)

Usage (needs an env with shinka 0.0.7 installed, e.g. the demo environment):

    conda activate <shinka-env>
    python docs/analysis/spike-320-repro.py                 # stall mode, ~3 min
    python docs/analysis/spike-320-repro.py --mode fast     # cascade, ~4 min
    python docs/analysis/spike-320-repro.py --watch-seconds 120

The driver kills the whole child process group at the end of the
observation window — the point of the spike is to observe the wedge, not to
wait it out (fully-stalled worst case is ~60 h per proposal, see analysis).
"""

from __future__ import annotations

import argparse
import contextlib
import http.server
import json
import os
from pathlib import Path
import re
import signal
import socketserver
import subprocess
import sys
import tempfile
import threading
import time

# ── Fake stalling OpenAI-compatible endpoint ─────────────────────────────────

CONNECTION_LOG: list[str] = []
_CONNECTION_LOCK = threading.Lock()


class _StallingHandler(http.server.BaseHTTPRequestHandler):
    """Accepts the request, logs it, never sends a response byte."""

    protocol_version = "HTTP/1.1"

    def _stall(self) -> None:
        with _CONNECTION_LOCK:
            CONNECTION_LOG.append(
                f"{time.strftime('%H:%M:%S')} {self.command} {self.path}"
            )
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            self.rfile.read(length)  # drain the request body, then hang
        # Hold the socket open forever (until the server is torn down).
        # No status line, no headers, no body: the client's only way out
        # is its own read timeout.
        while not getattr(self.server, "_shutting_down", False):
            time.sleep(0.5)

    do_GET = _stall
    do_POST = _stall

    def log_message(self, *_args) -> None:  # silence default request logging
        pass


class _ThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_stall_server() -> tuple[_ThreadingServer, int]:
    server = _ThreadingServer(("127.0.0.1", 0), _StallingHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


# ── Child payload: a tiny ShinkaEvolveRunner run against the fake endpoint ───

INIT_PROGRAM = '''\
"""Trivial program to evolve (spike #320 repro)."""


def solve(x: float) -> float:
    return x * 2.0
'''

# Shinka CLI evaluator contract (mirrors the shape of Revolver's generated
# wrapper standalone fallback): write metrics.json + correct.json fast.
EVALUATE_SCRIPT = '''\
import argparse
import json
import os

parser = argparse.ArgumentParser()
parser.add_argument("--program_path", required=True)
parser.add_argument("--results_dir", required=True)
args = parser.parse_args()

os.makedirs(args.results_dir, exist_ok=True)
with open(os.path.join(args.results_dir, "correct.json"), "w") as f:
    json.dump({"correct": True, "error": None}, f)
with open(os.path.join(args.results_dir, "metrics.json"), "w") as f:
    json.dump({"combined_score": 0.5}, f)
'''


def run_child(port: int, workdir: Path, mode: str, generations: int,
              max_patch_attempts: int) -> None:
    """Construct and run ShinkaEvolveRunner the way Revolver's _run_engine does."""
    import faulthandler

    # SIGUSR1 → dump all thread stacks to stderr (driver captures the file).
    faulthandler.register(signal.SIGUSR1, all_threads=True)

    # Mirrors ShinkaBackend launch(): key-less local endpoint placeholder.
    os.environ.setdefault("OLLAMA_API_KEY", "ollama")
    os.environ["PYTHONUNBUFFERED"] = "1"

    if mode == "fast":
        # shinka/llm/client.py reads the module-global TIMEOUT at call time
        # (get_client_llm / get_async_client_llm), so patching it BEFORE the
        # first query shrinks the per-HTTP-attempt timeout without touching
        # any other layer. The backoff decorator constants (max_tries=20,
        # max_time=6000 s) are baked at import and stay at their real values.
        import shinka.llm.client as shinka_client

        shinka_client.TIMEOUT = 8

    from shinka.core import EvolutionConfig, ShinkaEvolveRunner
    from shinka.database import DatabaseConfig
    from shinka.launch import LocalJobConfig

    results_dir = workdir / "shinka-output"
    model = f"local/stalled-qwen15@http://127.0.0.1:{port}/v1?api_key_env=OLLAMA_API_KEY"

    evo = EvolutionConfig(
        task_sys_msg="Improve the function. (spike #320 repro)",
        num_generations=generations,
        max_patch_attempts=max_patch_attempts,
        patch_types=["diff", "full"],
        patch_type_probs=[0.6, 0.4],
        language="python",
        job_type="local",
        llm_models=[model],
        llm_dynamic_selection="fixed",  # Revolver's default projection
        llm_dynamic_selection_kwargs={},
        llm_kwargs={"temperatures": [0.7], "max_tokens": 512},
        embedding_model=None,  # mirrors Revolver build_config
        results_dir=str(results_dir),
    )
    job = LocalJobConfig(conda_env=None)
    db = DatabaseConfig(num_islands=1, archive_size=4)

    # NOTE: max_proposal_jobs is deliberately NOT passed — Revolver's
    # _run_engine (shinka.py) does not pass it either, so the runner falls
    # back to its own default (6, scaled by CPU/memory). This is the
    # dropped-pin bug documented in the analysis: build_config writes
    # job_config.max_proposal_jobs=1 but _dataclass_kwargs drops it (not a
    # LocalJobConfig field) and the constructor kwarg is never wired.
    runner = ShinkaEvolveRunner(
        evo_config=evo,
        job_config=job,
        db_config=db,
        init_program_str=INIT_PROGRAM,
        evaluate_str=EVALUATE_SCRIPT,
        verbose=True,
    )
    runner.run()


# ── Driver: observe the wedge, dump stacks, collect evidence, kill ───────────

def _tail(path: Path, lines: int = 15) -> str:
    if not path.exists():
        return "<missing>"
    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


def drive(args: argparse.Namespace) -> int:
    workdir = Path(args.workdir or tempfile.mkdtemp(prefix="spike320-"))
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"[driver] workdir: {workdir}")

    server, port = start_stall_server()
    print(f"[driver] stalling fake endpoint on 127.0.0.1:{port}")

    child_out = workdir / "child_stdout.log"
    child_err = workdir / "child_stderr.log"
    cmd = [
        sys.executable, os.path.abspath(__file__),
        "--child", "--port", str(port), "--workdir", str(workdir),
        "--mode", args.mode, "--generations", str(args.generations),
        "--max-patch-attempts", str(args.max_patch_attempts),
    ]
    with open(child_out, "w") as out, open(child_err, "w") as err:
        child = subprocess.Popen(
            cmd, stdout=out, stderr=err, start_new_session=True
        )
    print(f"[driver] child runner pid={child.pid} (new session/pgid)")

    evolution_log = workdir / "shinka-output" / "evolution_run.log"
    t0 = time.time()
    wedge_seen_at: float | None = None
    try:
        while time.time() - t0 < args.watch_seconds:
            time.sleep(5)
            alive = child.poll() is None
            with _CONNECTION_LOCK:
                n_conn = len(CONNECTION_LOG)
            if not alive:
                print(f"[driver] child EXITED early rc={child.returncode} "
                      f"after {time.time() - t0:.0f}s — no wedge (see logs)")
                break
            if n_conn and wedge_seen_at is None:
                wedge_seen_at = time.time()
                print(f"[driver] first LLM request received and stalled at "
                      f"t+{wedge_seen_at - t0:.0f}s")
            print(f"[driver] t+{time.time() - t0:.0f}s alive={alive} "
                  f"stalled_connections={n_conn}")

        evidence: dict[str, object] = {}
        if child.poll() is None:
            # Dump all thread stacks of the wedged child. NOTE: faulthandler
            # shows OS-thread frames only — a *parked coroutine* (the wedged
            # `await llm.query(...)`) is NOT on any thread stack, so these
            # frame greps are EXPECTED to be false during the wedge (the main
            # thread shows the idle asyncio selector instead). The await
            # point is established by the engine log frozen at "==> QUERYING"
            # plus the stalled connection(s); these keys only record whether
            # the dump happened to catch an LLM/httpx frame mid-execution.
            os.kill(child.pid, signal.SIGUSR1)
            time.sleep(3)
            stack_dump = child_err.read_text(encoding="utf-8", errors="replace")
            evidence["stack_dump_note"] = (
                "faulthandler sees OS threads only; a parked coroutine "
                "leaves the frame greps below false — see driver comment"
            )
            evidence["stack_dump_caught_llm_frame"] = bool(
                re.search(r"query_local_openai_async|shinka/llm", stack_dump)
            )
            evidence["stack_dump_caught_httpx_frame"] = bool(
                re.search(r"httpx|httpcore|anyio", stack_dump)
            )

        log_text = (
            evolution_log.read_text(encoding="utf-8", errors="replace")
            if evolution_log.exists() else ""
        )
        with _CONNECTION_LOCK:
            evidence["stalled_connections"] = len(CONNECTION_LOG)
            evidence["connection_log"] = list(CONNECTION_LOG)
        evidence["stuck_watchdog_lines"] = log_text.count("STUCK SYSTEM DETECTED")
        evidence["backoff_retry_lines"] = len(
            re.findall(r"Local OpenAI - Retry", log_text)
        )
        evidence["llm_layer_retry_lines"] = len(
            re.findall(r"/3 Error in query", log_text)
        )
        evidence["generations_completed"] = len(
            re.findall(r"Gen(?:eration)? .*complete", log_text, re.IGNORECASE)
        )
        evidence["child_alive_at_end"] = child.poll() is None

        print("\n[driver] ===== EVIDENCE =====")
        print(json.dumps(evidence, indent=2))
        (workdir / "evidence.json").write_text(json.dumps(evidence, indent=2))

        print("\n[driver] last evolution_run.log lines:")
        print(_tail(evolution_log))
        print("\n[driver] last child_stderr lines (stack dump if wedged):")
        print(_tail(child_err, 40))

        wedged = (
            evidence["child_alive_at_end"]
            and evidence["stalled_connections"] >= 1  # type: ignore[operator]
            and evidence["stuck_watchdog_lines"] == 0
        )
        print(f"\n[driver] VERDICT: {'WEDGED (repro OK)' if wedged else 'no wedge'}")
        return 0 if wedged else 1
    finally:
        server._shutting_down = True  # type: ignore[attr-defined]
        server.shutdown()
        if child.poll() is None:
            print(f"[driver] killing child process group {child.pid}")
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(child.pid), signal.SIGKILL)
            # Never let the cleanup wait mask the driver's return code.
            with contextlib.suppress(subprocess.TimeoutExpired):
                child.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=("stall", "fast"), default="stall")
    parser.add_argument("--watch-seconds", type=int, default=180)
    parser.add_argument("--generations", type=int, default=2)
    parser.add_argument("--max-patch-attempts", type=int, default=2)
    parser.add_argument("--workdir", default=None)
    args = parser.parse_args()

    if args.child:
        run_child(args.port, Path(args.workdir), args.mode,
                  args.generations, args.max_patch_attempts)
        return 0
    return drive(args)


if __name__ == "__main__":
    sys.exit(main())
