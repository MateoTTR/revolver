"""DEPRECATED shim — content moved to ``revolver.infra.backends.openevolve``.

The OpenEvolve integration was relocated into the pluggable backend
package (ADR-007 D1, Sprint 013). This module re-exports the full
public surface (plus the private helpers exercised by tests) so every
pre-existing import keeps working unmodified.

Deprecation: import from ``revolver.infra.backends.openevolve`` instead.
This shim is scheduled for removal in Sprint 015.

Note: the module's logger name changed with the move — records now log
under ``revolver.infra.backends.openevolve`` (logging configs filtering
on the old name must be updated).
"""

from __future__ import annotations

from revolver.infra.backends.openevolve import (
    _DATABASE_KEYS as _DATABASE_KEYS,
    REVOLVER_KEYS,
    SYSTEM_PROMPT_TEMPLATE as SYSTEM_PROMPT_TEMPLATE,
    OpenEvolveRunner,
    ProgressInfo,
    RunOutput,
    _build_cell_reverse_map as _build_cell_reverse_map,
    _build_ensemble_llm_config as _build_ensemble_llm_config,
    _extract_best_score as _extract_best_score,
    _parse_value as _parse_value,
    _set_nested as _set_nested,
    build_config,
    count_valid_programs,
    find_latest_checkpoint,
    parse_population,
    read_checkpoint_best_score,
    resolve_api_keys,
    revolver_env,
    validate_oe_config,
)

__all__ = [
    "REVOLVER_KEYS",
    "OpenEvolveRunner",
    "ProgressInfo",
    "RunOutput",
    "build_config",
    "count_valid_programs",
    "find_latest_checkpoint",
    "parse_population",
    "read_checkpoint_best_score",
    "resolve_api_keys",
    "revolver_env",
    "validate_oe_config",
]
