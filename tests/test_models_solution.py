"""L1 unit tests for revolver.models.solution — Solution Pydantic model (S4-05)."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from revolver.models.solution import Solution


class TestSolution:
    """Tests for Solution model."""

    @pytest.mark.unit
    def test_creation(self) -> None:
        """Solution can be created with valid data."""
        sol = Solution(
            id="sol-20260310-143000",
            run_id="run-20260310-143000",
            rank=1,
            best_score=0.95,
            alias="best-v1",
        )
        assert sol.id == "sol-20260310-143000"
        assert sol.run_id == "run-20260310-143000"
        assert sol.rank == 1
        assert sol.best_score == 0.95
        assert sol.alias == "best-v1"

    @pytest.mark.unit
    def test_nullable_alias(self) -> None:
        """Solution accepts None alias."""
        sol = Solution(
            id="sol-1",
            run_id="run-1",
            rank=1,
            best_score=0.90,
        )
        assert sol.alias is None

    @pytest.mark.unit
    def test_nullable_best_score(self) -> None:
        """Solution accepts None best_score."""
        sol = Solution(
            id="sol-1",
            run_id="run-1",
            rank=2,
        )
        assert sol.best_score is None

    @pytest.mark.unit
    def test_missing_required_raises(self) -> None:
        """Solution raises ValidationError when required fields are missing."""
        with pytest.raises(ValidationError):
            Solution(id="sol-1")  # type: ignore[call-arg]

    @pytest.mark.unit
    def test_serialization_round_trip(self) -> None:
        """Solution serializes to dict and back."""
        sol = Solution(
            id="sol-20260310-143000",
            run_id="run-20260310-143000",
            rank=1,
            best_score=0.95,
            alias="my-sol",
        )
        data = sol.model_dump()
        restored = Solution.model_validate(data)
        assert restored == sol

    @pytest.mark.unit
    def test_mutable(self) -> None:
        """Solution is not frozen (no ConfigDict frozen=True)."""
        sol = Solution(
            id="sol-1",
            run_id="run-1",
            rank=1,
        )
        # Should not raise — Solution is mutable
        sol.alias = "updated"
        assert sol.alias == "updated"

    @pytest.mark.unit
    def test_defaults(self) -> None:
        """Solution applies defaults for optional fields."""
        sol = Solution(
            id="sol-1",
            run_id="run-1",
            rank=3,
        )
        assert sol.best_score is None
        assert sol.alias is None
