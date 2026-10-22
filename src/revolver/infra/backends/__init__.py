"""Evolution backend adapters (ADR-007).

Public surface of the pluggable evolution backend abstraction:
the ``EvolutionBackend`` protocol, the ``get_backend()`` factory and
the registered adapters (OpenEvolve default, ShinkaEvolve stub).
"""

from revolver.infra.backends.base import (
    AVAILABLE_BACKENDS,
    BackendCapabilities,
    BackendRunResult,
    BackendRunSpec,
    BackendUnavailableError,
    EvolutionBackend,
    ProgressInfo,
    get_backend,
)
from revolver.infra.backends.agentic import AgenticBackend
from revolver.infra.backends.loongflow import LoongFlowBackend
from revolver.infra.backends.openevolve import OpenEvolveBackend
from revolver.infra.backends.shinka import ShinkaBackend

__all__ = [
    "AVAILABLE_BACKENDS",
    "AgenticBackend",
    "BackendCapabilities",
    "BackendRunResult",
    "BackendRunSpec",
    "BackendUnavailableError",
    "EvolutionBackend",
    "LoongFlowBackend",
    "OpenEvolveBackend",
    "ProgressInfo",
    "ShinkaBackend",
    "get_backend",
]
