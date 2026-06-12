"""L2-Shinka contract tests for ShinkaBackend DB-reading methods (S14-03).

Pins the ``programs.sqlite`` reading contract against the fixture DB built
by ``tests/fixtures/programs_sqlite.py`` (schema byte-compatible with
shinka-evolve 0.0.7 — see sprint-014 §"Verified shinka-evolve 0.0.7 schema
facts"):

- ``collect_token_usage()`` sums tokens from ``metadata.llm_result.*`` and
  USD cost from the top-level ``metadata.api_costs`` key; a file-based
  init row (NO ``llm_result`` key at all) and a row with a SQL ``NULL``
  ``metadata`` column must not crash and count 0 tokens.
- ``parse_population()`` returns programs ranked by ``combined_score``
  descending, with **no** ``cell_indices`` field (no MAP-Elites on Shinka).
- ``count_valid()`` counts rows where ``correct = 1``.
- ``read_progress()`` returns ``(last_generation, best_combined_score)``.

The backend is still the S13 stub (raises ``BackendUnavailableError``), so
every test is ``xfail(strict=False)`` until the implementation lands in
S14 PR-C — keeping PR-A independently mergeable.

Skipped automatically when shinka-evolve is not installed (mirrors L2-OE).

Traceable to: sprint-014 S14-03/S14-11/S14-12, issue #190, ADR-007 D2,
val-integration-tests.md §L2-Shinka.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("shinka.database", reason="shinka-evolve not installed")

from revolver.infra.backends.shinka import ShinkaBackend
from tests.fixtures.programs_sqlite import (
    EXPECTED_BEST_SCORE,
    EXPECTED_COMPLETION_TOKENS,
    EXPECTED_COST_USD,
    EXPECTED_LAST_GENERATION,
    EXPECTED_PROMPT_TOKENS,
    EXPECTED_RANKED_IDS,
    EXPECTED_VALID_COUNT,
    build_shinka_run_dir,
)

xfail_stub = pytest.mark.xfail(
    strict=False,
    reason="ShinkaBackend DB-reading methods are the S13 stub — implementation lands in S14 PR-C",
)


@pytest.fixture()
def shinka_run_dir(tmp_path: Path) -> Path:
    """A run dir with the fixture ``shinka-output/programs.sqlite``."""
    return build_shinka_run_dir(tmp_path / "run")


@pytest.mark.integration
@pytest.mark.shinkaevolve
class TestShinkaDbContract:
    """DB-reading contract against the fixture programs.sqlite."""

    @xfail_stub
    def test_collect_token_usage_sums_metadata(self, shinka_run_dir: Path) -> None:
        """(a) Tokens from metadata.llm_result.*, cost from metadata.api_costs.

        The file-based init row has NO ``llm_result`` key at all (the shape
        every real Revolver Shinka run produces for generation 0) and one
        row has a SQL ``NULL`` ``metadata`` column — both must count 0
        tokens without crashing; the init row's ``api_costs`` still
        contributes to the USD total. Completion tokens are
        ``output_tokens + thinking_tokens`` (sum equals total
        completion-side tokens across all shinka 0.0.7 providers).
        """
        usage = ShinkaBackend().collect_token_usage(shinka_run_dir)

        assert usage is not None
        assert usage.prompt_tokens == EXPECTED_PROMPT_TOKENS
        assert usage.completion_tokens == EXPECTED_COMPLETION_TOKENS
        assert usage.estimated_cost_usd == pytest.approx(EXPECTED_COST_USD)

    @xfail_stub
    def test_collect_token_usage_missing_db_returns_none(self, tmp_path: Path) -> None:
        """(a-bis) No programs.sqlite (run died early) → None, no crash (S14-11)."""
        empty_run_dir = tmp_path / "run"
        empty_run_dir.mkdir()

        assert ShinkaBackend().collect_token_usage(empty_run_dir) is None

    @xfail_stub
    def test_parse_population_ranked_no_cell_indices(self, shinka_run_dir: Path) -> None:
        """(b) Population ranked by combined_score desc, no cell_indices field."""
        population = ShinkaBackend().parse_population(shinka_run_dir)

        assert population is not None
        assert len(population) >= len(EXPECTED_RANKED_IDS)

        # Scored programs appear in descending combined_score order.
        scored: list[dict[str, Any]] = [
            entry for entry in population if entry.get("combined_score") is not None
        ]
        assert [entry["id"] for entry in scored] == list(EXPECTED_RANKED_IDS)
        scores = [entry["combined_score"] for entry in scored]
        assert scores == sorted(scores, reverse=True)

        # S14-12 contract: id/generation/combined_score/correct/public_metrics,
        # and never the OE-only MAP-Elites fields.
        for entry in population:
            for key in ("id", "generation", "combined_score", "correct", "public_metrics"):
                assert key in entry, f"population entry is missing key: {key}"
            assert "cell_indices" not in entry

    @xfail_stub
    def test_count_valid_counts_correct_rows(self, shinka_run_dir: Path) -> None:
        """(c) count_valid() counts rows where correct = 1."""
        assert ShinkaBackend().count_valid(shinka_run_dir) == EXPECTED_VALID_COUNT

    @xfail_stub
    def test_read_progress_returns_last_generation_and_best_score(
        self, shinka_run_dir: Path
    ) -> None:
        """(d) read_progress() returns (last_generation, best_combined_score)."""
        iterations_done, best_score = ShinkaBackend().read_progress(shinka_run_dir)

        assert iterations_done == EXPECTED_LAST_GENERATION
        assert best_score == pytest.approx(EXPECTED_BEST_SCORE)
