"""ShinkaEvolve backend — registered stub (ADR-007, Sprint 013).

The real adapter lands in Sprint 014. This stub is registered in the
``get_backend()`` factory so the spec'd error paths are testable now:

- ``--backend shinka`` while not installed → exit 3 with an install hint
  (``BackendUnavailableError``);
- ``doctor`` reports ShinkaEvolve availability as informational.

Capabilities follow the ADR-007 matrix; every engine method raises
:class:`~revolver.infra.backends.base.BackendUnavailableError`.

Traceable to: ADR-007 (Pluggable Evolution Backend), sprint-013 S13-03.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from revolver.infra.backends.base import (
    BackendCapabilities,
    BackendRunResult,
    BackendRunSpec,
    BackendUnavailableError,
    ProgressInfo,
)
from revolver.models.run import ResolvedConfig, TokenUsage

_INSTALL_HINT = "Install with: pip install 'revolver[shinka]'"


class ShinkaBackend:
    """``EvolutionBackend`` protocol stub for ShinkaEvolve (S14 implements it)."""

    name: str = "shinka"

    def capabilities(self) -> BackendCapabilities:
        """Return the ShinkaEvolve capability matrix (ADR-007)."""
        return BackendCapabilities(
            global_seed=False,
            map_elites_cells=False,
            native_cost_tracking=True,
            multi_language=True,
            ensemble_model="bandit",
            top_n_extraction=True,
        )

    def is_available(self) -> tuple[bool, str | None]:
        """The ShinkaEvolve backend is not implemented yet (S14)."""
        return (False, _INSTALL_HINT)

    def wants_http_proxy(self) -> bool:
        """ShinkaEvolve tracks tokens natively — no HTTP proxy (ADR-007 D2)."""
        return False

    # ── Engine methods — all unavailable until S14 ───────────────────────────

    def _unavailable(self) -> BackendUnavailableError:
        """Build the typed not-installed error (CLI maps it to exit 3)."""
        return BackendUnavailableError(
            f"The ShinkaEvolve backend is not available. {_INSTALL_HINT}"
        )

    def config_template(self) -> str:
        """Not available until S14."""
        raise self._unavailable()

    def validate_config(self, config: Path | dict[str, Any]) -> list[str]:
        """Not available until S14."""
        raise self._unavailable()

    def build_config(self, spec: BackendRunSpec) -> dict[str, Any]:
        """Not available until S14."""
        raise self._unavailable()

    def resolved_config(
        self,
        config: dict[str, Any],
        config_overrides: dict[str, Any] | None = None,
    ) -> ResolvedConfig:
        """Not available until S14."""
        raise self._unavailable()

    def generate_wrapper(self, spec: BackendRunSpec) -> Path:
        """Not available until S14."""
        raise self._unavailable()

    def launch(
        self,
        spec: BackendRunSpec,
        config: dict[str, Any],
        on_progress: Callable[[ProgressInfo], None] | None = None,
    ) -> BackendRunResult:
        """Not available until S14."""
        raise self._unavailable()

    def resume(
        self,
        spec: BackendRunSpec,
        config: dict[str, Any],
        parent_run_dir: Path,
        on_progress: Callable[[ProgressInfo], None] | None = None,
    ) -> BackendRunResult:
        """Not available until S14."""
        raise self._unavailable()

    def read_progress(self, run_dir: Path) -> tuple[int | None, float | None]:
        """Not available until S14."""
        raise self._unavailable()

    def parse_population(self, run_dir: Path) -> list[dict[str, Any]] | None:
        """Not available until S14."""
        raise self._unavailable()

    def count_valid(self, run_dir: Path) -> int | None:
        """Not available until S14."""
        raise self._unavailable()

    def collect_token_usage(self, run_dir: Path) -> TokenUsage | None:
        """Not available until S14."""
        raise self._unavailable()


__all__ = ["ShinkaBackend"]
