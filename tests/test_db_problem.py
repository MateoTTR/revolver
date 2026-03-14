"""Tests for problem version DB CRUD (S2-10)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from revolver.core.exceptions import DuplicateNameError
from revolver.infra.db import (
    get_problem_version,
    get_problem_version_by_hash,
    get_project_db,
    insert_problem_version,
    list_problem_versions,
)
from revolver.models.problem import ProblemVersion


@pytest.fixture()
def db_conn(tmp_path: Path):
    """Create an in-memory-like project DB for testing."""
    conn = get_project_db(tmp_path / "revolver.db")
    yield conn
    conn.close()


class TestProblemVersionCRUD:
    """Tests for insert/get/list problem version functions."""

    def test_insert_and_get_round_trip(self, db_conn) -> None:
        """Insert a problem version, then retrieve it by tag."""
        now = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)
        pv = ProblemVersion(
            tag="v1.0",
            hash="sha256:aabbccdd",
            message="First version",
            created_at=now,
        )
        insert_problem_version(db_conn, pv)
        result = get_problem_version(db_conn, "v1.0")
        assert result is not None
        assert result.tag == "v1.0"
        assert result.hash == "sha256:aabbccdd"
        assert result.message == "First version"
        assert result.created_at == now

    def test_duplicate_tag_raises(self, db_conn) -> None:
        """Inserting a duplicate tag raises DuplicateNameError."""
        now = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)
        pv1 = ProblemVersion(
            tag="v1.0",
            hash="sha256:aaa",
            created_at=now,
        )
        pv2 = ProblemVersion(
            tag="v1.0",
            hash="sha256:bbb",
            created_at=now,
        )
        insert_problem_version(db_conn, pv1)
        with pytest.raises(DuplicateNameError, match=r"Problem version conflict"):
            insert_problem_version(db_conn, pv2)

    def test_list_ascending_order(self, db_conn) -> None:
        """list_problem_versions returns versions in ascending created_at order."""
        t1 = datetime(2026, 1, 1, tzinfo=UTC)
        t2 = datetime(2026, 2, 1, tzinfo=UTC)
        t3 = datetime(2026, 3, 1, tzinfo=UTC)
        # Insert out of order
        insert_problem_version(
            db_conn,
            ProblemVersion(tag="v2", hash="sha256:bbb", created_at=t2),
        )
        insert_problem_version(
            db_conn,
            ProblemVersion(tag="v3", hash="sha256:ccc", created_at=t3),
        )
        insert_problem_version(
            db_conn,
            ProblemVersion(tag="v1", hash="sha256:aaa", created_at=t1),
        )
        versions = list_problem_versions(db_conn)
        assert len(versions) == 3
        assert versions[0].tag == "v1"
        assert versions[1].tag == "v2"
        assert versions[2].tag == "v3"

    def test_get_nonexistent_returns_none(self, db_conn) -> None:
        """Getting a non-existent tag returns None."""
        result = get_problem_version(db_conn, "nonexistent")
        assert result is None

    def test_get_by_hash_found(self, db_conn) -> None:
        """Retrieve a version by its content hash."""
        now = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)
        pv = ProblemVersion(tag="v1.0", hash="sha256:aabbccdd", message="First", created_at=now)
        insert_problem_version(db_conn, pv)
        result = get_problem_version_by_hash(db_conn, "sha256:aabbccdd")
        assert result is not None
        assert result.tag == "v1.0"
        assert result.hash == "sha256:aabbccdd"

    def test_get_by_hash_not_found(self, db_conn) -> None:
        """Querying a non-existent hash returns None."""
        result = get_problem_version_by_hash(db_conn, "sha256:nonexistent")
        assert result is None
