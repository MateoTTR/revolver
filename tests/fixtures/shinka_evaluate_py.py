"""Golden-content helper: reference Shinka ``evaluate.py`` wrapper (S14-01).

Provides the **reference implementation** of the evaluator wrapper that
``ShinkaBackend.generate_wrapper()`` must produce in Sprint 014 (S14-09),
plus the textual markers every conforming wrapper must contain. The R4
contract tests (``tests/integration/test_shinka_wrapper.py``) execute this
golden wrapper against real ``shinka.core.run_shinka_eval`` today, so the
contract itself is verified before the implementation lands (PR-B).

Wrapper contract (DES-006 §1.3, sprint-014 S14-09):

- Valid Shinka CLI evaluator script: invoked by Shinka's job scheduler as
  ``python evaluate.py --program_path <program> --results_dir <dir>``
  (verified in ``shinka/launch/scheduler.py::_build_command``).
- Calls ``shinka.core.run_shinka_eval``, which writes
  ``<results_dir>/metrics.json`` and ``<results_dir>/correct.json``.
- Imports and calls the user's ``evaluate_instance(program_path,
  instance_path)`` (never the legacy ``evaluate()``) over every dataset
  instance found in ``$REVOLVER_DATASET_DIR``.
- Aggregates per-instance metrics as the mean per numeric key; the
  aggregate must include ``combined_score``.
- A failing evaluator or missing ``combined_score`` yields
  ``correct.json`` with ``correct: false`` (run_shinka_eval's error path).

Reference technique: the wrapper passes **itself** as the experiment
module to ``run_shinka_eval`` (which loads ``program_path`` and calls
``experiment_fn_name`` on it) and hands the real evolved-program path over
via an environment variable. Implementations are free to use another
technique (e.g. a synthesized shim module) as long as the observable
contract above holds.
"""

from __future__ import annotations

from pathlib import Path

#: Textual markers every conforming generated wrapper must contain.
#: Kept deliberately coarse so PR-B retains implementation freedom.
GOLDEN_WRAPPER_MARKERS: tuple[str, ...] = (
    "run_shinka_eval",
    "--program_path",
    "--results_dir",
    "evaluate_instance",
    "REVOLVER_DATASET_DIR",
    "combined_score",
)

_GOLDEN_WRAPPER_TEMPLATE = '''\
"""Shinka evaluator wrapper — Revolver reference golden content (S14).

Invoked by Shinka's job scheduler as:
    python evaluate.py --program_path <program.py> --results_dir <dir>
"""

import argparse
import importlib.util
import os
from pathlib import Path

from shinka.core import run_shinka_eval

_SNAPSHOT_DIR = "@SNAPSHOT_DIR@"
_PROGRAM_PATH_ENV = "_REVOLVER_SHINKA_PROGRAM_PATH"


def _load_evaluate_instance():
    """Import the user's evaluate_instance() from the snapshot evaluator."""
    evaluator_path = Path(_SNAPSHOT_DIR) / "evaluator.py"
    spec = importlib.util.spec_from_file_location(
        "_revolver_user_evaluator", str(evaluator_path)
    )
    if spec is None or spec.loader is None:
        raise ImportError("Cannot load evaluator from " + str(evaluator_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.evaluate_instance


def _instances():
    """List dataset instance files from $REVOLVER_DATASET_DIR (sorted)."""
    dataset_dir = os.environ["REVOLVER_DATASET_DIR"]
    return sorted(
        str(p)
        for p in Path(dataset_dir).iterdir()
        if p.is_file() and not p.name.startswith(".")
    )


def run_experiment(instance_path):
    """Experiment entry point loaded by run_shinka_eval (one instance)."""
    evaluate_instance = _load_evaluate_instance()
    program_path = os.environ[_PROGRAM_PATH_ENV]
    return evaluate_instance(program_path, instance_path)


def _validate(result):
    """Per-instance validation: metrics dict with numeric combined_score."""
    if not isinstance(result, dict):
        return False, "evaluate_instance() must return a metrics dict"
    if not isinstance(result.get("combined_score"), (int, float)):
        return False, "metrics are missing a numeric combined_score"
    return True, None


def _aggregate(results):
    """Aggregate per-instance metrics: mean per numeric key."""
    keys = set()
    for result in results:
        if isinstance(result, dict):
            keys.update(
                k for k, v in result.items() if isinstance(v, (int, float))
            )
    metrics = {}
    for key in sorted(keys):
        values = [
            r[key]
            for r in results
            if isinstance(r, dict) and isinstance(r.get(key), (int, float))
        ]
        if values:
            metrics[key] = sum(values) / len(values)
    if "combined_score" not in metrics:
        raise RuntimeError("evaluate_instance() metrics are missing combined_score")
    return metrics


def main():
    parser = argparse.ArgumentParser(
        description="Revolver-generated Shinka evaluator wrapper"
    )
    parser.add_argument("--program_path", required=True)
    parser.add_argument("--results_dir", required=True)
    args = parser.parse_args()

    os.environ[_PROGRAM_PATH_ENV] = args.program_path
    instances = _instances()
    run_shinka_eval(
        program_path=__file__,
        results_dir=args.results_dir,
        experiment_fn_name="run_experiment",
        num_runs=len(instances),
        get_experiment_kwargs=lambda run_idx: {"instance_path": instances[run_idx]},
        aggregate_metrics_fn=_aggregate,
        validate_fn=_validate,
    )


if __name__ == "__main__":
    main()
'''


def golden_wrapper_content(snapshot_dir: Path) -> str:
    """Render the reference wrapper for a given problem snapshot.

    Args:
        snapshot_dir: Problem version snapshot directory containing the
            user's ``evaluator.py``.

    Returns:
        The full wrapper script source.
    """
    return _GOLDEN_WRAPPER_TEMPLATE.replace('"@SNAPSHOT_DIR@"', repr(str(snapshot_dir)))


def write_golden_wrapper(snapshot_dir: Path, output_path: Path) -> Path:
    """Write the reference wrapper to *output_path* and return it."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(golden_wrapper_content(snapshot_dir))
    return output_path
