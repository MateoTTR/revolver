# Security policy

Revolver is a local command-line tool. This policy says which versions receive
security fixes, how to report a vulnerability privately, and what is in scope.

## Supported versions

Revolver is pre-1.0. Only the **latest minor release** (the most recent
`v0.Y.Z` tag on `main`, see [CHANGELOG.md](CHANGELOG.md)) receives security
fixes, shipped as a patch release through the hotfix procedure of
[docs/process/release.md](docs/process/release.md). Older minors are not
patched; upgrade to the latest release first and check whether the problem is
still present.

| Version | Supported |
|---|---|
| Latest minor release (`v0.Y.*`) | Yes — fixes ship as a patch release |
| Earlier releases | No — please upgrade |
| `develop` branch | Best effort; fixes land there first |

## Reporting a vulnerability

**Do not open a public issue or pull request for a vulnerability.**

Report it through **GitHub private vulnerability reporting** on this
repository ("Security" tab → "Report a vulnerability"), which opens a private
advisory visible only to you and the maintainer. The feature is enabled when
the repository becomes public; until then, contact the maintainer with a
private message on GitHub and ask for a private channel before sharing any
detail. No e-mail address is published for this project.

Please include: the affected version (the output of `revolver --version`), the
backend in use if relevant, the command or configuration that triggers the
problem, the impact you see, and a minimal reproduction when you have one.

What to expect: an acknowledgement within a few days, a shared assessment of
the impact and of the supported versions affected, a fix released as a patch
of the latest minor release with a `### Fixed` line in `CHANGELOG.md`, and
credit in the advisory unless you prefer to stay anonymous. The advisory is
published once the fix is released.

## Scope

Revolver runs as a **local CLI** on the user's machine. It exposes **no
network service** of its own: it reads and writes a local project directory
and a local SQLite store, and it connects outward to the LLM endpoints the user
registers (a local Ollama host or a remote API) and to the evolution backend
installed in the same Python environment.

In scope:

- Code under `src/revolver/` and the packaging in `pyproject.toml`: command
  injection, unsafe deserialization, path traversal, secrets leaking into
  files, logs or the database, unsafe handling of evaluator and program code
  beyond what the user explicitly runs.
- The CI workflows under `.github/workflows/`.

Out of scope, or the user's responsibility:

- **API keys and endpoints**: Revolver stores only the *name* of the
  environment variable that holds a key, never the key itself; keeping keys,
  local endpoints and network Ollama hosts secure is the user's job.
- **User-supplied programs and evaluators**: evolution runs and evaluations
  execute the user's own code (and LLM-generated variants of it) in local
  subprocesses, by design; sandboxing that code is outside Revolver's scope.
- **Third-party components**: the evolution engines (OpenEvolve,
  ShinkaEvolve), Ollama, the LLM providers and the Python dependencies.
  Report those upstream; a dependency update needed on Revolver's side is
  welcome as an issue or a pull request (Dependabot proposes updates weekly).

## Public-file rule

Everything in this repository, its issues and its pull requests is public.
Keep reports free of local paths, hostnames, private repository names and
e-mail addresses ([docs/process/README.md](docs/process/README.md#public-file-rule));
the private advisory is the place for sensitive detail.
