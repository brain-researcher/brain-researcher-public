"""Hosted Studio assistant runtime.

This runtime binds the assistant-first Studio surface to a durable thread and a
typed notebook-planning contract. The UI talks to this runtime instead of
assembling planner prompts and parsing assistant JSON on the client.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import httpx
from pydantic import BaseModel, Field

from brain_researcher.config.paths import get_data_root

from .env import AGENT_URL
from .models import Message, Thread
from .sqlite_state_store import SqliteStateStore
from .studio_notebook_runtime import (
    StudioNotebook,
    StudioNotebookCellInput,
    StudioNotebookCellType,
    StudioNotebookDocumentInput,
    StudioNotebookOperation,
    StudioNotebookOperationType,
    StudioNotebookOpsRequest,
    StudioNotebookOutput,
    StudioNotebookRuntime,
)
from .studio_session_runtime import StudioSession, StudioSessionRuntime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _message_id() -> str:
    return f"msg_{secrets.token_urlsafe(9).replace('-', '').replace('_', '')}"


def _assistant_thread_id(session: StudioSession) -> str:
    suffix = session.assistant_session_id.removeprefix("ast_")
    cleaned = "".join(ch for ch in suffix if ch.isalnum()) or session.id.removeprefix(
        "studio_"
    )
    return f"thread_{cleaned}"


def _assistant_title_for_session(session: StudioSession) -> str:
    return f"{session.display_name} assistant"


def _truncate_text(value: str, max_length: int = 500) -> str:
    if len(value) <= max_length:
        return value
    return f"{value[:max_length]}..."


def _resolve_planner_timeout_seconds() -> float:
    raw = os.getenv("BR_STUDIO_ASSISTANT_PLANNER_TIMEOUT_SECONDS")
    if raw:
        try:
            return max(1.0, float(raw))
        except ValueError:
            pass
    return 20.0 if os.getenv("NODE_ENV") == "production" else 8.0


_T1_HINT_PATTERN = re.compile(r"\b(?:t1|t1w|anat|anatomical|structural)\b")
_NEURODESK_HINT_PATTERN = re.compile(
    r"\b(?:module\s+load|neurodesk|cat12|fsl|ants|mrtrix)\b"
)
_MODULE_LOAD_PATTERN = re.compile(r"module\s+load\s+([^\s;]+)")
_FMRI_QC_HINT_PATTERN = re.compile(
    r"\b(?:bold|fmri|fmriprep|confounds?|carpet|qc|quality control|motion)\b"
)
_GLM_HINT_PATTERN = re.compile(
    r"\b(?:glm|first[\s-]?level|design matrix|contrast|openneuro|events\.tsv|trial_type)\b"
)


def _prompt_mentions_t1_visualization(prompt: str) -> bool:
    lowered = prompt.lower()
    mentions_t1 = bool(_T1_HINT_PATTERN.search(lowered)) or any(
        token in prompt for token in ["结构像", "解剖像", "T1像", "T1 图像"]
    )
    mentions_visualization = any(
        token in lowered for token in ["visualiz", "plot", "view", "display", "show"]
    ) or any(token in prompt for token in ["可视化", "显示", "画图", "绘图"])
    mentions_notebook = any(
        token in lowered for token in ["notebook", "generate", "create", "draft"]
    ) or any(token in prompt for token in ["notebook", "生成", "创建", "草拟"])
    return mentions_t1 and (mentions_visualization or mentions_notebook)


def _prompt_mentions_neurodesk_module_execution(prompt: str) -> bool:
    lowered = prompt.lower()
    return bool(_NEURODESK_HINT_PATTERN.search(lowered)) or any(
        token in prompt for token in ["模块", "运行 CAT12", "运行 FSL", "Neurodesk"]
    )


def _extract_module_loads(prompt: str) -> list[str]:
    matches = [
        match.strip() for match in _MODULE_LOAD_PATTERN.findall(prompt) if match.strip()
    ]
    if matches:
        return matches
    lowered = prompt.lower()
    if "cat12" in lowered:
        return ["cat12/r2166"]
    if "mrtrix" in lowered:
        return ["mrtrix"]
    if "ants" in lowered:
        return ["ants"]
    if "fsl" in lowered:
        return ["fsl"]
    return []


def _prompt_mentions_fmri_qc(prompt: str) -> bool:
    lowered = prompt.lower()
    return bool(_FMRI_QC_HINT_PATTERN.search(lowered)) or any(
        token in prompt for token in ["地毯图", "混杂", "运动参数", "质量控制", "BOLD"]
    )


def _prompt_mentions_glm_scaffold(prompt: str) -> bool:
    lowered = prompt.lower()
    return bool(_GLM_HINT_PATTERN.search(lowered)) or any(
        token in prompt for token in ["设计矩阵", "对比", "一阶 GLM", "一阶模型"]
    )


def _infer_t1_visualization_markdown(prompt: str) -> str:
    request = prompt.strip() or "Visualize a T1-weighted MRI volume."
    return (
        "## T1 visualization notebook\n\n"
        f"- Request: {request}\n"
        "- Update the input path to a real T1w NIfTI file.\n"
        "- Run the code cell to render sagittal, coronal, and axial middle slices."
    )


def _infer_t1_visualization_code() -> str:
    return "\n".join(
        [
            "from pathlib import Path",
            "",
            "import matplotlib.pyplot as plt",
            "import nibabel as nib",
            "import numpy as np",
            "",
            "# Update this path to point at a real T1w image in your project.",
            "t1_path = Path('data/sub-01/anat/sub-01_T1w.nii.gz')",
            "img = nib.load(str(t1_path))",
            "data = np.asarray(img.get_fdata())",
            "",
            "if data.ndim != 3:",
            "    raise ValueError(f'Expected a 3D T1 image, got shape {data.shape}')",
            "",
            "mid = tuple(dim // 2 for dim in data.shape)",
            "views = [",
            "    ('sagittal', data[mid[0], :, :]),",
            "    ('coronal', data[:, mid[1], :]),",
            "    ('axial', data[:, :, mid[2]]),",
            "]",
            "",
            "fig, axes = plt.subplots(1, 3, figsize=(12, 4))",
            "for ax, (title, view) in zip(axes, views):",
            "    ax.imshow(np.rot90(view), cmap='gray')",
            "    ax.set_title(title)",
            "    ax.axis('off')",
            "",
            "fig.suptitle(t1_path.name)",
            "fig.tight_layout()",
            "plt.show()",
        ]
    )


def _infer_neurodesk_markdown(prompt: str, module_loads: list[str]) -> str:
    request = prompt.strip() or "Run a Neurodesk module-backed neuroimaging workflow."
    lines = [
        "## Neurodesk execution scaffold",
        "",
        f"- Request: {request}",
    ]
    if module_loads:
        lines.append(f"- Requested modules: {', '.join(module_loads)}")
    lines.extend(
        [
            "- Update the placeholder shell command and any dataset paths on the right.",
            "- The code cell is valid Python and prints a bash scaffold you can refine before running real analyses.",
        ]
    )
    return "\n".join(lines)


def _infer_neurodesk_code(prompt: str) -> str:
    module_loads = _extract_module_loads(prompt)
    module_lines = "\n".join(f"module load {item}" for item in module_loads) or (
        "# module load <replace-with-required-neurodesk-module>"
    )
    return "\n".join(
        [
            "from textwrap import dedent",
            "",
            "# Review this bash scaffold before replacing the echo command",
            "# with the real Neurodesk CLI invocation you want to run.",
            "shell_script = dedent(",
            '    """',
            "    source /etc/profile.d/lmod.sh 2>/dev/null || \\",
            "      source /usr/share/lmod/lmod/init/bash 2>/dev/null || true",
            f"    {module_lines}",
            "    # Replace the echo below with the actual Neurodesk command.",
            '    echo "Neurodesk scaffold ready. Replace this line with the real CLI command."',
            '    """',
            ").strip()",
            "",
            "print(shell_script)",
        ]
    )


def _infer_fmri_qc_markdown(prompt: str) -> str:
    request = prompt.strip() or "Inspect a BOLD run with confounds and a carpet plot."
    return "\n".join(
        [
            "## fMRI QC scaffold",
            "",
            f"- Request: {request}",
            "- Update the BOLD and confounds paths to match your dataset.",
            "- Run the code cell to load the run, inspect motion/confounds, and render a carpet plot.",
        ]
    )


def _infer_fmri_qc_code() -> str:
    return "\n".join(
        [
            "from pathlib import Path",
            "",
            "import pandas as pd",
            "from nilearn import image, plotting",
            "",
            "# Update these paths to match a real preprocessed BOLD run.",
            "bold_path = Path('data/sub-01/func/sub-01_task-rest_desc-preproc_bold.nii.gz')",
            "confounds_path = Path('data/sub-01/func/sub-01_task-rest_desc-confounds_timeseries.tsv')",
            "",
            "img = image.load_img(str(bold_path))",
            "confounds = pd.read_csv(confounds_path, sep='\\t')",
            "",
            "qc_columns = [",
            "    column",
            "    for column in [",
            "        'framewise_displacement',",
            "        'trans_x', 'trans_y', 'trans_z',",
            "        'rot_x', 'rot_y', 'rot_z',",
            "    ]",
            "    if column in confounds.columns",
            "]",
            "",
            "print({'shape': img.shape, 'n_confounds': len(confounds.columns)})",
            "if qc_columns:",
            "    display(confounds[qc_columns].head())",
            "else:",
            "    print('No standard QC columns were found in the confounds table.')",
            "",
            "plotting.plot_carpet(img, title=bold_path.name)",
        ]
    )


def _infer_glm_markdown(prompt: str) -> str:
    request = prompt.strip() or "Fit a first-level GLM for a task fMRI run."
    return "\n".join(
        [
            "## First-level GLM scaffold",
            "",
            f"- Request: {request}",
            "- Update the dataset paths and TR before fitting the model.",
            "- Review the design matrix and then adapt the contrast definition to your task.",
        ]
    )


def _infer_glm_code() -> str:
    return "\n".join(
        [
            "from pathlib import Path",
            "",
            "import pandas as pd",
            "from nilearn import image, plotting",
            "from nilearn.glm.first_level import FirstLevelModel",
            "",
            "# Update these paths to a real task run, events file, and confounds table.",
            "bold_path = Path('data/sub-01/func/sub-01_task-motor_desc-preproc_bold.nii.gz')",
            "events_path = Path('data/sub-01/func/sub-01_task-motor_events.tsv')",
            "confounds_path = Path('data/sub-01/func/sub-01_task-motor_desc-confounds_timeseries.tsv')",
            "t_r = 2.0",
            "",
            "img = image.load_img(str(bold_path))",
            "events = pd.read_csv(events_path, sep='\\t')",
            "confounds = pd.read_csv(confounds_path, sep='\\t')",
            "",
            "candidate_confounds = [",
            "    column",
            "    for column in [",
            "        'trans_x', 'trans_y', 'trans_z',",
            "        'rot_x', 'rot_y', 'rot_z',",
            "        'framewise_displacement',",
            "    ]",
            "    if column in confounds.columns",
            "]",
            "model = FirstLevelModel(t_r=t_r, hrf_model='glover', noise_model='ar1')",
            "model = model.fit(",
            "    img,",
            "    events=events,",
            "    confounds=confounds[candidate_confounds].fillna(0) if candidate_confounds else None,",
            ")",
            "",
            "design_matrix = model.design_matrices_[0]",
            "display(design_matrix.head())",
            "plotting.plot_design_matrix(design_matrix)",
            "",
            "if 'trial_type' in events.columns:",
            "    print('Available trial types:', sorted(events['trial_type'].dropna().unique()))",
        ]
    )


def _extract_json_candidate(content: str) -> str | None:
    stripped = content.strip()
    if not stripped:
        return None

    if stripped.startswith("```"):
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            return stripped[start : end + 1]

    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        return stripped[first_brace : last_brace + 1]
    return None


def _extract_assistant_content(payload: Any, fallback_text: str) -> str:
    if isinstance(payload, dict):
        message = payload.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
        content = payload.get("content")
        if isinstance(content, str) and content.strip():
            return content
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail
    return fallback_text


def _build_planner_system_prompt() -> str:
    return "\n".join(
        [
            "You are Brain Researcher Studio notebook planner.",
            "Convert the user request into notebook operations for an assistant-first notebook UI.",
            "Return strict JSON only. Do not use markdown fences. Do not add explanation outside JSON.",
            (
                "Schema: "
                '{"assistant_message":"string","ops":[{"type":"append|edit|ai_edit|edit_and_move|delete_cell|move_cell|replace_cell",'
                '"cell_id":"optional string","cell_type":"optional code|markdown","source":"optional string",'
                '"after_cell_id":"optional string or null","before_cell_id":"optional string or null",'
                '"target_index":"optional integer","reason":"optional string","metadata":"optional object"}]}'
            ),
            "Rules:",
            "- Prefer the smallest notebook change that satisfies the request.",
            "- Use append for new cells.",
            "- Use markdown for notes, goals, plans, and explanations.",
            "- Use code for executable Python.",
            "- Preserve existing cell ids when editing or moving cells unless you are replacing a broken cell.",
        ]
    )


def _build_planner_user_message(
    *,
    prompt: str,
    notebook: StudioNotebook,
    conversation: list[Message],
) -> str:
    recent_conversation = [
        {
            "role": message.role,
            "content": _truncate_text(message.content, 280),
        }
        for message in conversation[-6:]
    ]
    notebook_summary = {
        "id": notebook.id,
        "path": notebook.path,
        "title": notebook.title,
        "revision": notebook.revision,
        "cells": [
            {
                "index": index,
                "id": cell.id,
                "cell_type": cell.type.value,
                "status": cell.status.value,
                "source_preview": _truncate_text(cell.source, 240),
            }
            for index, cell in enumerate(notebook.cells[:16])
        ],
    }
    return json.dumps(
        {
            "task": "Plan notebook operations",
            "user_request": prompt,
            "recent_conversation": recent_conversation,
            "notebook": notebook_summary,
        },
        ensure_ascii=False,
        indent=2,
    )


def _normalize_role(value: str | None) -> str:
    if value in {"assistant", "system"}:
        return value
    return "user"


class StudioAssistantPlannerSource(str, Enum):
    AGENT_TYPED = "agent_typed"
    HEURISTIC_FALLBACK = "heuristic_fallback"


class StudioAssistantPlannerFallbackReason(str, Enum):
    FAST_PATH = "fast_path"
    AGENT_ERROR = "agent_error"
    AGENT_NO_PLAN = "agent_no_plan"


class StudioAssistantPlannerError(BaseModel):
    code: str = Field(..., min_length=1, max_length=100)
    message: str | None = None
    status_code: int | None = None


class StudioAssistantNotebookCellPreview(BaseModel):
    id: str | None = Field(default=None, max_length=200)
    cell_type: StudioNotebookCellType = StudioNotebookCellType.CODE
    source: str = ""
    status: str | None = Field(default=None, max_length=50)


class StudioAssistantNotebookContext(BaseModel):
    path: str | None = Field(default=None, max_length=2000)
    title: str | None = Field(default=None, max_length=300)
    kernel_name: str | None = Field(default=None, max_length=100)
    metadata: dict[str, Any] = Field(default_factory=dict)
    revision: int | None = Field(default=None, ge=1)
    cells: list[StudioAssistantNotebookCellPreview] = Field(default_factory=list)


class StudioAssistantNotebookOp(BaseModel):
    type: str = Field(..., min_length=1, max_length=50)
    cell_id: str | None = Field(default=None, max_length=200)
    cell_type: str | None = Field(default=None, max_length=20)
    source: str | None = None
    after_cell_id: str | None = Field(default=None, max_length=200)
    before_cell_id: str | None = Field(default=None, max_length=200)
    target_index: int | None = None
    outputs: list[StudioNotebookOutput] | None = None
    execution_count: int | None = None
    status: str | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None
    reason: str | None = None


class StudioAssistantPlan(BaseModel):
    assistant_message: str = Field(..., min_length=1)
    ops: list[StudioAssistantNotebookOp] = Field(default_factory=list)
    source: StudioAssistantPlannerSource
    fallback_reason: StudioAssistantPlannerFallbackReason | None = None
    planner_error: StudioAssistantPlannerError | None = None


class StudioAssistantThreadState(BaseModel):
    assistant_session_id: str = Field(..., pattern=r"^ast_[A-Za-z0-9]+$")
    thread: Thread
    messages: list[Message] = Field(default_factory=list)


class StudioAssistantTurnRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    notebook: StudioAssistantNotebookContext | None = None


class StudioAssistantTurnResponse(BaseModel):
    assistant_session_id: str = Field(..., pattern=r"^ast_[A-Za-z0-9]+$")
    thread: Thread
    messages: list[Message]
    user_message: Message
    assistant_message: Message
    plan: StudioAssistantPlan
    notebook: StudioNotebook


def _build_notebook_context_dict(
    notebook: StudioNotebook,
    conversation: list[Message],
) -> dict[str, Any]:
    """Build a compact notebook context dict for the studio/plan endpoint.

    Sends the last 5 cells and last 3 non-bootstrap messages so the agent
    service has enough context to ground cell generation without blowing the
    LLM context budget.
    """
    cells = [
        {
            "id": cell.id,
            "cell_type": cell.type.value,
            "source": _truncate_text(cell.source, 240),
            "status": cell.status.value,
        }
        for cell in notebook.cells[-5:]
    ]
    recent_messages = [
        {"role": m.role, "content": _truncate_text(m.content, 280)}
        for m in conversation[-8:]
        if m.role in {"user", "assistant"}
        and m.metadata.get("source") != "studio_bootstrap"
    ][-3:]
    return {
        "notebook_id": notebook.id,
        "notebook_path": notebook.path,
        "cells": cells,
        "recent_messages": recent_messages,
    }


class StudioAssistantRuntime:
    """Durable Studio assistant facade with typed notebook planning."""

    def __init__(
        self,
        *,
        studio_session_runtime: StudioSessionRuntime,
        studio_notebook_runtime: StudioNotebookRuntime,
        agent_base_url: str | None = None,
    ) -> None:
        self._studio_session_runtime = studio_session_runtime
        self._studio_notebook_runtime = studio_notebook_runtime
        self._agent_base_url = (agent_base_url or AGENT_URL).rstrip("/")
        self._planner_timeout_seconds = _resolve_planner_timeout_seconds()
        db_path = getattr(studio_session_runtime, "_db_path", None)
        self._store = SqliteStateStore(
            db_path=db_path or str(get_data_root() / "orchestrator" / "state.sqlite")
        )
        self._store_ready = False

    async def _ensure_store(self) -> SqliteStateStore:
        if not self._store_ready:
            await self._store.initialize()
            self._store_ready = True
        return self._store

    async def _require_session(
        self, owner_user_id: str, session_id: str
    ) -> StudioSession:
        session = await self._studio_session_runtime.get_session(session_id)
        if session is None or session.owner_user_id != owner_user_id:
            raise KeyError(session_id)
        return session

    async def _ensure_thread(
        self, owner_user_id: str, session: StudioSession
    ) -> tuple[Thread, list[Message]]:
        store = await self._ensure_store()
        thread_id = _assistant_thread_id(session)
        stored = await store.get_thread(thread_id)
        if stored is not None:
            thread = Thread.model_validate(stored)
            messages = [
                Message.model_validate(item)
                for item in await store.list_messages(thread_id=thread_id, limit=200)
            ]
            return thread, messages

        now = _utc_now()
        thread = Thread(
            thread_id=thread_id,
            title=_assistant_title_for_session(session),
            created_at=now,
            updated_at=now,
            message_count=0,
            context={
                "surface": "studio",
                "project_id": session.project_id,
                "session_id": session.id,
                "assistant_session_id": session.assistant_session_id,
            },
            metadata={
                "source": "brain_researcher.studio",
                "owner_user_id": owner_user_id,
                "runtime_profile_id": session.runtime_profile_id.value,
            },
            scenario_id="studio_notebook_assistant",
        )
        await store.upsert_thread(
            thread_id=thread.thread_id,
            thread=thread.model_dump(mode="json"),
            user_id=owner_user_id,
        )
        intro = Message(
            id=_message_id(),
            thread_id=thread.thread_id,
            role="assistant",
            content=(
                "Tell me what notebook you want to generate. I can draft cells, "
                "revise existing cells, and explain the next analysis step."
            ),
            timestamp=now,
            metadata={"source": "studio_bootstrap"},
        )
        await store.append_message(
            thread_id=thread.thread_id,
            message_id=intro.id,
            message=intro.model_dump(mode="json"),
        )
        thread.message_count = 1
        thread.updated_at = now
        await store.upsert_thread(
            thread_id=thread.thread_id,
            thread=thread.model_dump(mode="json"),
            user_id=owner_user_id,
        )
        return thread, [intro]

    async def get_thread_state(
        self, owner_user_id: str, session_id: str
    ) -> StudioAssistantThreadState:
        session = await self._require_session(owner_user_id, session_id)
        thread, messages = await self._ensure_thread(owner_user_id, session)
        return StudioAssistantThreadState(
            assistant_session_id=session.assistant_session_id,
            thread=thread,
            messages=messages,
        )

    async def _append_thread_message(
        self,
        *,
        owner_user_id: str,
        thread: Thread,
        message: Message,
    ) -> Thread:
        store = await self._ensure_store()
        await store.append_message(
            thread_id=thread.thread_id,
            message_id=message.id,
            message=message.model_dump(mode="json"),
        )
        updated = thread.model_copy(
            update={
                "message_count": thread.message_count + 1,
                "updated_at": message.timestamp,
            }
        )
        await store.upsert_thread(
            thread_id=updated.thread_id,
            thread=updated.model_dump(mode="json"),
            user_id=owner_user_id,
        )
        return updated

    def _normalize_planner_operation(
        self, raw: dict[str, Any]
    ) -> StudioAssistantNotebookOp | None:
        op_type = str(raw.get("type") or "").strip()
        if op_type not in {
            "append",
            "edit",
            "ai_edit",
            "edit_and_move",
            "delete_cell",
            "move_cell",
            "replace_cell",
            "apply_outputs",
        }:
            return None
        return StudioAssistantNotebookOp.model_validate(raw)

    def _parse_agent_plan(self, content: str) -> StudioAssistantPlan | None:
        candidate = _extract_json_candidate(content)
        if not candidate:
            return None
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None

        raw_ops = payload.get("ops")
        if raw_ops is None:
            raw_ops = payload.get("operations")
        ops: list[StudioAssistantNotebookOp] = []
        if isinstance(raw_ops, list):
            for item in raw_ops:
                if not isinstance(item, dict):
                    continue
                normalized = self._normalize_planner_operation(item)
                if normalized is not None:
                    ops.append(normalized)
        assistant_message = (
            str(
                payload.get("assistant_message")
                or payload.get("assistantMessage")
                or ""
            ).strip()
            or "Updated the notebook plan."
        )
        return StudioAssistantPlan(
            assistant_message=assistant_message,
            ops=ops,
            source=StudioAssistantPlannerSource.AGENT_TYPED,
        )

    def _infer_markdown_source(self, prompt: str) -> str:
        lowered = prompt.lower()
        if _prompt_mentions_neurodesk_module_execution(prompt):
            return _infer_neurodesk_markdown(prompt, _extract_module_loads(prompt))
        if _prompt_mentions_glm_scaffold(prompt):
            return _infer_glm_markdown(prompt)
        if _prompt_mentions_fmri_qc(prompt):
            return _infer_fmri_qc_markdown(prompt)
        if "research goal" in lowered or "研究目标" in prompt:
            body = prompt.strip() or "Describe the research goal for this notebook."
            return f"## Research goal\n\n{body}"
        if "hypothesis" in lowered or "假设" in prompt:
            body = prompt.strip() or "State the working hypothesis for this analysis."
            return f"## Hypothesis\n\n{body}"
        if any(token in lowered for token in ["summary", "note", "markdown"]):
            body = prompt.strip() or "Summarize the next analysis step."
            return f"## Note\n\n{body}"
        return f"## Assistant note\n\n{prompt.strip()}"

    def _infer_code_source(self, prompt: str) -> str:
        lowered = prompt.lower()
        if _prompt_mentions_neurodesk_module_execution(prompt):
            return _infer_neurodesk_code(prompt)
        if _prompt_mentions_glm_scaffold(prompt):
            return _infer_glm_code()
        if _prompt_mentions_fmri_qc(prompt):
            return _infer_fmri_qc_code()
        if "print hello" in lowered or "打印hello" in prompt or "打印 hello" in prompt:
            return 'print("hello")'
        if "plot" in lowered or "绘图" in prompt or "画图" in prompt:
            return "\n".join(
                [
                    "import matplotlib.pyplot as plt",
                    "",
                    "fig, ax = plt.subplots()",
                    "ax.plot([0, 1, 2], [0, 1, 4])",
                    "ax.set_title('Assistant draft plot')",
                    "plt.show()",
                ]
            )
        if (
            any(token in lowered for token in ["load", "read", "csv"])
            or "读取" in prompt
        ):
            return "\n".join(
                [
                    "from pathlib import Path",
                    "import pandas as pd",
                    "",
                    "data_path = Path('data.csv')",
                    "df = pd.read_csv(data_path)",
                    "df.head()",
                ]
            )
        return "\n".join(
            [
                "# Assistant draft",
                f"request = {json.dumps(prompt.strip(), ensure_ascii=False)}",
                "print('Drafted from request:')",
                "print(request)",
            ]
        )

    def _append_plan_duplicates_recent_cells(
        self, notebook: StudioNotebook, ops: list[StudioAssistantNotebookOp]
    ) -> bool:
        append_ops = [
            op
            for op in ops
            if op.type == "append"
            and op.cell_type in {"markdown", "code"}
            and op.source
        ]
        if len(append_ops) != len(ops) or len(notebook.cells) < len(append_ops):
            return False
        recent_cells = notebook.cells[-len(append_ops) :]
        for op, cell in zip(append_ops, recent_cells, strict=False):
            if cell.type.value != (op.cell_type or ""):
                return False
            if cell.source.strip() != (op.source or "").strip():
                return False
            expected_source = (op.metadata or {}).get("source")
            if expected_source and cell.metadata.get("source") != expected_source:
                return False
        return True

    def _build_fallback_plan(
        self,
        prompt: str,
        notebook: StudioNotebook,
        *,
        fallback_reason: StudioAssistantPlannerFallbackReason | None = None,
        planner_error: StudioAssistantPlannerError | None = None,
    ) -> StudioAssistantPlan:
        normalized = prompt.strip()
        if not normalized:
            return StudioAssistantPlan(
                assistant_message="Add a request and I will draft cells into the notebook.",
                ops=[],
                source=StudioAssistantPlannerSource.HEURISTIC_FALLBACK,
                fallback_reason=fallback_reason,
                planner_error=planner_error,
            )
        if _prompt_mentions_t1_visualization(normalized):
            return StudioAssistantPlan(
                assistant_message=(
                    "Drafted a T1 visualization notebook scaffold. Update the image "
                    "path on the right, then run the code cell."
                ),
                ops=[
                    StudioAssistantNotebookOp(
                        type="append",
                        cell_type="markdown",
                        source=_infer_t1_visualization_markdown(normalized),
                        after_cell_id=notebook.cells[-1].id if notebook.cells else None,
                        metadata={"source": "studio_assistant_fallback"},
                    ),
                    StudioAssistantNotebookOp(
                        type="append",
                        cell_type="code",
                        source=_infer_t1_visualization_code(),
                        metadata={"source": "studio_assistant_fallback"},
                    ),
                ],
                source=StudioAssistantPlannerSource.HEURISTIC_FALLBACK,
                fallback_reason=fallback_reason,
                planner_error=planner_error,
            )
        if _prompt_mentions_neurodesk_module_execution(normalized):
            return StudioAssistantPlan(
                assistant_message=(
                    "Drafted a Neurodesk execution scaffold. Review the module loads and "
                    "replace the placeholder shell command on the right before real execution."
                ),
                ops=[
                    StudioAssistantNotebookOp(
                        type="append",
                        cell_type="markdown",
                        source=_infer_neurodesk_markdown(
                            normalized, _extract_module_loads(normalized)
                        ),
                        after_cell_id=notebook.cells[-1].id if notebook.cells else None,
                        metadata={"source": "studio_assistant_fallback"},
                    ),
                    StudioAssistantNotebookOp(
                        type="append",
                        cell_type="code",
                        source=_infer_neurodesk_code(normalized),
                        metadata={"source": "studio_assistant_fallback"},
                    ),
                ],
                source=StudioAssistantPlannerSource.HEURISTIC_FALLBACK,
                fallback_reason=fallback_reason,
                planner_error=planner_error,
            )
        if _prompt_mentions_glm_scaffold(normalized):
            return StudioAssistantPlan(
                assistant_message=(
                    "Drafted a first-level GLM scaffold. Update the BOLD, events, and confounds "
                    "paths on the right, then inspect the design matrix before fitting contrasts."
                ),
                ops=[
                    StudioAssistantNotebookOp(
                        type="append",
                        cell_type="markdown",
                        source=_infer_glm_markdown(normalized),
                        after_cell_id=notebook.cells[-1].id if notebook.cells else None,
                        metadata={"source": "studio_assistant_fallback"},
                    ),
                    StudioAssistantNotebookOp(
                        type="append",
                        cell_type="code",
                        source=_infer_glm_code(),
                        metadata={"source": "studio_assistant_fallback"},
                    ),
                ],
                source=StudioAssistantPlannerSource.HEURISTIC_FALLBACK,
                fallback_reason=fallback_reason,
                planner_error=planner_error,
            )
        if _prompt_mentions_fmri_qc(normalized):
            return StudioAssistantPlan(
                assistant_message=(
                    "Drafted an fMRI QC scaffold with confounds and a carpet plot. "
                    "Update the run paths on the right, then execute the code cell."
                ),
                ops=[
                    StudioAssistantNotebookOp(
                        type="append",
                        cell_type="markdown",
                        source=_infer_fmri_qc_markdown(normalized),
                        after_cell_id=notebook.cells[-1].id if notebook.cells else None,
                        metadata={"source": "studio_assistant_fallback"},
                    ),
                    StudioAssistantNotebookOp(
                        type="append",
                        cell_type="code",
                        source=_infer_fmri_qc_code(),
                        metadata={"source": "studio_assistant_fallback"},
                    ),
                ],
                source=StudioAssistantPlannerSource.HEURISTIC_FALLBACK,
                fallback_reason=fallback_reason,
                planner_error=planner_error,
            )
        ops: list[StudioAssistantNotebookOp] = []
        last_cell_id = notebook.cells[-1].id if notebook.cells else None
        lowered = normalized.lower()
        wants_markdown = any(
            token in lowered
            for token in [
                "markdown",
                "research goal",
                "objective",
                "hypothesis",
                "note",
                "summary",
            ]
        ) or any(token in normalized for token in ["说明", "总结", "笔记", "研究目标", "假设"])
        wants_code = any(
            token in lowered
            for token in ["python", "code", "print", "execute", "plot", "load", "read"]
        ) or any(token in normalized for token in ["代码", "运行", "绘图", "加载", "读取"])

        if wants_markdown:
            ops.append(
                StudioAssistantNotebookOp(
                    type="append",
                    cell_type="markdown",
                    source=self._infer_markdown_source(normalized),
                    after_cell_id=last_cell_id,
                    metadata={"source": "studio_assistant_fallback"},
                )
            )
        if wants_code:
            ops.append(
                StudioAssistantNotebookOp(
                    type="append",
                    cell_type="code",
                    source=self._infer_code_source(normalized),
                    metadata={"source": "studio_assistant_fallback"},
                )
            )
        if not ops:
            ops.append(
                StudioAssistantNotebookOp(
                    type="append",
                    cell_type="markdown",
                    source=self._infer_markdown_source(normalized),
                    after_cell_id=last_cell_id,
                    metadata={"source": "studio_assistant_fallback"},
                )
            )

        summary = " and ".join(
            "1 markdown cell" if op.cell_type == "markdown" else "1 code cell"
            for op in ops
        )
        return StudioAssistantPlan(
            assistant_message=(
                f"Added {summary} to the notebook. Review on the right, then edit or run the drafted cells."
            ),
            ops=ops,
            source=StudioAssistantPlannerSource.HEURISTIC_FALLBACK,
            fallback_reason=fallback_reason,
            planner_error=planner_error,
        )

    def _build_fast_path_plan(
        self, prompt: str, notebook: StudioNotebook
    ) -> StudioAssistantPlan | None:
        normalized = prompt.strip()
        if not normalized:
            return None
        if _prompt_mentions_t1_visualization(normalized):
            return self._build_fallback_plan(
                normalized,
                notebook,
                fallback_reason=StudioAssistantPlannerFallbackReason.FAST_PATH,
            )
        return None

    def _resolve_workspace_id(self, session: StudioSession) -> str:
        metadata = session.metadata if isinstance(session.metadata, dict) else {}
        for key in ("workspace_id", "workspace"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return session.project_id

    def _build_planner_error(self, exc: Exception) -> StudioAssistantPlannerError:
        if isinstance(exc, httpx.HTTPStatusError):
            code = "agent_error"
            message = str(exc)
            try:
                detail = exc.response.json()
            except Exception:
                detail = None
            if isinstance(detail, dict):
                raw_code = detail.get("error") or detail.get("code")
                raw_message = detail.get("message") or detail.get("detail")
                if isinstance(raw_code, str) and raw_code.strip():
                    code = raw_code.strip()
                if isinstance(raw_message, str) and raw_message.strip():
                    message = raw_message.strip()
            return StudioAssistantPlannerError(
                code=code,
                message=message,
                status_code=exc.response.status_code,
            )
        if isinstance(exc, httpx.RequestError):
            return StudioAssistantPlannerError(
                code="agent_unavailable",
                message=str(exc),
            )
        return StudioAssistantPlannerError(code="planner_error", message=str(exc))

    async def _request_agent_plan(
        self,
        *,
        owner_user_id: str,
        session: StudioSession,
        thread: Thread,
        notebook: StudioNotebook,
        conversation: list[Message],
        prompt: str,
    ) -> StudioAssistantPlan | None:
        notebook_context = _build_notebook_context_dict(notebook, conversation)
        payload = {
            "prompt": prompt,
            "notebook_context": notebook_context,
            "thread_id": thread.thread_id,
            "session_id": session.id,
            "metadata": {
                "surface": "studio",
                "scenario_id": "studio_notebook_assistant",
                "studio_session_id": session.id,
                "assistant_session_id": session.assistant_session_id,
                "owner_user_id": owner_user_id,
                "project_id": session.project_id,
                "workspace_id": self._resolve_workspace_id(session),
            },
        }
        timeout = httpx.Timeout(self._planner_timeout_seconds, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{self._agent_base_url}/agent/studio/plan", json=payload
            )
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict):
            return None
        ops = [
            self._normalize_planner_operation(op)
            for op in (data.get("ops") or [])
            if isinstance(op, dict)
        ]
        ops = [op for op in ops if op is not None]
        return StudioAssistantPlan(
            assistant_message=(
                str(data.get("assistant_message") or "").strip()
                or "Updated the notebook plan."
            ),
            ops=ops,
            source=StudioAssistantPlannerSource.AGENT_TYPED,
        )

    def _coerce_operation_type(self, op_type: str) -> StudioNotebookOperationType:
        if op_type == "append":
            return StudioNotebookOperationType.APPEND
        if op_type in {"edit", "ai_edit"}:
            return StudioNotebookOperationType.EDIT
        if op_type == "edit_and_move":
            return StudioNotebookOperationType.EDIT_AND_MOVE
        if op_type == "delete_cell":
            return StudioNotebookOperationType.DELETE_CELL
        if op_type == "move_cell":
            return StudioNotebookOperationType.MOVE_CELL
        if op_type == "replace_cell":
            return StudioNotebookOperationType.REPLACE_CELL
        if op_type == "apply_outputs":
            return StudioNotebookOperationType.APPLY_OUTPUTS
        raise ValueError(f"Unsupported Studio assistant op: {op_type}")

    def _coerce_output_status(self, value: str | None):
        if value == "running":
            return "running"
        if value == "error":
            return "failed"
        if value == "finished":
            return "succeeded"
        return "idle"

    def _build_cell_input(
        self,
        *,
        op: StudioAssistantNotebookOp,
        existing_cell_id: str | None = None,
    ) -> StudioNotebookCellInput:
        cell_type = (
            StudioNotebookCellType.MARKDOWN
            if op.cell_type == "markdown"
            else StudioNotebookCellType.CODE
        )
        return StudioNotebookCellInput(
            id=existing_cell_id,
            cell_type=cell_type,
            source=op.source or "",
            metadata=dict(op.metadata or {}),
        )

    def _resolve_move_anchors(
        self, notebook: StudioNotebook, op: StudioAssistantNotebookOp
    ) -> tuple[str | None, str | None]:
        before_cell_id = op.before_cell_id
        after_cell_id = op.after_cell_id
        if before_cell_id or after_cell_id or op.target_index is None:
            return before_cell_id, after_cell_id
        target_index = max(0, min(op.target_index, len(notebook.cells)))
        if target_index >= len(notebook.cells):
            return None, notebook.cells[-1].id if notebook.cells else None
        return notebook.cells[target_index].id, None

    def _to_runtime_operation(
        self, notebook: StudioNotebook, op: StudioAssistantNotebookOp
    ) -> StudioNotebookOperation:
        op_type = self._coerce_operation_type(op.type)
        before_cell_id, after_cell_id = self._resolve_move_anchors(notebook, op)
        if op_type == StudioNotebookOperationType.APPEND:
            return StudioNotebookOperation(
                type=op_type,
                after_cell_id=after_cell_id,
                before_cell_id=before_cell_id,
                cell=self._build_cell_input(op=op),
            )
        if op_type in {
            StudioNotebookOperationType.REPLACE_CELL,
            StudioNotebookOperationType.EDIT_AND_MOVE,
        }:
            return StudioNotebookOperation(
                type=op_type,
                cell_id=op.cell_id,
                after_cell_id=after_cell_id,
                before_cell_id=before_cell_id,
                cell=self._build_cell_input(op=op),
            )
        if op_type == StudioNotebookOperationType.APPLY_OUTPUTS:
            status = self._coerce_output_status(op.status)
            return StudioNotebookOperation(
                type=op_type,
                cell_id=op.cell_id,
                outputs=op.outputs or [],
                execution_count=op.execution_count,
                status=status,
            )
        return StudioNotebookOperation(
            type=op_type,
            cell_id=op.cell_id,
            source=op.source,
            after_cell_id=after_cell_id,
            before_cell_id=before_cell_id,
            metadata=dict(op.metadata or {}),
        )

    async def _ensure_notebook(
        self,
        owner_user_id: str,
        session: StudioSession,
        context: StudioAssistantNotebookContext | None,
    ) -> StudioNotebook:
        notebook_path = str(context.path or "").strip() if context else ""
        studio_root = f"projects/{session.project_id}/notebooks/studio/"
        if not notebook_path:
            notebook_path = ""
        elif notebook_path.endswith("/draft.ipynb"):
            notebook_path = ""
        elif notebook_path.startswith(studio_root) and not notebook_path.endswith(
            f"/{session.id}.ipynb"
        ):
            notebook_path = ""
        payload = StudioNotebookDocumentInput(
            notebook_path=notebook_path or None,
            title=context.title if context else None,
            kernel_name=context.kernel_name if context else None,
            metadata=context.metadata if context else {},
        )
        return await self._studio_notebook_runtime.open_or_create_notebook(
            owner_user_id,
            session.id,
            payload,
        )

    async def submit_turn(
        self,
        owner_user_id: str,
        session_id: str,
        request: StudioAssistantTurnRequest,
    ) -> StudioAssistantTurnResponse:
        session = await self._require_session(owner_user_id, session_id)
        thread, existing_messages = await self._ensure_thread(owner_user_id, session)
        notebook = await self._ensure_notebook(owner_user_id, session, request.notebook)

        user_message = Message(
            id=_message_id(),
            thread_id=thread.thread_id,
            role="user",
            content=request.content.strip(),
            timestamp=_utc_now(),
            metadata={
                "source": "studio_assistant",
                "studio_session_id": session.id,
            },
        )
        thread = await self._append_thread_message(
            owner_user_id=owner_user_id,
            thread=thread,
            message=user_message,
        )
        conversation = [*existing_messages, user_message]

        plan = self._build_fast_path_plan(request.content, notebook)
        planner_error: StudioAssistantPlannerError | None = None
        if plan is None:
            try:
                plan = await self._request_agent_plan(
                    owner_user_id=owner_user_id,
                    session=session,
                    thread=thread,
                    notebook=notebook,
                    conversation=conversation,
                    prompt=request.content,
                )
            except Exception as exc:
                planner_error = self._build_planner_error(exc)
        if plan is None:
            plan = self._build_fallback_plan(
                request.content,
                notebook,
                fallback_reason=(
                    StudioAssistantPlannerFallbackReason.AGENT_ERROR
                    if planner_error is not None
                    else StudioAssistantPlannerFallbackReason.AGENT_NO_PLAN
                ),
                planner_error=planner_error,
            )

        if plan.ops and self._append_plan_duplicates_recent_cells(notebook, plan.ops):
            plan = plan.model_copy(
                update={
                    "assistant_message": (
                        "The notebook already ends with this draft, so I did not append the same cells again."
                    ),
                    "ops": [],
                }
            )

        if plan.ops:
            runtime_ops = [self._to_runtime_operation(notebook, op) for op in plan.ops]
            notebook = await self._studio_notebook_runtime.apply_operations(
                owner_user_id,
                session_id,
                StudioNotebookOpsRequest(operations=runtime_ops),
            )

        assistant_message = Message(
            id=_message_id(),
            thread_id=thread.thread_id,
            role="assistant",
            content=plan.assistant_message,
            timestamp=_utc_now(),
            metadata={
                "source": "studio_assistant",
                "planner_source": plan.source.value,
                "fallback_reason": (
                    plan.fallback_reason.value
                    if plan.fallback_reason is not None
                    else None
                ),
                "planner_fallback_reason": (
                    plan.fallback_reason.value
                    if plan.fallback_reason is not None
                    else None
                ),
                "planner_error_code": (
                    plan.planner_error.code if plan.planner_error is not None else None
                ),
                "op_count": len(plan.ops),
                "notebook_revision": notebook.revision,
            },
        )
        thread = await self._append_thread_message(
            owner_user_id=owner_user_id,
            thread=thread,
            message=assistant_message,
        )
        messages = [
            Message.model_validate(item)
            for item in await (await self._ensure_store()).list_messages(
                thread_id=thread.thread_id,
                limit=200,
            )
        ]
        return StudioAssistantTurnResponse(
            assistant_session_id=session.assistant_session_id,
            thread=thread,
            messages=messages,
            user_message=user_message,
            assistant_message=assistant_message,
            plan=plan,
            notebook=notebook,
        )
