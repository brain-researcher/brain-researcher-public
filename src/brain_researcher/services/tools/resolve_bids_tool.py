"""Tool for resolving BIDS dataset files.

Resolution strategy:
1) Fast path glob-based lookup for common BIDS layouts (cheap on mounted datasets).
2) Optional PyBIDS fallback for richer entity queries.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult


class ResolveBIDSArgs(BaseModel):
    """Arguments for BIDS dataset resolution."""

    bids_root: str = Field(description="BIDS dataset root directory")
    subject_id: str = Field(description="Subject identifier (without 'sub-' prefix)")
    session_id: str | None = Field(
        default=None, description="Session identifier (without 'ses-' prefix)"
    )
    datatype: str = Field(description="BIDS datatype (anat, func, dwi, ieeg, eeg, meg)")
    suffix: str = Field(description="BIDS suffix (T1w, bold, dwi, eeg, etc.)")
    task_id: str | None = Field(
        default=None, description="Task identifier (without 'task-' prefix)"
    )
    space: str | None = Field(
        default=None, description="Spatial reference (for derivatives)"
    )
    desc: str | None = Field(default=None, description="Description label")


class ResolveBIDSTool(NeuroToolWrapper):
    """Resolve BIDS dataset files with PyBIDS."""

    def get_tool_name(self) -> str:
        return "resolve_bids"

    def get_tool_description(self) -> str:
        return (
            "Query BIDS dataset to resolve file paths for a given subject and datatype."
        )

    def get_args_schema(self):
        return ResolveBIDSArgs

    @staticmethod
    def _normalize_entity(value: str | None, prefix: str) -> str:
        label = str(value).strip() if value else ""
        prefix_label = f"{prefix}-"
        if label.startswith(prefix_label):
            label = label[len(prefix_label) :]
        return label

    @staticmethod
    def _has_entity(filename: str, entity: str, value: str) -> bool:
        return f"{entity}-{value}" in filename.split("_")

    @staticmethod
    def _quick_resolve(args: ResolveBIDSArgs) -> list[str]:
        """Fast filesystem lookup without PyBIDS indexing."""
        bids_root = Path(args.bids_root)
        if not bids_root.exists():
            return []

        subject = ResolveBIDSTool._normalize_entity(args.subject_id, "sub")
        if not subject:
            return []
        subject_label = f"sub-{subject}"

        datatype = str(args.datatype).strip()
        suffix = str(args.suffix).strip()
        if not datatype or not suffix:
            return []

        session = ResolveBIDSTool._normalize_entity(args.session_id, "ses")
        session_label = f"ses-{session}" if session else ""
        task = ResolveBIDSTool._normalize_entity(args.task_id, "task")
        task_label = f"task-{task}" if task else ""

        # Prefer direct subject-level func dir, then session-level dirs.
        candidate_dirs: list[Path] = []
        subject_root = bids_root / subject_label
        direct_dir = subject_root / datatype
        if direct_dir.exists():
            candidate_dirs.append(direct_dir)

        if session_label:
            ses_dir = subject_root / session_label / datatype
            if ses_dir.exists():
                candidate_dirs.append(ses_dir)
        elif subject_root.exists():
            for ses_dir in sorted(subject_root.glob("ses-*")):
                subdir = ses_dir / datatype
                if subdir.exists():
                    candidate_dirs.append(subdir)

        matches: list[str] = []
        for directory in candidate_dirs:
            for file_path in sorted(directory.glob(f"{subject_label}*_{suffix}.nii*")):
                if not file_path.is_file():
                    continue
                if session_label and not ResolveBIDSTool._has_entity(
                    file_path.name, "ses", session
                ):
                    continue
                if task_label and not ResolveBIDSTool._has_entity(
                    file_path.name, "task", task
                ):
                    continue
                matches.append(str(file_path))

        return matches

    def _run(self, **kwargs) -> ToolResult:
        args = ResolveBIDSArgs(**kwargs)
        subject = self._normalize_entity(args.subject_id, "sub")
        session = self._normalize_entity(args.session_id, "ses")
        task = self._normalize_entity(args.task_id, "task")
        quick_matches = self._quick_resolve(args)
        if quick_matches:
            return ToolResult(
                status="success",
                data={
                    "outputs": {
                        "resolved_path": quick_matches[0],
                        "resolved_paths": quick_matches,
                        "metadata": {
                            "subject": subject,
                            "session": session or None,
                            "task": task or None,
                            "datatype": args.datatype,
                            "suffix": args.suffix,
                            "space": args.space,
                            "desc": args.desc,
                            "strategy": "glob",
                        },
                    },
                    "summary": {
                        "query_success": True,
                        "bids_root": args.bids_root,
                        "n_matches": len(quick_matches),
                    },
                },
            )

        try:
            from bids import BIDSLayout
        except Exception as exc:  # pragma: no cover - dependency missing
            return ToolResult(
                status="error",
                error=f"pybids required: {exc}",
                data={
                    "summary": {
                        "query_success": False,
                        "strategy": "glob+pybids",
                        "bids_root": args.bids_root,
                    }
                },
            )

        bids_root = Path(args.bids_root)
        derivatives_root = bids_root / "derivatives"
        has_derivatives = False
        if derivatives_root.exists():
            has_derivatives = any(
                path.name == "dataset_description.json"
                for path in derivatives_root.rglob("dataset_description.json")
            )
        layout = BIDSLayout(
            args.bids_root,
            validate=False,
            derivatives=has_derivatives,
        )
        filters = {
            "subject": subject,
            "datatype": args.datatype,
            "suffix": args.suffix,
            "extension": [".nii", ".nii.gz"],
        }
        if session:
            filters["session"] = session
        if task:
            filters["task"] = task
        if args.space:
            filters["space"] = args.space
        if args.desc:
            filters["desc"] = args.desc

        files = layout.get(
            return_type="file",
            invalid_filters="drop",
            **filters,
        )

        if not files:
            return ToolResult(
                status="error",
                error="No matching BIDS files found",
                data={
                    "summary": {
                        "query_success": False,
                        "bids_root": args.bids_root,
                        "subject": subject,
                        "session": session or None,
                        "task": task or None,
                        "datatype": args.datatype,
                        "suffix": args.suffix,
                        "space": args.space,
                        "desc": args.desc,
                    }
                },
            )

        resolved_path = files[0]
        return ToolResult(
            status="success",
            data={
                "outputs": {
                    "resolved_path": resolved_path,
                    "resolved_paths": files,
                    "metadata": {
                        "subject": subject,
                        "session": session or None,
                        "task": task or None,
                        "datatype": args.datatype,
                        "suffix": args.suffix,
                        "space": args.space,
                        "desc": args.desc,
                        "strategy": "pybids",
                    },
                },
                "summary": {
                    "query_success": True,
                    "bids_root": args.bids_root,
                    "n_matches": len(files),
                },
            },
        )


class ResolveBIDSTools:
    @staticmethod
    def get_all_tools():
        return [ResolveBIDSTool()]


__all__ = ["ResolveBIDSTool", "ResolveBIDSTools"]
