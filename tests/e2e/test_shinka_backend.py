"""L3 E2E Scenario 3 — ShinkaEvolve backend happy path (val-e2e-tests.md §3.3).

Mirrors the Scenario 1 workflow on the ShinkaEvolve backend
(``revolver run --backend shinka``) with the fake LLM server standing in
for a real model: project init → llm add (fake server registered as a
local LLM) → problem version → dataset registration → run → solution →
eval. Asserts the post-engine boundary — ``programs/rank-1.py`` exists
and is NOT the initial program, the run manifest carries
``backend: shinka``, the run record has ``backend='shinka'`` — and that
the engine-neutral downstream (``solution list``, ``eval``) works
identically on the produced artifacts.

The fake server serves plain chat completions only (Shinka's local
OpenAI-compatible path uses no structured output) and always answers
with a deterministic full rewrite, so the run uses ``--rewrite-mode``
(``patch_types=["full"]``) to keep patch application deterministic.

Requires the ``revolver[shinka]`` extra: the module auto-skips when
shinka is not installed (no dedicated marker — FR-RUN-047/048, NFR-061,
ADR-007 D6).

Traceable to: val-e2e-tests.md Scenario 3, sprint-014 S14-16,
FR-RUN-047/048, NFR-024, NFR-061, FR-SET-002.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sqlite3

import pytest

pytest.importorskip("shinka.database", reason="shinka-evolve not installed (optional extra)")

from typer.testing import CliRunner
import yaml

from revolver.cli import app
from revolver.infra.ollama import OllamaClient
from tests.fixtures.fake_llm_server import FakeLLMServer

pytestmark = [pytest.mark.e2e, pytest.mark.slow]

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _get_all_output(result: object) -> str:
    """Combine stdout and stderr from a CliRunner result."""
    parts: list[str] = []
    for attr in ("stdout", "stderr", "output"):
        val = getattr(result, attr, None)
        if val:
            parts.append(val)
    return _strip_ansi("".join(parts))


def _parse_json_output(result: object) -> object:
    """Extract and parse the first JSON object/array from CLI output."""
    output = getattr(result, "output", "") or ""
    for i, ch in enumerate(output):
        if ch in ("{", "["):
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(output, i)
            return obj
    msg = f"No JSON found in output: {output[:200]}"
    raise ValueError(msg)


# ── Problem definition (tiny, deterministic, dependency-free) ────────────────

# Weak baseline: always returns 0 (never matches the expected sum), so a
# successful evolution step is observable as a strictly better score and
# the rank-1 program must differ from the initial program.
_INITIAL_PROGRAM = '''\
"""Initial program for E2E Scenario 3 — deliberately weak baseline."""


def solve(data):
    """Return an aggregate of *data* (the evaluator checks the sum)."""
    # EVOLVE-BLOCK-START
    result = 0
    # EVOLVE-BLOCK-END
    return result
'''

# Deterministic "evolution": the fake LLM always proposes the correct
# sum implementation. The marker comment lets assertions prove the
# rank-1 program came from the fake LLM, not from the baseline.
_EVOLVED_BLOCK_MARKER = "evolved-by-fake-llm"

_FAKE_LLM_RESPONSE = f'''\
<NAME>sum-rewrite</NAME>
<DESCRIPTION>Replace the zero baseline with the actual sum of the input.</DESCRIPTION>

```python
"""Evolved program proposed by the fake LLM."""


def solve(data):
    """Return an aggregate of *data* (the evaluator checks the sum)."""
    # EVOLVE-BLOCK-START
    result = sum(data)  # {_EVOLVED_BLOCK_MARKER}
    # EVOLVE-BLOCK-END
    return result
```
'''

_EVALUATOR = '''\
"""Evaluator for E2E Scenario 3 (instance mode)."""

from __future__ import annotations

import importlib.util
import json


def evaluate_instance(program_path: str, instance_path: str) -> dict[str, float]:
    """Score the candidate program on a single instance.

    combined_score is 1.0 on an exact match and 0.1 otherwise, so the
    weak baseline scores 0.1 and the evolved sum scores 1.0.
    """
    with open(instance_path) as f:
        instance = json.load(f)

    spec = importlib.util.spec_from_file_location("candidate_program", program_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.solve(instance["input"])
    exact = float(result == instance["expected"])
    return {"combined_score": 0.1 + 0.9 * exact, "exact_match": exact}
'''

_TRAIN_INSTANCES = {
    "instance_001.json": {"input": [1, 2, 3], "expected": 6},
    "instance_002.json": {"input": [10, 20], "expected": 30},
    "instance_003.json": {"input": [5], "expected": 5},
}

_EVAL_INSTANCES = {
    "instance_101.json": {"input": [2, 4, 8], "expected": 14},
    "instance_102.json": {"input": [7, 7], "expected": 14},
}


def _invoke(args: list[str]) -> object:
    """Invoke the CLI and fail loudly on unexpected exceptions."""
    return runner.invoke(app, args, catch_exceptions=False)


def _write_instances(directory: Path, instances: dict[str, dict[str, object]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name, payload in instances.items():
        (directory / name).write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.e2e
def test_shinka_backend_happy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_llm_server: FakeLLMServer,
) -> None:
    """Full Scenario 3 workflow on the real ShinkaEvolve engine."""
    fake_llm_server.response_content = _FAKE_LLM_RESPONSE

    # Isolate the global LLM registry (~/.revolver) in tmp_path.
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    # The Ollama discovery URL is not configurable on the CLI yet, so the
    # registration health check is redirected at the fake server (which
    # serves the minimal Ollama-native endpoints). This is the only seam
    # touched by the scenario; everything else runs the real stack.
    import revolver.cli.llm as cli_llm

    monkeypatch.setattr(
        cli_llm, "OllamaClient", lambda: OllamaClient(base_url=fake_llm_server.root_url)
    )

    project_root = tmp_path / "e2e-shinka"

    # Step 1 — project init with the Shinka config scaffold (S14-15)
    result = _invoke(
        [
            "project",
            "init",
            "e2e-shinka",
            "--path",
            str(project_root),
            "--description",
            "E2E Scenario 3",
            "--backend",
            "shinka",
        ]
    )
    assert result.exit_code == 0, _get_all_output(result)
    config_yaml = (project_root / "config.yaml").read_text(encoding="utf-8")
    assert "evo_config" in config_yaml, "expected the Shinka-shaped config scaffold"

    monkeypatch.chdir(project_root)

    # Step 2 — register the fake server as a local LLM
    result = _invoke(
        [
            "llm",
            "add",
            "fake-llm",
            "--source",
            "local",
            "--model",
            "fake-model",
            "--base-url",
            fake_llm_server.openai_base_url,
        ]
    )
    assert result.exit_code == 0, _get_all_output(result)

    # Step 3 — problem files (overwrite the init templates)
    (project_root / "initial_program.py").write_text(_INITIAL_PROGRAM, encoding="utf-8")
    (project_root / "evaluator.py").write_text(_EVALUATOR, encoding="utf-8")
    _write_instances(project_root / "instances", _TRAIN_INSTANCES)
    _write_instances(project_root / "eval_instances", _EVAL_INSTANCES)

    # Step 4 — problem version (validated by the real ShinkaBackend)
    result = _invoke(
        [
            "problem",
            "version",
            "create",
            "--tag",
            "v1.0",
            "--message",
            "E2E Scenario 3",
            "--backend",
            "shinka",
        ]
    )
    output = _get_all_output(result)
    assert result.exit_code == 0, output
    # The scaffolded template must validate cleanly against the real
    # Shinka dataclasses (S14-15: template/validate_config consistency).
    assert "Unknown" not in output, f"template failed Shinka validation: {output}"

    # Step 5 — datasets (train + eval)
    result = _invoke(
        [
            "dataset",
            "add",
            "e2e-train",
            "--path",
            "instances",
            "--split",
            "train",
            "--compatible-with",
            "v1.0",
        ]
    )
    assert result.exit_code == 0, _get_all_output(result)
    result = _invoke(
        [
            "dataset",
            "add",
            "e2e-eval",
            "--path",
            "eval_instances",
            "--split",
            "eval",
            "--compatible-with",
            "v1.0",
        ]
    )
    assert result.exit_code == 0, _get_all_output(result)

    # Step 6 — the run itself (real ShinkaEvolveRunner + fake LLM)
    result = _invoke(
        [
            "run",
            "--backend",
            "shinka",
            "--version",
            "v1.0",
            "--llm",
            "fake-llm",
            "--dataset",
            "e2e-train",
            "--iterations",
            "2",
            "--alias",
            "e2e-shinka",
            "--rewrite-mode",
        ]
    )
    output = _get_all_output(result)
    assert result.exit_code == 0, output

    # The fake LLM was actually queried through the local OpenAI path
    assert fake_llm_server.chat_request_count >= 1, "the engine never queried the fake LLM"

    # Step 7 — run record: backend='shinka', completed (FR-RUN-047)
    db_path = project_root / ".revolver" / "revolver.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        run_row = conn.execute("SELECT * FROM runs").fetchone()
        assert run_row is not None, "expected a run record"
        run_id = run_row["id"]
        assert run_row["backend"] == "shinka"
        assert run_row["status"] == "completed", f"run status: {run_row['status']}"

        solution_row = conn.execute(
            "SELECT * FROM solutions WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert solution_row is not None, "expected a rank-1 solution record"
        assert solution_row["alias"] == "e2e-shinka"
    finally:
        conn.close()

    run_dir = project_root / ".revolver" / "runs" / run_id

    # Step 8 — engine artifacts: shinka-output and ranked programs
    assert (run_dir / "shinka-output" / "programs.sqlite").is_file(), (
        "expected the ShinkaEvolve programs database in shinka-output/"
    )

    rank1 = run_dir / "programs" / "rank-1.py"
    assert rank1.is_file(), "expected programs/rank-1.py after the run"
    rank1_content = rank1.read_text(encoding="utf-8")
    # The best program must be a genuine evolution product, NOT the
    # initial program (guards the silent wrong-solution trap).
    assert rank1_content != _INITIAL_PROGRAM
    assert _EVOLVED_BLOCK_MARKER in rank1_content, (
        f"rank-1.py is not the fake-LLM rewrite:\n{rank1_content}"
    )

    # Step 9 — run manifest: backend + native token accounting (ADR-007 D2)
    manifest_path = run_dir / "manifest.yaml"
    assert manifest_path.is_file(), "expected the run manifest"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert manifest["backend"] == "shinka"
    assert manifest["run_id"] == run_id
    token_usage = manifest.get("token_usage")
    assert token_usage is not None, "expected native token usage (no HTTP proxy on shinka)"
    assert token_usage["prompt_tokens"] > 0
    assert token_usage["completion_tokens"] > 0

    # Step 10 — solution list shows the aliased solution (FR-SOL-001)
    result = _invoke(["--json", "solution", "list"])
    assert result.exit_code == 0, _get_all_output(result)
    solutions = _parse_json_output(result)
    assert isinstance(solutions, list) and len(solutions) == 1
    assert solutions[0]["alias"] == "e2e-shinka"
    assert solutions[0]["run_id"] == run_id

    # Step 11 — engine-neutral downstream: eval on the eval split
    result = _invoke(["eval", "--solution", "e2e-shinka", "--dataset", "e2e-eval"])
    assert result.exit_code == 0, _get_all_output(result)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        meta = conn.execute("SELECT * FROM eval_metadata").fetchone()
        assert meta is not None, "expected an eval_metadata record"
        assert meta["dataset_name"] == "e2e-eval"
        assert meta["instance_count"] == len(_EVAL_INSTANCES)
        # The evolved sum solves every eval instance
        assert meta["instances_solved"] == len(_EVAL_INSTANCES)

        statuses = {
            row["status"] for row in conn.execute("SELECT status FROM eval_instances").fetchall()
        }
        assert statuses == {"solved"}
    finally:
        conn.close()

    # Step 12 — eval results render without error
    result = _invoke(["eval", "results", "--solution", "e2e-shinka", "--dataset", "e2e-eval"])
    assert result.exit_code == 0, _get_all_output(result)
