"""CLI commands for ``revolver dataset``.

Registers commands on the ``dataset_app`` Typer instance from
``revolver.cli``.

Traceable to: DES-004 section 8, FR-DAT-001..016.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from revolver.cli import dataset_app
from revolver.cli.error_handler import cli_error_boundary
from revolver.core import dataset as core_dataset
from revolver.infra.output import print_confirmation, render


@dataset_app.command("add")
def dataset_add(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Unique name for this dataset.")],
    path: Annotated[
        Path,
        typer.Option("--path", help="Path to the dataset directory."),
    ],
    split: Annotated[
        str | None,
        typer.Option(
            "--split",
            help="Dataset split: 'train', 'eval', or 'both' (usable for both).",
        ),
    ] = None,
    snapshot: Annotated[
        bool,
        typer.Option("--snapshot", help="Copy files into .revolver/datasets/<name>/snapshot/."),
    ] = False,
    compatible_with: Annotated[
        list[str] | None,
        typer.Option(
            "--compatible-with",
            help="Problem version tag(s) this dataset is compatible with.",
        ),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", help="Short description for the dataset."),
    ] = None,
) -> None:
    """Register a new dataset from a directory of instances."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        # Progress indicator for large dataset registration (NFR-005)
        use_progress = not json_mode and not quiet
        if use_progress:
            from rich.console import Console

            stderr_console = Console(stderr=True)
            with stderr_console.status("Registering dataset (computing hashes)..."):
                registration = core_dataset.register_dataset(
                    project_root=None,
                    name=name,
                    path=path,
                    split=split,
                    snapshot=snapshot,
                    compatible_with=compatible_with,
                    description=description,
                )
        else:
            registration = core_dataset.register_dataset(
                project_root=None,
                name=name,
                path=path,
                split=split,
                snapshot=snapshot,
                compatible_with=compatible_with,
                description=description,
            )

        if json_mode:
            render(
                registration.model_dump(mode="json"),
                json_mode=True,
            )
        else:
            render(
                {
                    "status": "registered",
                    "name": registration.name,
                    "path": registration.path,
                    "storage": registration.storage,
                    "split": registration.split or "",
                    "instance_count": registration.instance_count,
                    "global_hash": registration.global_hash,
                },
                json_mode=False,
            )
            count = registration.instance_count
            print_confirmation(
                f"Done: Dataset '{registration.name}' registered ({count} instances)",
                json_mode=json_mode,
                quiet=quiet,
            )


@dataset_app.command("update")
def dataset_update(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Dataset name to update.")],
    add_compatible_with: Annotated[
        list[str] | None,
        typer.Option("--add-compatible-with", help="Problem version tag(s) to add."),
    ] = None,
    remove_compatible_with: Annotated[
        list[str] | None,
        typer.Option("--remove-compatible-with", help="Problem version tag(s) to remove."),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", help="New description for the dataset."),
    ] = None,
) -> None:
    """Update mutable dataset metadata (compatibility, description)."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        updated = core_dataset.update_dataset(
            project_root=None,
            name=name,
            add_compat=add_compatible_with,
            remove_compat=remove_compatible_with,
            description=description,
        )

        if json_mode:
            render(
                updated.model_dump(mode="json"),
                json_mode=True,
            )
        else:
            render(
                {
                    "status": "updated",
                    "name": updated.name,
                    "description": updated.description or "",
                },
                json_mode=False,
            )
            print_confirmation(
                f"Done: Dataset '{updated.name}' updated",
                json_mode=json_mode,
                quiet=quiet,
            )


@dataset_app.command("remove")
def dataset_remove(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Dataset name to remove.")],
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Skip confirmation prompt and remove even if referenced by solutions.",
        ),
    ] = False,
) -> None:
    """Remove a registered dataset."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False
        quiet: bool = ctx.obj.get("quiet", False) if ctx.obj else False

        # Confirmation logic: require --force in JSON mode, prompt interactively otherwise
        if not force:
            if json_mode:
                from revolver.core.exceptions import ValidationError

                raise ValidationError("Use --force to remove in JSON mode (no interactive prompt)")
            typer.confirm(f"Remove dataset '{name}'?", abort=True)

        core_dataset.remove_dataset(
            project_root=None,
            name=name,
            force=force,
        )

        if json_mode:
            render({"name": name, "removed": True}, json_mode=True)
        else:
            render({"status": "removed", "name": name}, json_mode=False)
            print_confirmation(
                f"Done: Dataset '{name}' removed",
                json_mode=json_mode,
                quiet=quiet,
            )


@dataset_app.command("list")
def dataset_list(
    ctx: typer.Context,
) -> None:
    """List all registered datasets."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        summaries = core_dataset.list_datasets()

        if json_mode:
            render(
                [s.model_dump(mode="json") for s in summaries],
                json_mode=True,
            )
        else:
            if not summaries:
                render({"message": "No datasets registered."}, json_mode=False)
            else:
                rows = [
                    {
                        "name": s.name,
                        "split": s.split or "",
                        "instance_count": s.instance_count,
                        "storage": s.storage,
                        "created_at": str(s.created_at),
                    }
                    for s in summaries
                ]
                render(rows, json_mode=False)


@dataset_app.command("info")
def dataset_info(
    ctx: typer.Context,
    name: Annotated[str, typer.Argument(help="Dataset name to inspect.")],
    verify: Annotated[
        bool,
        typer.Option("--verify", help="Recompute and verify instance hashes."),
    ] = False,
) -> None:
    """Show detailed dataset information with optional integrity check."""
    with cli_error_boundary():
        json_mode: bool = ctx.obj.get("json", False) if ctx.obj else False

        info = core_dataset.get_dataset_info(
            project_root=None,
            name=name,
            verify=verify,
        )

        if json_mode:
            render(
                info.model_dump(mode="json"),
                json_mode=True,
            )
        else:
            reg = info.registration
            render(
                {
                    "name": reg.name,
                    "path": reg.path,
                    "storage": reg.storage,
                    "split": reg.split or "",
                    "instance_count": reg.instance_count,
                    "global_hash": reg.global_hash,
                    "created_at": str(reg.created_at),
                    "description": reg.description or "",
                    "compatible_with": (
                        ", ".join(info.compat_versions) if info.compat_versions else ""
                    ),
                },
                json_mode=False,
            )

            if info.integrity is not None:
                integrity_data: dict[str, object] = {
                    "integrity_valid": info.integrity.is_valid,
                    "checked_at": str(info.integrity.checked_at),
                }
                if info.integrity.mismatches:
                    integrity_data["mismatches"] = ", ".join(
                        m.filename for m in info.integrity.mismatches
                    )
                if info.integrity.missing:
                    integrity_data["missing"] = ", ".join(info.integrity.missing)
                if info.integrity.extra:
                    integrity_data["extra"] = ", ".join(info.integrity.extra)
                render(integrity_data, json_mode=False)
