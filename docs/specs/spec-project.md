# Spec: revolver project

**Traceable to**: ConOps §4.1 (Project), §5.2 (Workflow: Create a Project)
**Status**: Draft

---

## 1. Scope

This spec covers project initialization and the project-level data model. A project is the top-level organizational unit in Revolver — all problems, datasets, solutions, and benchmarks live within a project.

**Key constraint**: A project contains exactly **one problem** (with multiple versions). Different optimization problems require separate projects. This simplifies dataset compatibility tracking, solution lineage, and benchmarking.

---

## 2. Commands

### 2.1 `revolver project init [name]`

Initialize a new Revolver project.

**Arguments**:

| Argument | Required | Description |
|---|---|---|
| `name` | No | Project name. Defaults to current directory name. |

**Options**:

| Option | Type | Default | Description |
|---|---|---|---|
| `--path <dir>` | string | `.` | Directory to initialize. Created if it does not exist. |
| `--description <text>` | string | `""` | Short project description |

**Output** (human):
```
Project "scheduling-optimizer" initialized in ./scheduling-optimizer/
Created: .revolver/, initial_program.py, evaluator.py, config.yaml, project.yaml
```

**Output** (JSON):
```json
{
  "project": "scheduling-optimizer",
  "path": "/absolute/path/to/scheduling-optimizer",
  "files_created": [".revolver/", "initial_program.py", "evaluator.py", "config.yaml", "project.yaml"]
}
```

**Exit codes**: 0 success, 1 if directory already contains `.revolver/`

---

## 3. Functional Requirements

| ID | Priority | Requirement | ConOps Ref |
|---|---|---|---|
| FR-PRJ-001 | MUST | Create a `.revolver/` directory with an empty SQLite database (`revolver.db`) and subdirectories (`problem/`, `datasets/`, `solutions/`, `benchmarks/`) | §4.1 |
| FR-PRJ-002 | MUST | Generate a `project.yaml` file with project name, description, and creation timestamp | §4.1 |
| FR-PRJ-003 | MUST | Generate a template `initial_program.py` with `EVOLVE-BLOCK` markers and inline comments explaining the pattern | §4.2, Appendix A |
| FR-PRJ-004 | MUST | Generate a template `evaluator.py` implementing `evaluate_instance(program_path: str, instance_path: str)` with the correct 2-argument signature. The template includes only the per-instance function (recommended mode). Legacy aggregated mode (`evaluate(program_path)` with `REVOLVER_DATASET_DIR`) is documented in the template docstring as an opt-in for advanced users. | §4.4 |
| FR-PRJ-005 | MUST | Generate a template `config.yaml` with OpenEvolve defaults and comments | Appendix A |
| FR-PRJ-006 | MUST | Refuse to initialize if `.revolver/` already exists in the target directory (exit code 1 with clear error message) | — |
| FR-PRJ-007 | SHOULD | Support `--path <dir>` to create and initialize a new directory in one step | §5.2 |
| FR-PRJ-008 | SHOULD | Set `.revolver/` directory permissions to 700 (user-only) | NFR-051 |

---

## 4. Error Cases

| Trigger | Behavior | Exit Code |
|---|---|---|
| `.revolver/` already exists in target directory | Error: "Project already initialized in <path>. Use a different directory." | 1 |
| Target directory is not writable | Error: "Cannot write to <path>: permission denied" | 1 |
| No name provided and current directory is filesystem root | Error: "Cannot infer project name from root directory. Provide a name." | 1 |

---

## 5. Generated File Formats

### 5.1 `project.yaml`

```yaml
name: scheduling-optimizer
description: ""
created_at: "2026-03-10T14:30:00Z"
revolver_version: "0.1.0"
```

### 5.2 Template Files

Template files (`initial_program.py`, `evaluator.py`, `config.yaml`) contain working example code with inline documentation. They are functional as-is — the user can run `revolver problem test` on the templates to verify their setup before customizing.

---

## 6. Dependencies

- None (this is the first command in the workflow).
