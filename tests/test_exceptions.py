"""Unit tests for typed exceptions and CLI error handler.

Covers:
- Each exception maps to the correct exit code per specs §4.2
- Error handler renders messages to stderr
- cli_error_boundary context manager catches and exits correctly
"""

from __future__ import annotations

import sys
from io import StringIO

import pytest
import typer

from revolver.cli.error_handler import cli_error_boundary, handle_error
from revolver.core.exceptions import (
    DuplicateNameError,
    ExternalError,
    IntegrityError,
    ProjectNotFoundError,
    ResourceError,
    RevolverError,
    ValidationError,
)

# ── Exit code mapping tests ──────────────────────────────────────────────────


@pytest.mark.unit
class TestExitCodeMapping:
    """Each exception class maps to the correct exit code."""

    def test_revolver_error_exit_code(self) -> None:
        assert handle_error(RevolverError("general")) == 1

    def test_project_not_found_exit_code(self) -> None:
        assert handle_error(ProjectNotFoundError("not found")) == 1

    def test_integrity_error_exit_code(self) -> None:
        assert handle_error(IntegrityError("hash mismatch")) == 2

    def test_resource_error_exit_code(self) -> None:
        assert handle_error(ResourceError("ollama down")) == 3

    def test_external_error_exit_code(self) -> None:
        assert handle_error(ExternalError("api failure")) == 4

    def test_validation_error_exit_code(self) -> None:
        assert handle_error(ValidationError("bad input")) == 1

    def test_duplicate_name_error_exit_code(self) -> None:
        assert handle_error(DuplicateNameError("already exists")) == 1


# ── Exception hierarchy tests ────────────────────────────────────────────────


@pytest.mark.unit
class TestExceptionHierarchy:
    """All exceptions are subclasses of RevolverError."""

    def test_project_not_found_is_revolver_error(self) -> None:
        assert issubclass(ProjectNotFoundError, RevolverError)

    def test_integrity_error_is_revolver_error(self) -> None:
        assert issubclass(IntegrityError, RevolverError)

    def test_resource_error_is_revolver_error(self) -> None:
        assert issubclass(ResourceError, RevolverError)

    def test_external_error_is_revolver_error(self) -> None:
        assert issubclass(ExternalError, RevolverError)

    def test_validation_error_is_revolver_error(self) -> None:
        assert issubclass(ValidationError, RevolverError)

    def test_duplicate_name_error_is_revolver_error(self) -> None:
        assert issubclass(DuplicateNameError, RevolverError)

    def test_revolver_error_is_exception(self) -> None:
        assert issubclass(RevolverError, Exception)


# ── Exception message tests ──────────────────────────────────────────────────


@pytest.mark.unit
class TestExceptionMessages:
    """Exceptions preserve their message."""

    def test_message_preserved(self) -> None:
        exc = RevolverError("something went wrong")
        assert str(exc) == "something went wrong"

    def test_empty_message(self) -> None:
        exc = RevolverError()
        assert str(exc) == ""

    def test_subclass_message(self) -> None:
        exc = IntegrityError("hash mismatch on dataset foo")
        assert str(exc) == "hash mismatch on dataset foo"


# ── Error handler stderr rendering tests ─────────────────────────────────────


@pytest.mark.unit
class TestErrorHandlerStderr:
    """Error handler renders error messages to stderr."""

    def test_renders_message_to_stderr(self) -> None:
        captured = StringIO()
        original_stderr = sys.stderr
        sys.stderr = captured
        try:
            with pytest.raises(typer.Exit) as exc_info, cli_error_boundary():
                raise RevolverError("disk full")
            assert exc_info.value.exit_code == 1
        finally:
            sys.stderr = original_stderr
        assert "Error: disk full" in captured.getvalue()

    def test_renders_class_name_when_no_message(self) -> None:
        captured = StringIO()
        original_stderr = sys.stderr
        sys.stderr = captured
        try:
            with pytest.raises(typer.Exit) as exc_info, cli_error_boundary():
                raise ResourceError()
            assert exc_info.value.exit_code == 3
        finally:
            sys.stderr = original_stderr
        assert "Error: ResourceError" in captured.getvalue()


# ── cli_error_boundary context manager tests ─────────────────────────────────


@pytest.mark.unit
class TestCliErrorBoundary:
    """Context manager catches RevolverError and raises typer.Exit."""

    def test_no_error_passes_through(self) -> None:
        """No exception means no exit."""
        with cli_error_boundary():
            pass  # no error

    def test_revolver_error_raises_exit(self) -> None:
        with pytest.raises(typer.Exit) as exc_info, cli_error_boundary():
            raise RevolverError("fail")
        assert exc_info.value.exit_code == 1

    def test_integrity_error_raises_exit_code_2(self) -> None:
        with pytest.raises(typer.Exit) as exc_info, cli_error_boundary():
            raise IntegrityError("corrupted")
        assert exc_info.value.exit_code == 2

    def test_resource_error_raises_exit_code_3(self) -> None:
        with pytest.raises(typer.Exit) as exc_info, cli_error_boundary():
            raise ResourceError("no gpu")
        assert exc_info.value.exit_code == 3

    def test_external_error_raises_exit_code_4(self) -> None:
        with pytest.raises(typer.Exit) as exc_info, cli_error_boundary():
            raise ExternalError("api down")
        assert exc_info.value.exit_code == 4

    def test_non_revolver_error_propagates(self) -> None:
        """Non-RevolverError exceptions are not caught."""
        with pytest.raises(ValueError, match="unrelated"), cli_error_boundary():
            raise ValueError("unrelated")
