"""Lightweight helpers for coding-oriented workflows.

Provides:
- Intent classification for coding vs read/search/test queries
- A first-turn ripgrep ritual surfacing likely files/snippets
- Patch summarisation/application and pytest runners

The helpers rely on ripgrep/git/pytest when available and degrade gracefully
if those binaries are absent.
"""

from __future__ import annotations

import asyncio
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

CODING_STOPWORDS = {
    "the",
    "and",
    "that",
    "this",
    "with",
    "file",
    "code",
    "show",
    "lines",
    "please",
    "function",
    "implement",
    "read",
    "write",
    "make",
    "add",
    "update",
    "remove",
    "for",
    "using",
    "into",
    "from",
    "main",
}


@dataclass
class CodingPlan:
    intent: str
    terms: List[str]
    matches: List[Dict[str, str]]
    summary: str
    steps: List[str]


def classify_intent(prompt: str) -> str:
    """Return a coarse intent label for the given prompt."""

    text = prompt.lower()
    edit_keywords = ["add", "update", "modify", "patch", "refactor", "fix", "implement"]
    test_keywords = ["test", "pytest", "unit", "run tests", "validate"]
    read_keywords = ["read", "open", "show", "display", "inspect", "list"]
    search_keywords = ["find", "where", "search", "locate"]

    if any(k in text for k in edit_keywords):
        return "edit"
    if any(k in text for k in test_keywords):
        return "test"
    if any(k in text for k in search_keywords):
        return "search"
    if any(k in text for k in read_keywords):
        return "read"
    return "mixed"


_DOMAIN_PATTERNS = [
    r"\bglm\b",
    r"nilearn\.glm",
    r"fitlins",
    r"\bds\d{5,6}\b",
    r"rest(ing)?[- ]?state",
    r"\bconnectivit(y|ies)\b",
    r"nimare",
    r"neurosynth",
    r"knowledge\s+graph",
    r"br_kg",
    r"fmriprep",
    r"brain atlas",
    r"meta[- ]?analysis",
]

MANDATORY_TOOL_PARAMS: Dict[str, Tuple[str, ...]] = {
    "fs.apply_patch": ("patch",),
    "fs.search": ("pattern",),
}

TOOL_DEFAULTS: Dict[str, Dict[str, object]] = {
    "fs.list_directory": {"path": "."},
    "fs.read": {"path": "."},
    "fs.search": {"root": ".", "max_results": 200, "case_sensitive": False},
    "fs.apply_patch": {"apply": True},
}

SAFE_AUTORUN_TOOLS = {"fs.read", "fs.list_directory", "fs.search"}

_FILE_PATH_RX = re.compile(r"(?P<path>[\w./-]+\.[a-zA-Z0-9]+)")


def is_domain_prompt(prompt: str) -> bool:
    text = prompt.lower()
    matches = [re.search(rx, text, re.IGNORECASE) for rx in _DOMAIN_PATTERNS]
    hits = sum(1 for match in matches if match)
    return hits >= 2


def _has_code_signals(prompt: str) -> bool:
    text = prompt.lower()
    return any(
        s in text
        for s in [
            "diff --git",
            "```",
            "apply patch",
            "pytest",
            "/",
            ".py",
        ]
    )


def should_use_coding_mode(prompt: str, auto_enabled: bool = True) -> bool:
    """Return True when the prompt should enter coding track.

    Logic:
    - If auto is disabled, return False
    - If strong domain cues present, prefer domain (False)
    - If coding signals or coding intents present, return True
    """
    if not auto_enabled:
        return False
    if is_domain_prompt(prompt):
        # Allow explicit code signals to override domain if clearly editing
        return _has_code_signals(prompt)
    intent = classify_intent(prompt)
    return intent in {"edit", "read", "search", "test"} or _has_code_signals(prompt)


def _extract_terms(prompt: str, max_terms: int = 5) -> List[str]:
    words = re.findall(r"[A-Za-z0-9_]{3,}", prompt.lower())
    seen: List[str] = []
    for word in words:
        if word in CODING_STOPWORDS:
            continue
        if word in seen:
            continue
        seen.append(word)
        if len(seen) >= max_terms:
            break
    return seen


def _run_ripgrep(
    terms: List[str], repo_root: Path, max_matches: int = 60
) -> List[Dict[str, str]]:
    if not terms:
        return []
    if not shutil.which("rg"):
        return []

    matches: List[Dict[str, str]] = []
    seen_keys = set()
    for term in terms:
        cmd = [
            "rg",
            "--line-number",
            "--no-heading",
            "--color",
            "never",
            term,
        ]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception:
            continue

        for line in result.stdout.splitlines():
            parts = line.split(":", 2)
            if len(parts) != 3:
                continue
            path, line_no, snippet = parts
            key = (path, line_no)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            matches.append(
                {
                    "path": path,
                    "line": line_no,
                    "match": snippet.strip(),
                    "term": term,
                }
            )
            if len(matches) >= max_matches:
                return matches

    return matches


def generate_plan(prompt: str, repo_root: Path) -> CodingPlan:
    intent = classify_intent(prompt)
    terms = _extract_terms(prompt)
    matches = _run_ripgrep(terms, repo_root)

    top_paths: List[str] = []
    for match in matches:
        if match["path"] not in top_paths:
            top_paths.append(match["path"])
        if len(top_paths) >= 5:
            break

    if top_paths:
        summary = (
            f"Identified {len(matches)} matching lines across {len(top_paths)} files."
        )
    else:
        summary = "No direct matches found; consider broader search or specifying files explicitly."

    steps: List[str] = []
    if top_paths:
        steps.append(f"Review files: {', '.join(top_paths[:3])}")
    if intent == "edit":
        steps.append("Draft patch for required changes")
        steps.append("Run targeted pytest suite")
    elif intent == "test":
        steps.append("Run targeted pytest suite")
    else:
        steps.append("Confirm desired edit or inspection")

    if not steps:
        steps = ["Clarify desired action"]

    return CodingPlan(
        intent=intent, terms=terms, matches=matches, summary=summary, steps=steps
    )


def summarise_patch(patch: str, preview_lines: int = 20) -> Dict[str, str]:
    lines = patch.strip().splitlines()
    preview = "\n".join(lines[:preview_lines]) if lines else ""
    return {
        "summary": f"Patch with {len(lines)} lines",
        "preview": preview,
    }


def _collect_candidate_paths(
    prompt: str,
    plan_matches: List[Dict[str, str]],
    repo_root: Path,
    limit: int = 5,
) -> List[str]:
    candidates: List[str] = []
    seen = set()

    for match in plan_matches:
        path = match.get("path")
        if not path:
            continue
        resolved = Path(repo_root / path)
        if resolved.exists() and path not in seen:
            candidates.append(path)
            seen.add(path)
            if len(candidates) >= limit:
                return candidates

    for candidate_match in _FILE_PATH_RX.finditer(prompt):
        path = candidate_match.group("path")
        if not path or path in seen:
            continue
        resolved = Path(repo_root / path)
        if resolved.exists():
            candidates.append(path)
            seen.add(path)
            if len(candidates) >= limit:
                break
    return candidates


def _guess_search_pattern(prompt: str, plan_terms: List[str]) -> Optional[str]:
    quoted = re.findall(r"\"([^\"]+)\"|'([^']+)'", prompt)
    for primary, secondary in quoted:
        candidate = primary or secondary
        if candidate.strip():
            return candidate.strip()
    match_word = re.search(r"search (for )?(?P<term>[\w_-]+)", prompt, re.IGNORECASE)
    if match_word:
        return match_word.group("term")
    if plan_terms:
        return plan_terms[0]
    return None


def missing_required_params(tool_name: str, params: Dict[str, object]) -> List[str]:
    required = MANDATORY_TOOL_PARAMS.get(tool_name)
    if not required:
        return []
    missing: List[str] = []
    for key in required:
        value = params.get(key)
        if value is None:
            missing.append(key)
        elif isinstance(value, str) and not value.strip():
            missing.append(key)
        elif isinstance(value, (list, dict)) and not value:
            missing.append(key)
    return missing


def should_autorun_tool(tool_name: str) -> bool:
    return tool_name in SAFE_AUTORUN_TOOLS


def build_follow_up(tool_name: str, missing_params: List[str]) -> str:
    if not missing_params:
        return ""
    if tool_name == "fs.apply_patch":
        return "I need the diff patch to apply. Paste the patch or describe the changes so I can draft it."
    if tool_name == "fs.search" and "pattern" in missing_params:
        return "Which pattern should I search for? Provide a regex or text snippet."
    missing_list = ", ".join(missing_params)
    return f"I still need values for: {missing_list}. Please provide them."


def infer_parameters(
    tool_name: Optional[str],
    prompt: str,
    repo_root: Path,
    plan_matches: List[Dict[str, str]],
    current_params: Dict[str, object],
    plan_terms: Optional[List[str]] = None,
) -> Tuple[Dict[str, object], List[str]]:
    if not tool_name:
        return {}, []

    inferred: Dict[str, object] = {}
    params = dict(current_params or {})

    defaults = TOOL_DEFAULTS.get(tool_name)
    if defaults:
        for key, value in defaults.items():
            if key not in params:
                inferred[key] = value
                params[key] = value

    candidate_paths = _collect_candidate_paths(prompt, plan_matches, repo_root)

    if tool_name in {"fs.read", "fs.list_directory"}:
        if "path" not in params:
            if candidate_paths:
                inferred["path"] = candidate_paths[0]
            else:
                inferred["path"] = "."
            params["path"] = inferred["path"]

    if tool_name == "fs.search":
        if "root" not in params:
            inferred["root"] = candidate_paths[0] if candidate_paths else "."
            params["root"] = inferred["root"]
        if "pattern" not in params:
            pattern = _guess_search_pattern(prompt, plan_terms or [])
            if pattern:
                inferred["pattern"] = pattern
                params["pattern"] = pattern

    if tool_name == "fs.apply_patch":
        if "apply" not in params:
            inferred["apply"] = True
            params["apply"] = True

    missing = missing_required_params(tool_name, params)
    return inferred, missing


def apply_patch(patch: str, repo_root: Path) -> Dict[str, Optional[str]]:
    result = {
        "applied": False,
        "stdout": None,
        "stderr": None,
        "summary": None,
        "preview": None,
        "error": None,
    }

    if not patch.strip():
        result["error"] = "Empty patch"
        return result

    git_path = shutil.which("git")
    if not git_path:
        result["error"] = "git binary not available"
        return result

    try:
        check_proc = subprocess.run(
            [git_path, "apply", "--check", "--whitespace=nowarn"],
            cwd=str(repo_root),
            input=patch,
            text=True,
            capture_output=True,
        )
        if check_proc.returncode != 0:
            result["stderr"] = check_proc.stderr
            result["error"] = "Patch failed validation"
            return result

        apply_proc = subprocess.run(
            [git_path, "apply", "--whitespace=nowarn"],
            cwd=str(repo_root),
            input=patch,
            text=True,
            capture_output=True,
        )
        result["stdout"] = apply_proc.stdout
        result["stderr"] = apply_proc.stderr
        if apply_proc.returncode != 0:
            result["error"] = "Patch application failed"
            return result
    except Exception as exc:  # pragma: no cover
        result["error"] = str(exc)
        return result

    summary = summarise_patch(patch)
    result["applied"] = True
    result["summary"] = summary["summary"]
    result["preview"] = summary["preview"]
    return result


def run_tests(
    targets: Optional[List[str]],
    marker: Optional[str],
    extra_args: Optional[List[str]],
    repo_root: Path,
) -> Dict[str, Optional[str]]:
    cmd = ["pytest"]
    if marker:
        cmd.extend(["-m", marker])
    if targets:
        cmd.extend(targets)
    if extra_args:
        cmd.extend(extra_args)

    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )

    return {
        "command": " ".join(shlex.quote(part) for part in cmd),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


async def run_in_executor(func, *args, loop=None):
    """Utility to offload blocking work to a thread."""

    loop = loop or asyncio.get_event_loop()
    return await loop.run_in_executor(None, func, *args)
