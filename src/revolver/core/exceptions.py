"""Typed exception hierarchy with exit code mapping.

Exit codes follow the specification (specs §4.2):
- 0: Success
- 1: General error (invalid arguments, missing files, validation, duplicates)
- 2: Integrity error (hash mismatch, corrupted data)
- 3: Resource error (Ollama not running, GPU not available, OOM)
- 4: External error (OpenEvolve failure, LLM API error)
"""


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
