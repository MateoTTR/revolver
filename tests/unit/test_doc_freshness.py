"""Doc freshness check — guides carry a ``verified-against`` stamp within 1 minor.

S18-23 / backlog #355: every guide/tutorial file — ``docs/guides/*.md``
**plus** ``docs/specs/user-story-e2e.md`` (the E2E walkthrough lives under
``docs/specs/``, so a ``docs/guides`` glob alone would miss it) — must open
with a YAML front-matter block carrying a ``verified-against: vX.Y.Z`` stamp,
recording the last release the doc was verified against.

Lag rule (same-major minor arithmetic): the stamp may trail
``revolver.__version__`` by at most ONE minor version. At a current 0.18.x,
``v0.18.*`` and ``v0.17.*`` stamps pass and ``v0.16.*`` fails; a stamp from an
older major always fails, a stamp ahead of the current version never does
(stamps may be refreshed just before the release bump lands). Refreshing the
stamps is part of the Release Checklist step 1b in ``CLAUDE.md``.

This module runs in the main CI test job (``unit`` marker) and in the
docs-only ``doc-lint.yml`` workflow, so a stale guide blocks docs-only PRs
too.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

import revolver

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

STAMP_KEY = "verified-against"

# YAML front-matter: the file must START with `---` and close it with `---`.
_FRONT_MATTER_RE = re.compile(
    r"\A---[ \t]*\n(?P<body>.*?)^---[ \t]*(?:\n|\Z)", re.DOTALL | re.MULTILINE
)
_STAMP_RE = re.compile(rf"^{STAMP_KEY}:\s*v(\d+)\.(\d+)\.\d+\s*$", re.MULTILINE)
_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.")


def scanned_files() -> list[Path]:
    """The freshness corpus: every guide plus the specs-side E2E walkthrough."""
    guides = sorted((REPO_ROOT / "docs" / "guides").glob("*.md"))
    return [*guides, REPO_ROOT / "docs" / "specs" / "user-story-e2e.md"]


def read_stamp(text: str) -> tuple[int, int] | None:
    """Return the ``(major, minor)`` of the front-matter stamp, or ``None``.

    ``None`` means either no front-matter block at the very top of the file
    or a block without a well-formed ``verified-against: vX.Y.Z`` entry.
    """
    front_matter = _FRONT_MATTER_RE.match(text)
    if front_matter is None:
        return None
    stamp = _STAMP_RE.search(front_matter.group("body"))
    if stamp is None:
        return None
    return int(stamp.group(1)), int(stamp.group(2))


def check_freshness(text: str, current_version: str, name: str) -> str | None:
    """Check *text* against *current_version*; return an error message or ``None``.

    The message names the offending file and the refresh expected, so the CI
    failure is self-explanatory.
    """
    version = _VERSION_RE.match(current_version)
    if version is None:  # pragma: no cover - revolver.__version__ is well-formed
        raise ValueError(f"unparseable current version: {current_version!r}")
    current = int(version.group(1)), int(version.group(2))
    stamp = read_stamp(text)
    if stamp is None:
        return (
            f"{name}: missing `{STAMP_KEY}: vX.Y.Z` YAML front-matter stamp — verify the "
            f"doc against revolver {current_version} and stamp it (CLAUDE.md Release "
            "Checklist step 1b)"
        )
    if stamp[0] > current[0]:
        return None  # stamped ahead of the current major: never stale
    behind_major = stamp[0] < current[0]
    if behind_major or current[1] - stamp[1] > 1:
        return (
            f"{name}: stamp `{STAMP_KEY}: v{stamp[0]}.{stamp[1]}.x` is more than one minor "
            f"version behind revolver {current_version} — re-verify the doc against the "
            f"current release and refresh the stamp to v{current[0]}.{current[1]}.z"
        )
    return None


# ── Real corpus ───────────────────────────────────────────────────────────────


class TestDocFreshnessCorpus:
    def test_specs_side_walkthrough_is_in_the_scan(self) -> None:
        # Guard the "not docs/guides/* alone" requirement: the E2E walkthrough
        # sits under docs/specs/ and must be explicitly included.
        files = scanned_files()
        assert REPO_ROOT / "docs" / "specs" / "user-story-e2e.md" in files
        relative = {path.relative_to(REPO_ROOT).as_posix() for path in files}
        assert "docs/guides/initial-program-structure.md" in relative
        assert "docs/guides/tuning-evolution.md" in relative

    def test_corpus_is_stamped_and_fresh(self) -> None:
        failures = [
            error
            for path in scanned_files()
            for error in [
                check_freshness(
                    path.read_text(encoding="utf-8"),
                    revolver.__version__,
                    path.relative_to(REPO_ROOT).as_posix(),
                )
            ]
            if error is not None
        ]
        assert not failures, "doc freshness failures:\n" + "\n".join(failures)

    def test_corpus_stays_fresh_after_next_minor_bump(self) -> None:
        # Acceptance guard (#255): the stamps written today must still pass
        # after the upcoming v0.18.0 bump (one-minor grace), so the release
        # itself is never blocked by its own version bump.
        version = _VERSION_RE.match(revolver.__version__)
        assert version is not None
        next_minor = f"{version.group(1)}.{int(version.group(2)) + 1}.0"
        for path in scanned_files():
            name = path.relative_to(REPO_ROOT).as_posix()
            assert check_freshness(path.read_text(encoding="utf-8"), next_minor, name) is None


# ── Checker unit cases ────────────────────────────────────────────────────────

_STAMPED = "---\nverified-against: {stamp}\n---\n\n# Guide\n\nBody.\n"


class TestFreshnessChecker:
    def test_stamped_current_passes(self) -> None:
        assert check_freshness(_STAMPED.format(stamp="v0.17.1"), "0.17.1", "doc.md") is None

    def test_stamped_one_minor_behind_passes(self) -> None:
        assert check_freshness(_STAMPED.format(stamp="v0.17.1"), "0.18.0", "doc.md") is None

    def test_stamped_two_minors_behind_fails(self) -> None:
        error = check_freshness(_STAMPED.format(stamp="v0.16.0"), "0.18.0", "doc.md")
        assert error is not None
        assert "doc.md" in error and "v0.16.x" in error and "0.18.0" in error
        assert "refresh the stamp to v0.18.z" in error

    def test_stamped_older_major_fails(self) -> None:
        error = check_freshness(_STAMPED.format(stamp="v0.17.1"), "1.0.0", "doc.md")
        assert error is not None and "behind" in error

    def test_stamped_ahead_passes(self) -> None:
        # Stamps refreshed just before the bump lands must not fail.
        assert check_freshness(_STAMPED.format(stamp="v0.18.0"), "0.17.1", "doc.md") is None
        assert check_freshness(_STAMPED.format(stamp="v1.0.0"), "0.17.1", "doc.md") is None

    def test_missing_front_matter_fails(self) -> None:
        error = check_freshness("# Guide\n\nBody.\n", "0.17.1", "doc.md")
        assert error is not None
        assert "doc.md" in error and STAMP_KEY in error and "0.17.1" in error

    def test_front_matter_without_stamp_key_fails(self) -> None:
        text = "---\ntitle: Guide\n---\n\n# Guide\n"
        error = check_freshness(text, "0.17.1", "doc.md")
        assert error is not None and STAMP_KEY in error

    def test_front_matter_not_at_top_fails(self) -> None:
        # A `---` thematic break later in the doc is not front-matter.
        text = "# Guide\n\n---\nverified-against: v0.17.1\n---\n"
        assert read_stamp(text) is None

    def test_malformed_stamp_value_fails(self) -> None:
        # Missing `v` prefix or truncated version: not a well-formed stamp.
        assert read_stamp(_STAMPED.format(stamp="0.17.1")) is None
        assert read_stamp(_STAMPED.format(stamp="v0.17")) is None

    def test_read_stamp_parses_major_minor(self) -> None:
        assert read_stamp(_STAMPED.format(stamp="v0.17.1")) == (0, 17)
