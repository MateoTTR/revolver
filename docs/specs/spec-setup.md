# Spec: revolver doctor / setup

**Traceable to**: NFR-060 to NFR-068
**Status**: Draft

---

## 1. Scope

This spec covers dependency verification and assisted installation. Revolver depends on Python packages, conda-installable binaries, and system-level tools. These commands help users diagnose and resolve missing dependencies.

### Installation Strategy

Revolver supports two installation methods:

1. **pip/uv** (Python packages only): `pip install revolver` — installs Revolver and its Python dependencies. Non-Python dependencies (Ollama) must be installed separately.
2. **conda + pip** (recommended): conda provides the environment with Ollama and CUDA runtime; pip/uv installs Revolver inside that environment.

`revolver setup` can install Ollama via conda-forge if conda/mamba is available in the active environment. This is the only method that installs Ollama **without root**.

### Dependency Classification

| Dependency | Type | Managed by `setup` | Install method | Required for |
|---|---|---|---|---|
| Python CLI framework | Python | Yes (auto, via pip) | pip | All commands |
| PyYAML / SQLite driver | Python | Yes (auto, via pip) | pip | All commands |
| OpenEvolve | Python | Yes (via `setup`) | pip | `revolver run`, `revolver eval` |
| Ollama | Binary | Yes, if conda available | conda-forge | Local LLM commands |
| nvidia-smi / GPU drivers | System | No — detect and report | Manual | Local LLM inference, VRAM monitoring |

---

## 2. Commands

### 2.1 `revolver doctor`

Check the health of all dependencies.

**Options**:

| Option | Type | Default | Description |
|---|---|---|---|
| `--fix` | flag | false | Alias for `revolver setup` — attempt to fix Python-installable issues |

**Behavior**:
1. Check Revolver's own Python package dependencies
2. Check OpenEvolve: importable and version
3. Check Ollama: binary present, service running, API reachable
4. Check GPU: nvidia-smi available, driver version, GPU detected
5. Report each dependency with status: `OK`, `WARN`, or `FAIL`

**Output** (human):
```
Revolver dependency check:

  Python packages:
    ✓ revolver         0.1.0
    ✓ pyyaml           6.0.1
    ✓ openevolve       0.2.0

  External tools:
    ✓ ollama           0.6.2      running (http://localhost:11434)
    ✓ nvidia-smi       560.35     GPU: RTX 5090 (32 GB)

All checks passed.
```

**Output** (human, with issues):
```
Revolver dependency check:

  Python packages:
    ✓ revolver         0.1.0
    ✓ pyyaml           6.0.1
    ✗ openevolve       not installed
      → Run `revolver setup` to install it

  External tools:
    ✗ ollama           not found
      → Run `revolver setup` to install via conda-forge (conda detected)
      → Or install manually: https://ollama.com/download
    ⚠ nvidia-smi       not found
      → Install NVIDIA drivers for GPU support. Local LLM inference requires a compatible GPU.
      → Remote-only workflows will still work without GPU.

2 errors, 1 warning. Run `revolver setup` to fix installable issues.
```

**Output** (JSON):
```json
{
  "status": "fail",
  "checks": [
    {"name": "revolver", "type": "python", "status": "ok", "version": "0.1.0"},
    {"name": "openevolve", "type": "python", "status": "fail", "error": "not installed", "fixable": true},
    {"name": "ollama", "type": "external", "status": "ok", "version": "0.6.2", "url": "http://localhost:11434"},
    {"name": "nvidia-smi", "type": "system", "status": "warn", "error": "not found", "fixable": false}
  ],
  "errors": 1,
  "warnings": 1
}
```

**Exit codes**: 0 all OK, 1 if any check fails (FAIL, not WARN)

### 2.2 `revolver setup`

Install or upgrade missing Python-installable dependencies.

**Options**:

| Option | Type | Default | Description |
|---|---|---|---|
| `--dry-run` | flag | false | Show what would be installed without making changes |
| `--force` | flag | false | Reinstall even if already present |

**Behavior**:
1. Run the same checks as `revolver doctor`
2. Detect available package managers: pip (always), conda/mamba (if in active environment)
3. For each fixable issue: propose installation with version and install method
4. Ask user confirmation (unless `--quiet`)
5. Install Python packages via pip, Ollama via conda/mamba (if available)
6. Re-run checks to verify

**Output** (human, conda available):
```
The following will be installed:
  openevolve    (latest)    via pip
  ollama        (latest)    via conda-forge

Proceed? [Y/n] y

Installing openevolve via pip... done (0.2.0)
Installing ollama via conda... done (0.17.5)

All dependencies are now satisfied.
```

**Output** (human, conda not available):
```
The following will be installed:
  openevolve    (latest)    via pip

Not auto-installable (no conda detected):
  ollama        → Install manually: https://ollama.com/download
                  Or activate a conda environment and re-run `revolver setup`

Proceed? [Y/n] y

Installing openevolve via pip... done (0.2.0)

1 dependency requires manual installation. See above.
```

**Output** (human, `--dry-run`):
```
The following would be installed:
  openevolve    (latest)    via pip
  ollama        (latest)    via conda-forge

No changes made (dry run).
```

**Exit codes**: 0 success, 1 if installation fails, 0 if nothing to do

---

## 3. Functional Requirements

| ID | Priority | Requirement | NFR Ref |
|---|---|---|---|
| FR-SET-001 | MUST | `doctor` checks all Python package dependencies are importable | NFR-063 |
| FR-SET-002 | MUST | `doctor` checks OpenEvolve is installed and reports its version | NFR-063 |
| FR-SET-003 | MUST | `doctor` checks Ollama binary presence, service status, and API reachability | NFR-063 |
| FR-SET-004 | MUST | `doctor` checks nvidia-smi availability and reports GPU info | NFR-063 |
| FR-SET-005 | MUST | `doctor` reports each dependency with OK/WARN/FAIL status and actionable message | NFR-066 |
| FR-SET-006 | MUST | `doctor` distinguishes fixable (Python) from non-fixable (system) issues | NFR-062 |
| FR-SET-007 | MUST | `setup` installs missing Python-installable dependencies via pip | NFR-064 |
| FR-SET-008 | MUST | `setup` asks for user confirmation before installing | NFR-064 |
| FR-SET-009 | MUST | `setup` never installs system-level software (GPU drivers, OS packages) directly | NFR-065 |
| FR-SET-010 | MUST | `setup` provides instructions for non-fixable dependencies (URLs, install commands) | NFR-065 |
| FR-SET-011 | SHOULD | `setup --dry-run` previews changes without installing | NFR-068 |
| FR-SET-012 | SHOULD | `doctor` works outside of a Revolver project (global health check) | — |
| FR-SET-013 | SHOULD | `doctor` and `setup` report versions of installed dependencies | NFR-066 |
| FR-SET-014 | SHOULD | `setup` detects if conda/mamba is available in the active environment | NFR-064 |
| FR-SET-015 | SHOULD | `setup` installs Ollama via `conda install conda-forge::ollama` when conda is available and Ollama is missing | NFR-064 |
| FR-SET-016 | SHOULD | `setup` reports the install method (pip or conda) for each dependency it proposes to install | NFR-066 |
| FR-SET-017 | SHOULD | When conda is not available and Ollama is missing, `setup` reports manual install instructions and suggests activating a conda environment | NFR-065 |

---

## 4. Error Cases

| Trigger | Behavior | Exit Code |
|---|---|---|
| Ollama not installed (conda available) | FAIL: "Ollama not found. Run `revolver setup` to install via conda-forge." | 1 |
| Ollama not installed (no conda) | WARN: "Ollama not found. Install from https://ollama.com or activate a conda environment and run `revolver setup`." | 0 (warn only) |
| Ollama installed but not running | WARN: "Ollama installed but not running. Start with `ollama serve`." | 0 (warn only) |
| conda install fails | Error: "Failed to install ollama via conda: \<error\>" | 1 |
| nvidia-smi not found | WARN: "nvidia-smi not found. GPU monitoring unavailable. Install NVIDIA drivers for local LLM inference." | 0 (warn only) |
| OpenEvolve not installed | FAIL: "OpenEvolve not installed. Run `revolver setup` to install." | 1 |
| pip install fails | Error: "Failed to install <package>: <error>" | 1 |
| No network access during `setup` | Error: "Cannot reach PyPI. Check your network connection." | 1 |

---

## 5. Dependencies

- `doctor` and `setup` have no project dependency — they work globally.
- `setup` requires network access to download packages from PyPI and/or conda-forge.
- `setup` uses conda/mamba only if detected in the active environment — it never installs conda itself.
