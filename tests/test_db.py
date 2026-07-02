"""L1 unit tests for revolver.infra.db — SQLite connection factory and schema."""

from __future__ import annotations

from pathlib import Path

import pytest

from revolver.infra.db import CURRENT_SCHEMA_VERSION, get_project_db


@pytest.mark.unit
def test_wal_mode_enabled(tmp_path: Path) -> None:
    """Project DB must use WAL journal mode (NFR-016)."""
    db_path = tmp_path / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode == "wal", f"Expected WAL mode, got {mode}"
    finally:
        conn.close()


@pytest.mark.unit
def test_foreign_keys_enabled(tmp_path: Path) -> None:
    """Project DB must have foreign_keys pragma enabled."""
    db_path = tmp_path / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("PRAGMA foreign_keys")
        fk = cursor.fetchone()[0]
        assert fk == 1, f"Expected foreign_keys=1, got {fk}"
    finally:
        conn.close()


@pytest.mark.unit
def test_all_tables_created(tmp_path: Path) -> None:
    """Project DB must contain all tables from DES-001."""
    expected_tables = {
        "schema_version",
        "problem_versions",
        "datasets",
        "dataset_instances",
        "dataset_compat",
        "runs",
        "solutions",
        "eval_metadata",
        "eval_instances",
        "benchmarks",
        "benchmark_solutions",
    }
    db_path = tmp_path / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        actual_tables = {row[0] for row in cursor.fetchall()}
        assert expected_tables.issubset(actual_tables), (
            f"Missing tables: {expected_tables - actual_tables}"
        )
    finally:
        conn.close()


@pytest.mark.unit
def test_schema_version(tmp_path: Path) -> None:
    """schema_version table must contain version=1 after initialization."""
    db_path = tmp_path / "revolver.db"
    conn = get_project_db(db_path)
    try:
        cursor = conn.execute("SELECT version FROM schema_version")
        row = cursor.fetchone()
        assert row is not None, "schema_version table is empty"
        assert row[0] == CURRENT_SCHEMA_VERSION, (
            f"Expected version {CURRENT_SCHEMA_VERSION}, got {row[0]}"
        )
    finally:
        conn.close()


@pytest.mark.unit
def test_global_db_has_llms_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Global DB must contain the llms table."""
    # Redirect HOME to tmp_path to avoid touching real ~/.revolver/
    monkeypatch.setenv("HOME", str(tmp_path))
    # Also patch Path.home() directly since it may cache
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))  # type: ignore[arg-type]

    from revolver.infra.db import get_global_db

    conn = get_global_db()
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='llms'")
        assert cursor.fetchone() is not None, "llms table not found in global DB"
    finally:
        conn.close()


@pytest.mark.unit
def test_global_db_respects_revolver_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """get_global_db honours $REVOLVER_HOME over the user's home.

    This isolates the global store across parallel CI runners that share
    $HOME — otherwise they race on the ``schema_version`` migration.
    """
    home_dir = tmp_path / "home"
    state_dir = tmp_path / "state"
    # Home points elsewhere; REVOLVER_HOME must win.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home_dir))  # type: ignore[arg-type]
    monkeypatch.setenv("REVOLVER_HOME", str(state_dir))

    from revolver.infra.db import get_global_db

    conn = get_global_db()
    try:
        assert (state_dir / ".revolver" / "revolver.db").exists()
        assert not (home_dir / ".revolver").exists()
    finally:
        conn.close()


# ── S17-32(b): --global-db / REVOLVER_GLOBAL_DB override ──────────────────────


@pytest.mark.unit
def test_global_db_path_default_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """global_db_path() defaults to ~/.revolver/revolver.db with no env set."""
    monkeypatch.delenv("REVOLVER_HOME", raising=False)
    monkeypatch.delenv("REVOLVER_GLOBAL_DB", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))  # type: ignore[arg-type]

    from revolver.infra.db import global_db_path

    assert global_db_path() == tmp_path / ".revolver" / "revolver.db"


@pytest.mark.unit
def test_global_db_path_revolver_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """REVOLVER_HOME (a base dir) overrides home when --global-db is unset."""
    monkeypatch.delenv("REVOLVER_GLOBAL_DB", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))  # type: ignore[arg-type]
    monkeypatch.setenv("REVOLVER_HOME", str(tmp_path / "state"))

    from revolver.infra.db import global_db_path

    assert global_db_path() == tmp_path / "state" / ".revolver" / "revolver.db"


@pytest.mark.unit
def test_global_db_path_override_beats_revolver_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Precedence: --global-db (a full file path) beats REVOLVER_HOME beats home."""
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))  # type: ignore[arg-type]
    monkeypatch.setenv("REVOLVER_HOME", str(tmp_path / "state"))
    override = tmp_path / "custom" / "x.db"
    monkeypatch.setenv("REVOLVER_GLOBAL_DB", str(override))

    from revolver.infra.db import global_db_path

    assert global_db_path() == override


@pytest.mark.unit
def test_get_global_db_uses_override_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """get_global_db() opens the exact --global-db path, creating parents.

    The default store (home / REVOLVER_HOME) must be untouched.
    """
    home_dir = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home_dir))  # type: ignore[arg-type]
    monkeypatch.delenv("REVOLVER_HOME", raising=False)
    override = tmp_path / "nested" / "override.db"
    monkeypatch.setenv("REVOLVER_GLOBAL_DB", str(override))

    from revolver.infra.db import get_global_db

    conn = get_global_db()
    try:
        assert override.exists()
        # The default home store was never created.
        assert not (home_dir / ".revolver").exists()
    finally:
        conn.close()
