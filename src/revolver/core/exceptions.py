"""Typed exception hierarchy with exit code mapping.

Exit codes follow the specification (specs §4.2):
- 0: Success
- 1: General error (invalid arguments, missing files, validation, duplicates)
- 2: Integrity error (hash mismatch, corrupted data)
- 3: Resource error (Ollama not running, GPU not available, OOM)
- 4: External error (OpenEvolve failure, LLM API error)
"""

from __future__ import annotations


class RevolverError(Exception):
    """Base exception for all Revolver errors.

    Attributes:
        exit_code: CLI exit code associated with this error category.
    """

    exit_code: int = 1

    def __init__(self, message: str = "") -> None:
        super().__init__(message)


class ProjectNotFoundError(RevolverError):
    """Raised when no .revolver/ project is found in the directory hierarchy."""

    exit_code: int = 1


class IntegrityError(RevolverError):
    """Raised on hash mismatch or corrupted data."""

    exit_code: int = 2


class ResourceError(RevolverError):
    """Raised when a required resource is unavailable (Ollama, GPU, memory)."""

    exit_code: int = 3


class ExternalError(RevolverError):
    """Raised on failure from an external system (OpenEvolve, LLM API)."""

    exit_code: int = 4


class ValidationError(RevolverError):
    """Raised when input validation fails."""

    exit_code: int = 1


class DuplicateNameError(RevolverError):
    """Raised when a resource with the same name already exists."""

    exit_code: int = 1


class EvaluatorLoadError(RevolverError):
    """Raised when an evaluator module cannot be loaded or is invalid."""

    exit_code: int = 1


class EvalError(RevolverError):
    """Raised when an evaluation operation fails."""

    exit_code: int = 1


class EvalAborted(RevolverError):
    """Raised when an evaluation is cancelled by the user."""

    exit_code: int = 1


class EvalNotFoundError(RevolverError):
    """Raised when no evaluation results are found for a query."""

    exit_code: int = 1


class BenchmarkError(RevolverError):
    """Raised when a benchmark operation fails (e.g. all evaluations failed).

    Exit code 4: treated as an external error per DES-007 §2.1.
    """

    exit_code: int = 4


class BenchmarkNotFoundError(RevolverError):
    """Raised when a requested benchmark is not found in the database."""

    exit_code: int = 1


class ActiveRunError(RevolverError):
    """Raised when an operation is attempted on an active (running) run."""

    exit_code: int = 1


class ExportError(RevolverError):
    """Raised when an export operation fails (invalid format, unwritable path)."""

    exit_code: int = 1


class CheckpointRecoveryError(RevolverError):
    """Raised when best-of-interrupted-run recovery cannot produce a program.

    Distinct from :class:`RecoveryNotSupportedError`: the backend *does*
    support checkpoint recovery, but no usable checkpoint exists yet (the run
    was too short) or the checkpoint on disk is unreadable (B7 / FR-RUN-051).
    """

    exit_code: int = 1


class RecoveryNotSupportedError(RevolverError):
    """Raised when a backend cannot recover a best program from a checkpoint.

    Distinct from :class:`CheckpointRecoveryError`: the backend has no
    checkpoint-based recovery mechanism at all (e.g. ShinkaEvolve, whose
    interrupted-run state is its ``programs.sqlite`` — B7 / FR-RUN-051).
    """

    exit_code: int = 1


# ── Ollama / LLM exceptions ─────────────────────────────────────────────────


class OllamaNotRunningError(ResourceError):
    """Raised when the Ollama daemon is not reachable."""

    exit_code: int = 3


class ModelNotFoundError(RevolverError):
    """Raised when a requested model is not found locally."""

    exit_code: int = 1


class ModelPullError(ExternalError):
    """Raised when a model pull from the Ollama registry fails."""

    exit_code: int = 4


class ModelHealthCheckError(ExternalError):
    """Raised when a health-check prompt to a model fails."""

    exit_code: int = 4


class ModelLoadTimeoutError(ResourceError):
    """Raised when a model fails to load within the allowed timeout."""

    exit_code: int = 3
