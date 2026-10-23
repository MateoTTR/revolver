"""Doc command-lint — fenced-block ``revolver`` invocations resolve in the CLI tree.

S18-21 / backlog row 354: every *line-initial* ``revolver`` invocation inside
a fenced code block of the documentation corpus (the root Markdown files
listed in :data:`ROOT_DOC_FILES` + ``docs/**``; ``CHANGELOG.md`` is excluded
because its entries quote historical flags — issue #279) must resolve
against the real Typer command tree (subcommands, flags,
positional-argument caps) via the shared walker
:mod:`revolver.cli._tree`.

Line grammar (deliberately narrow):

- only *line-initial* invocations inside a fence are linted — ``revolver ...``,
  ``$ revolver ...`` or ``> revolver ...`` (leading indentation allowed);
- **untagged** fences are parsed too (conops.md, DES-005/007 and several
  README blocks carry no language tag);
- inline-prose backtick mentions (e.g. a sentence quoting
  ``revolver solution extract ... --rank <N>``) are OUT of scope;
- label/diagram lines whose second token ends with ``:`` (DES-005's
  ``revolver eval:  .revolver/problem/...``) are not invocations;
- trailing ``\\`` continuations are joined (PS2 ``> `` prompts stripped);
- ``# ...`` comments and everything after an unquoted shell operator
  (``|``, ``&&``, ``>``, ``;`` ...) are ignored;
- ``<placeholder>`` tokens count as opaque values;
- prose guard: a line whose first token after ``revolver`` is neither a
  top-level command nor an option, that carries **no** flag-like token at
  all, AND that ends with sentence punctuation is treated as prose inside a
  fence (``revolver is a tool for evolving code.``) and skipped. All three
  conditions are required, so a renamed top-level group still fails: with a
  flag (``revolver problms test --instance x``) or without trailing
  punctuation (``revolver problms``) the line is linted. Trade-off: flagless
  prose that also lacks sentence punctuation, or prose starting with a real
  command name, is still flagged — none exists in the corpus today.
"""

from __future__ import annotations

from pathlib import Path
import re
import shlex
import subprocess

import pytest

from revolver.cli import _tree

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

# ── Known-rot baseline ────────────────────────────────────────────────────────
# (relative path, exact invocation) pairs that currently FAIL the lint but sit
# in files owned by another in-flight Sprint 018 PR, so this PR must not edit
# them. Burn each entry down in the owning PR and remove it here.
#
# Empty since PR-9 (#356) fixed the two `run --source local` invocations in
# the restructured tuning guide (docs/guides/tuning-evolution.md).
KNOWN_ROT: frozenset[tuple[str, str]] = frozenset()

# ── Fenced-block extraction ──────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
_INVOCATION_RE = re.compile(r"^\s*(?:\$\s+|>\s+)?(revolver(?:\s.*)?)$")
_PS2_PROMPT_RE = re.compile(r"^[$>]\s+")
_PLACEHOLDER_RE = re.compile(r"<[^<>\s]+>")
# Tokens made purely of shlex punctuation chars terminate the invocation
# (pipe, redirect, chaining); `2>` etc. also end with one of these.
_SHELL_OPERATOR_RE = re.compile(r"^[|&;<>()]+$|^\d+[<>]+$")


def iter_fenced_lines(text: str) -> list[tuple[int, str]]:
    """Return ``(lineno, line)`` for every line inside a fenced code block.

    Fences open on ```` ``` ```` or ``~~~`` (any info string, tagged or not)
    and close on a fence of the same character at least as long — so a
    ````` ````markdown ````` block embedding ```` ``` ```` fences is treated
    as a single outer block (CommonMark rule).
    """
    fenced: list[tuple[int, str]] = []
    fence_char: str | None = None
    fence_len = 0
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = _FENCE_RE.match(line)
        if match:
            marker, info = match.group(1), match.group(2).strip()
            if fence_char is None:
                # Opening fence: any info string (tagged or untagged).
                fence_char = marker[0]
                fence_len = len(marker)
                continue
            if marker[0] == fence_char and len(marker) >= fence_len and not info:
                # Closing fence: same char, at least as long, bare.
                fence_char = None
                continue
        if fence_char is not None:
            fenced.append((lineno, line))
    return fenced


def extract_invocations(text: str) -> list[tuple[int, str]]:
    """Extract ``(lineno, command)`` line-initial invocations from *text*.

    Applies the line grammar documented in the module docstring, joining
    trailing-backslash continuations into a single command string.
    """
    lines = iter_fenced_lines(text)
    invocations: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        lineno, line = lines[index]
        match = _INVOCATION_RE.match(line)
        if match:
            command = match.group(1).rstrip()
            while command.endswith("\\") and index + 1 < len(lines):
                index += 1
                continuation = _PS2_PROMPT_RE.sub("", lines[index][1].strip())
                command = f"{command[:-1].rstrip()} {continuation}".rstrip()
            invocations.append((lineno, command))
        index += 1
    return invocations


def tokenize_invocation(command: str) -> list[str] | None:
    """Shell-tokenize *command*, truncating at the first shell operator.

    ``<placeholder>`` spans are replaced by an opaque word first so they
    neither trip the tokenizer nor look like redirects. Returns ``None`` for
    lines that are not real invocations (label lines such as
    ``revolver eval:  ...``) or that fail to tokenize.
    """
    prepared = _PLACEHOLDER_RE.sub("PLACEHOLDER", command)
    lexer = shlex.shlex(prepared, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        raw_tokens = list(lexer)
    except ValueError:
        return None
    tokens: list[str] = []
    for token in raw_tokens:
        if _SHELL_OPERATOR_RE.match(token):
            break
        tokens.append(token)
    if len(tokens) >= 2 and tokens[1].endswith(":"):
        return None  # label/diagram line, not an invocation
    return tokens


_PROSE_PUNCTUATION = (".", "?", "!", ":", ";", ",")


def is_prose_line(command: str, tokens: list[str], root: object) -> bool:
    """Cheap guard for prose sentences starting with the word ``revolver``.

    See the module docstring: skips only when the first token neither starts
    with ``-`` nor resolves as a top-level command (slash families included),
    no token is flag-like, and the raw line ends with sentence punctuation.
    """
    if len(tokens) < 2:
        return False
    first = tokens[1]
    if first.startswith("-"):
        return False
    top_level = _tree.subcommands(root)
    if all(part in top_level for part in first.split("/")):
        return False
    if any(token.startswith("-") for token in tokens[1:]):
        return False
    return command.rstrip().endswith(_PROSE_PUNCTUATION)


# ── Corpus scan ───────────────────────────────────────────────────────────────


# Root-level Markdown files that belong to the corpus (issue #279). CHANGELOG.md
# is excluded on purpose: its entries quote flags as they were at each release
# and must never be rewritten to the current CLI surface. Every other root
# `*.md` must appear in one of the two collections — pinned by
# TestDocCommandLintCorpus.test_corpus_includes_contributor_docs.
ROOT_DOC_FILES: tuple[str, ...] = (
    "README.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODE_OF_CONDUCT.md",
    "CLAUDE.md",
    "GEMINI.md",
)
ROOT_DOC_EXCLUDED: frozenset[str] = frozenset({"CHANGELOG.md"})


def corpus_files() -> list[Path]:
    """The linted corpus: the root files of ``ROOT_DOC_FILES`` + every ``docs/**/*.md``."""
    root_docs = [REPO_ROOT / name for name in ROOT_DOC_FILES]
    return [*root_docs, *sorted((REPO_ROOT / "docs").rglob("*.md"))]


def tracked_root_markdown() -> list[str] | None:
    """Root-level ``*.md`` files tracked by version control, or ``None`` when unknown.

    A contributor's untracked scratch notes at the repository root must not
    fail the corpus pin, so the unclassified-file check reads the index rather
    than the directory listing. Returns ``None`` when ``git`` is unavailable or
    the tree is not a checkout (an sdist); the caller then skips that check.
    """
    try:
        listing = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "--", "*.md"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    # The pathspec `*.md` also matches nested paths; keep the root level only.
    return [line for line in listing.stdout.splitlines() if "/" not in line]


def lint_text(text: str, root: object = None) -> list[tuple[int, str, str]]:
    """Lint *text*, returning ``(lineno, command, error)`` findings."""
    if root is None:
        root = _tree.get_cli_root()
    findings: list[tuple[int, str, str]] = []
    for lineno, command in extract_invocations(text):
        tokens = tokenize_invocation(command)
        if not tokens or is_prose_line(command, tokens, root):
            continue
        error = _tree.validate_invocation(tokens, root)
        if error is not None:
            findings.append((lineno, command, error))
    return findings


class TestDocCommandLintCorpus:
    """The real documentation corpus passes the lint (modulo KNOWN_ROT)."""

    def test_corpus_invocations_resolve(self) -> None:
        root = _tree.get_cli_root()
        failures: list[str] = []
        stale_baseline = dict.fromkeys(KNOWN_ROT, True)
        for path in corpus_files():
            relative = path.relative_to(REPO_ROOT).as_posix()
            for lineno, command, error in lint_text(path.read_text(encoding="utf-8"), root):
                if (relative, command) in KNOWN_ROT:
                    stale_baseline[(relative, command)] = False
                    continue
                failures.append(f"{relative}:{lineno}: `{command}` -> {error}")
        assert not failures, "doc command-lint failures:\n" + "\n".join(failures)
        stale = [
            f"{path}: `{command}`" for (path, command), unused in stale_baseline.items() if unused
        ]
        assert not stale, (
            "KNOWN_ROT entries no longer present in the corpus (baseline is stale, "
            "remove them from tests/unit/test_doc_command_lint.py):\n" + "\n".join(stale)
        )

    def test_corpus_extracts_a_meaningful_number_of_invocations(self) -> None:
        # Guard against the extractor silently going blind (e.g. a fence-
        # parsing regression skipping untagged fences): the corpus contains
        # well over 100 fenced invocations today.
        total = sum(
            len(extract_invocations(path.read_text(encoding="utf-8"))) for path in corpus_files()
        )
        assert total >= 100, f"only {total} fenced invocations extracted from the corpus"

    def test_corpus_includes_contributor_docs(self) -> None:
        # Pin the corpus composition (issue #279): the contributor-facing root
        # files are linted, CHANGELOG.md (historical flags) is not, and every
        # *tracked* root-level Markdown file is classified one way or the other
        # (untracked local notes are not the repository's business).
        corpus = {path.relative_to(REPO_ROOT).as_posix() for path in corpus_files()}
        for name in ROOT_DOC_FILES:
            assert name in corpus, f"{name} missing from the doc command-lint corpus"
            assert (REPO_ROOT / name).is_file(), f"{name} listed in ROOT_DOC_FILES but absent"
        assert "CHANGELOG.md" not in corpus
        assert not set(ROOT_DOC_FILES) & ROOT_DOC_EXCLUDED
        assert all(name.startswith("docs/") for name in corpus - set(ROOT_DOC_FILES))
        tracked = tracked_root_markdown()
        if tracked is not None:  # a checkout with git available: the index is authoritative
            unclassified = sorted(
                name
                for name in tracked
                if name not in ROOT_DOC_FILES and name not in ROOT_DOC_EXCLUDED
            )
            assert not unclassified, (
                "tracked root-level Markdown files neither linted nor excluded (add them "
                "to ROOT_DOC_FILES or ROOT_DOC_EXCLUDED in "
                "tests/unit/test_doc_command_lint.py): " + ", ".join(unclassified)
            )


# ── Extraction grammar unit cases (S18-24) ───────────────────────────────────


class TestExtractionGrammar:
    def test_untagged_fence_is_parsed(self) -> None:
        text = "intro\n\n```\nrevolver llm list\n```\n"
        assert extract_invocations(text) == [(4, "revolver llm list")]

    def test_bash_tagged_fence_is_parsed(self) -> None:
        text = "```bash\nrevolver doctor\n```\n"
        assert extract_invocations(text) == [(2, "revolver doctor")]

    def test_dollar_and_gt_prompts_are_stripped(self) -> None:
        text = "```console\n$ revolver llm list\n> revolver run status\n```\n"
        assert [cmd for _, cmd in extract_invocations(text)] == [
            "revolver llm list",
            "revolver run status",
        ]

    def test_inline_prose_backtick_mention_is_ignored(self) -> None:
        text = (
            "Use `revolver solution extract --run <id> --rank <N>` to promote\n"
            "the Nth-best program.\n"
        )
        assert extract_invocations(text) == []

    def test_line_initial_only_mid_line_mentions_are_ignored(self) -> None:
        text = "```\necho see revolver llm list for details\n```\n"
        assert extract_invocations(text) == []

    def test_text_outside_fences_is_ignored(self) -> None:
        text = "revolver bogus command\n\n```\nrevolver llm list\n```\n"
        assert extract_invocations(text) == [(4, "revolver llm list")]

    def test_backslash_continuation_is_joined(self) -> None:
        text = "```bash\nrevolver run --version v1.0 \\\n  --llm claude\n```\n"
        assert extract_invocations(text) == [(2, "revolver run --version v1.0 --llm claude")]

    def test_ps2_prompt_on_continuation_line_is_stripped(self) -> None:
        text = "```console\n$ revolver run --version v1.0 \\\n>   --llm claude\n```\n"
        assert extract_invocations(text) == [(2, "revolver run --version v1.0 --llm claude")]

    def test_indented_invocation_in_fence_is_extracted(self) -> None:
        text = "- item\n\n  ```bash\n  revolver llm list\n  ```\n"
        assert extract_invocations(text) == [(4, "revolver llm list")]

    def test_comment_and_pipe_are_truncated(self) -> None:
        assert tokenize_invocation("revolver llm list  # inspect | not a pipe") == [
            "revolver",
            "llm",
            "list",
        ]
        assert tokenize_invocation("revolver run list --json | jq '.[]'") == [
            "revolver",
            "run",
            "list",
            "--json",
        ]

    def test_label_line_is_not_an_invocation(self) -> None:
        # DES-005's dispatch diagram: `revolver eval:  .revolver/problem/...`.
        assert tokenize_invocation("revolver eval:  .revolver/problem/<tag>/evaluator.py") is None

    def test_placeholders_are_opaque_values(self) -> None:
        tokens = tokenize_invocation("revolver eval --solution <solution-id> --dataset eval-set")
        assert tokens == [
            "revolver",
            "eval",
            "--solution",
            "PLACEHOLDER",
            "--dataset",
            "eval-set",
        ]

    def test_prose_sentence_in_fence_is_skipped(self) -> None:
        text = "```\nrevolver is a tool for evolving code.\n```\n"
        assert lint_text(text) == []

    def test_prose_guard_preserves_renamed_group_failures(self) -> None:
        # No trailing sentence punctuation -> still linted (renamed group).
        flagless = lint_text("```\nrevolver problms\n```\n")
        assert len(flagless) == 1 and "problms" in flagless[0][2]
        # Flag-like token present -> still linted even with punctuation.
        with_flag = lint_text("```\nrevolver problms test --instance x.\n```\n")
        assert len(with_flag) == 1 and "problms" in with_flag[0][2]
        # First token is a real top-level command -> guard never applies.
        real_group = lint_text("```\nrevolver problem versions.\n```\n")
        assert len(real_group) == 1 and "versions" in real_group[0][2]

    def test_embedded_markdown_fence_is_one_outer_block(self) -> None:
        text = "````markdown\n```bash\nrevolver llm list\n```\n````\n\n```\nrevolver doctor\n```\n"
        commands = [cmd for _, cmd in extract_invocations(text)]
        assert commands == ["revolver llm list", "revolver doctor"]


# ── Walker / validator unit cases (S18-24) ───────────────────────────────────


class TestCliTreeWalker:
    def test_walk_covers_all_top_level_groups(self) -> None:
        paths = {path for path, _ in _tree.walk_commands()}
        for group in (
            ("project",),
            ("llm",),
            ("problem",),
            ("dataset",),
            ("run",),
            ("solution",),
            ("eval",),
            ("benchmark",),
            ("doctor",),
            ("setup",),
        ):
            assert group in paths
        assert ("problem", "version", "create") in paths
        assert ("llm", "ensemble", "add") in paths

    def test_group_callback_params_are_exposed(self) -> None:
        # `run` and `eval` are invoke_without_command=True groups: their
        # launch flags live on the group callback, not on a subcommand.
        by_path = dict(_tree.walk_commands())
        run_options = _tree.option_table(by_path[("run",)], ("run",))
        assert "--llm" in run_options and run_options["--llm"] is True
        assert "--dry-run" in run_options and run_options["--dry-run"] is False
        eval_options = _tree.option_table(by_path[("eval",)], ("eval",))
        assert "--solution" in eval_options

    def test_universal_options_valid_at_any_level(self) -> None:
        by_path = dict(_tree.walk_commands())
        options = _tree.option_table(by_path[("llm", "list")], ("llm", "list"))
        for flag in ("--json", "--verbose", "--quiet", "--help"):
            assert flag in options and options[flag] is False
        assert options["--global-db"] is True

    def test_secondary_opts_resolve(self) -> None:
        assert (
            _tree.validate_invocation(shlex.split("revolver project init demo --no-templates"))
            is None
        )
        assert (
            _tree.validate_invocation(shlex.split("revolver llm add x -s local -m codestral:22b"))
            is None
        )


class TestInvocationValidation:
    def test_resolving_command_passes(self) -> None:
        for command in (
            "revolver llm list --json",
            "revolver run --version v1.0 --llm claude --dataset train --backend shinka",
            "revolver run resume --run PLACEHOLDER --iterations 50",
            "revolver benchmark --solutions a,b --dataset eval-set --alias base",
            "revolver --global-db /tmp/ci.db llm list",
        ):
            assert _tree.validate_invocation(shlex.split(command)) is None, command

    def test_renamed_or_removed_flag_is_caught(self) -> None:
        error = _tree.validate_invocation(shlex.split("revolver run --version v1.0 --lllm x"))
        assert error is not None and "--lllm" in error

    def test_unknown_subcommand_is_caught(self) -> None:
        error = _tree.validate_invocation(shlex.split("revolver problem versions"))
        assert error is not None and "versions" in error

    def test_flag_valid_elsewhere_is_caught_on_wrong_command(self) -> None:
        # `--source` belongs to `llm add`, not `run`.
        error = _tree.validate_invocation(shlex.split("revolver run --llm x --source local"))
        assert error is not None and "--source" in error

    def test_deprecated_tag_flag_does_not_false_positive(self) -> None:
        assert (
            _tree.validate_invocation(
                shlex.split('revolver problem version create --tag v1.0 -m "msg"')
            )
            is None
        )

    def test_deprecated_registry_covers_tag(self) -> None:
        assert _tree.DEPRECATED_FLAGS[("problem", "version", "create")] == {"--tag": True}

    def test_excess_positionals_are_caught(self) -> None:
        # `llm ensemble add` takes ONE positional (the ensemble name); the
        # member is passed via --llm.
        error = _tree.validate_invocation(
            shlex.split("revolver llm ensemble add my-ens claude --weight 0.7")
        )
        assert error is not None and "positional" in error

    def test_slash_shorthand_families_resolve(self) -> None:
        # README feature list style: every part must be a real subcommand.
        assert (
            _tree.validate_invocation(["revolver", "llm", "add/update/start/stop/remove"]) is None
        )
        assert _tree.validate_invocation(["revolver", "run/run", "resume"]) is None
        error = _tree.validate_invocation(["revolver", "llm", "add/updat/start"])
        assert error is not None

    def test_option_value_elided_before_another_flag_is_caught(self) -> None:
        # `--llm` swallows its value; a following *known* option means the
        # value was elided (`--llm --version v1.0`).
        error = _tree.validate_invocation(shlex.split("revolver run --llm --version v1.0"))
        assert error is not None and "--llm" in error and "--version" in error

    def test_dash_value_not_matching_an_option_is_still_a_value(self) -> None:
        # Unknown dash tokens (negative numbers, odd literals) stay values.
        assert _tree.validate_invocation(shlex.split("revolver run --iterations -1")) is None

    def test_missing_required_argument_is_tolerated(self) -> None:
        # Docs may elide required arguments (`revolver llm start` prose-style).
        assert _tree.validate_invocation(["revolver", "llm", "start"]) is None

    def test_synthetic_doc_end_to_end(self) -> None:
        good = "```bash\nrevolver problem version create v1.0 --tag v1.0\n```\n"
        assert lint_text(good) == []
        bad = "```bash\nrevolver problem version create v1.0 --tags v1.0\n```\n"
        findings = lint_text(bad)
        assert len(findings) == 1
        assert "--tags" in findings[0][2]
