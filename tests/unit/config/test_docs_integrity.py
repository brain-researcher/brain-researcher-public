from __future__ import annotations

import html
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_ROOT = REPO_ROOT / "docs"
MKDOCS_CONFIGS = (REPO_ROOT / "mkdocs.yml", REPO_ROOT / "mkdocs-simple.yml")
HISTORICAL_MARKER = "<!-- docs-status: historical -->"
ROOT_DOCS = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "CONTRIBUTING.md",
    REPO_ROOT / "tests" / "README_TESTING.md",
    REPO_ROOT / "apps" / "web-ui" / "README.md",
    REPO_ROOT / "scripts" / "autoresearch" / "README.md",
    REPO_ROOT / "infrastructure" / "deployment" / "README.md",
)
CANONICAL_ENTRY_DOCS = ROOT_DOCS[-3:]
HISTORICAL_SNAPSHOTS = (
    REPO_ROOT / "docs" / "archive" / "deployment" / "README.md",
    REPO_ROOT / "apps" / "web-ui" / "IMPLEMENTATION_SUMMARY.md",
    REPO_ROOT / "apps" / "web-ui" / "TESTING_3D_VIEWER.md",
    REPO_ROOT / "infrastructure" / "deployment" / "gcp" / "GKE_QUICKSTART.md",
    REPO_ROOT
    / "docs"
    / "use_cases"
    / "bounded_autoresearch_a1_2026-04-30"
    / "BOUNDED_AUTORESEARCH_CASE_REPORT.md",
    REPO_ROOT / "docs" / "appendices" / "03_appendix_C_dataset_resource.md",
    REPO_ROOT / "docs" / "appendices" / "04_appendix_D_tool_registry.md",
    REPO_ROOT / "docs" / "mcp" / "brain_researcher_mcp_reader_question_inventory.md",
    REPO_ROOT / "tests" / "performance" / "k6" / "IMPLEMENTATION_SUMMARY.md",
    REPO_ROOT / "tests" / "tool_calling" / "FINAL_RESULTS.md",
    REPO_ROOT
    / "src"
    / "brain_researcher"
    / "services"
    / "br_kg"
    / "IMPLEMENTATION_SUMMARY.md",
    REPO_ROOT
    / "src"
    / "brain_researcher"
    / "services"
    / "br_kg"
    / "BELONGS_TO_IMPLEMENTATION.md",
    REPO_ROOT
    / "src"
    / "brain_researcher"
    / "services"
    / "br_kg"
    / "DERIVED_FROM_IMPLEMENTATION.md",
)

INLINE_LINK_RE = re.compile(r"(?P<image>!)?\[[^\]]*\]\(\s*(?P<target><[^>]+>|[^\s)]+)")
REFERENCE_DEFINITION_RE = re.compile(
    r"^\s{0,3}\[(?P<label>[^\]]+)\]:\s*(?P<target><[^>]+>|\S+)",
    re.MULTILINE,
)
IMAGE_REFERENCE_RE = re.compile(r"!\[[^\]]*\]\[(?P<label>[^\]]+)\]")
HTML_TARGET_RE = re.compile(
    r"<(?P<tag>a|img)\b[^>]*?\b(?P<attr>href|src)=[\"'](?P<target>[^\"']+)[\"']",
    re.IGNORECASE,
)
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
INLINE_CODE_RE = re.compile(r"`+([^`\n]+?)`+")
REPO_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])"
    r"(?P<path>(?:\.github|apps|configs|contracts|docs|infrastructure|"
    r"reproducibility|scripts|src|tests)/[A-Za-z0-9_./*${}<>-]+)"
)
USER_LOCAL_ENV_RE = re.compile(r"(?:^|/)\.env(?:\.[A-Za-z0-9_-]+)*\.local$")


class _MkDocsLoader(yaml.SafeLoader):
    """Parse MkDocs Python-name tags as data without importing the object."""


_MkDocsLoader.add_multi_constructor(
    "tag:yaml.org,2002:python/name:",
    lambda _loader, suffix, _node: suffix,
)


def _documentation_files() -> tuple[Path, ...]:
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.md", "*.mdx"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return tuple(
        REPO_ROOT / raw_path.decode("utf-8")
        for raw_path in tracked.rstrip(b"\0").split(b"\0")
        if raw_path
    )


def _without_code_blocks(text: str) -> str:
    kept: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(1)[0]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            kept.append("\n")
        elif fence is None:
            kept.append(line)
        else:
            kept.append("\n")
    return INLINE_CODE_RE.sub("", "".join(kept))


def _code_samples(text: str) -> Iterator[tuple[str, int, str]]:
    fence: str | None = None
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(1)[0]
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is not None:
            yield line, line_number, line
            continue
        for match in INLINE_CODE_RE.finditer(line):
            yield match.group(1), line_number, line


def _repo_path_candidates(source: Path, raw_path: str) -> Iterator[Path]:
    """Resolve a documented path from the repo or its enclosing component."""

    relative_path = Path(raw_path.rstrip("/"))
    bases = [REPO_ROOT]
    parent = source.parent
    while parent != REPO_ROOT:
        bases.append(parent)
        parent = parent.parent

    seen: set[Path] = set()
    for base in bases:
        candidate = base / relative_path
        if candidate not in seen:
            seen.add(candidate)
            yield candidate


def _repo_path_exists(source: Path, raw_path: str) -> bool:
    return any(
        candidate.exists() for candidate in _repo_path_candidates(source, raw_path)
    )


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _clean_target(raw_target: str) -> str:
    target = html.unescape(raw_target.strip())
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    return unquote(target)


def _resolve_local_target(source: Path, raw_target: str) -> Path | None:
    target = _clean_target(raw_target)
    if not target or target.startswith("#") or "{{" in target:
        return None
    split = urlsplit(target)
    if split.scheme or split.netloc:
        return None
    if not split.path:
        return None
    if split.path.startswith("/"):
        return REPO_ROOT / split.path.lstrip("/")
    return source.parent / split.path


def _markdown_targets(source: Path) -> Iterator[tuple[bool, str, int]]:
    text = _without_code_blocks(source.read_text(encoding="utf-8"))
    image_labels = {
        match.group("label").casefold() for match in IMAGE_REFERENCE_RE.finditer(text)
    }
    for match in INLINE_LINK_RE.finditer(text):
        yield bool(match.group("image")), match.group("target"), _line_number(
            text, match.start()
        )
    for match in REFERENCE_DEFINITION_RE.finditer(text):
        yield (
            match.group("label").casefold() in image_labels,
            match.group("target"),
            _line_number(text, match.start()),
        )
    for match in HTML_TARGET_RE.finditer(text):
        yield (
            match.group("tag").casefold() == "img",
            match.group("target"),
            _line_number(text, match.start()),
        )


def _missing_markdown_targets(*, images: bool) -> list[str]:
    missing: list[str] = []
    for source in _documentation_files():
        for is_image, target, line_number in _markdown_targets(source):
            if is_image is not images:
                continue
            resolved = _resolve_local_target(source, target)
            if resolved is not None and not resolved.exists():
                missing.append(
                    f"{source.relative_to(REPO_ROOT)}:{line_number}: {target}"
                )
    return missing


def _nav_targets(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _nav_targets(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _nav_targets(item)


def _normalized_nav(value: object) -> object:
    if isinstance(value, str):
        if value in {"index.md", "index-simple.md"}:
            return "<home>"
        return value
    if isinstance(value, list):
        return [_normalized_nav(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalized_nav(item) for key, item in value.items()}
    return value


def test_local_markdown_links_resolve() -> None:
    assert not (missing := _missing_markdown_targets(images=False)), "\n".join(missing)


def test_local_markdown_images_resolve() -> None:
    assert not (missing := _missing_markdown_targets(images=True)), "\n".join(missing)


def test_active_document_repo_paths_exist() -> None:
    missing: list[str] = []
    for source in _documentation_files():
        text = source.read_text(encoding="utf-8")
        if HISTORICAL_MARKER in text:
            continue
        for sample, line_number, context in _code_samples(text):
            for match in REPO_PATH_RE.finditer(sample):
                raw_path = match.group("path").rstrip(".,:;)]}'\"")
                raw_path = raw_path.split("#", 1)[0]
                if any(character in raw_path for character in "*${}<>"):
                    continue
                context_offset = context.find(sample)
                preceding_text = context[: max(context_offset, 0)].casefold()
                if re.search(
                    r"\b(?:does not|do not|no|not|without|missing)\b[^.]{0,80}$",
                    preceding_text,
                ):
                    continue
                if USER_LOCAL_ENV_RE.search(raw_path):
                    continue
                if "my_new_tool" in raw_path:
                    continue
                if not _repo_path_exists(source, raw_path):
                    missing.append(
                        f"{source.relative_to(REPO_ROOT)}:{line_number}: {raw_path}"
                    )
    assert not missing, "\n".join(sorted(set(missing)))


def test_mkdocs_navigation_is_synchronized_and_resolves() -> None:
    configs = [
        yaml.load(path.read_text(encoding="utf-8"), Loader=_MkDocsLoader)
        for path in MKDOCS_CONFIGS
    ]
    assert _normalized_nav(configs[0]["nav"]) == _normalized_nav(configs[1]["nav"])

    required_targets = {
        "ENVIRONMENT_SETUP.md",
        "reproducibility_packs.md",
        "contract-tiers.md",
        "hpc.md",
        "how-to-add-tool.md",
        "appendices/00_index.md",
    }
    for config_path, config in zip(MKDOCS_CONFIGS, configs, strict=True):
        targets = set(_nav_targets(config["nav"]))
        assert required_targets <= targets
        missing = sorted(
            target
            for target in targets
            if not urlsplit(target).scheme and not (DOCS_ROOT / target).is_file()
        )
        assert not missing, f"{config_path.name}: {missing}"


def test_canonical_entrypoints_define_status_boundaries() -> None:
    for path in CANONICAL_ENTRY_DOCS:
        content = path.read_text(encoding="utf-8").casefold()
        for status in (
            "active",
            "experimental",
            "historical",
            "private-input-required",
        ):
            assert status in content, f"{path.relative_to(REPO_ROOT)}: {status}"

    root_readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert root_readme.count("## Where the important pieces live") == 1
    assert "## What's in the repo" not in root_readme
    for path in CANONICAL_ENTRY_DOCS:
        assert str(path.relative_to(REPO_ROOT)) in root_readme


def test_historical_snapshots_are_machine_readable() -> None:
    for path in HISTORICAL_SNAPSHOTS:
        assert HISTORICAL_MARKER in path.read_text(encoding="utf-8"), path


def test_active_docs_do_not_advertise_unshipped_entrypoints() -> None:
    operations = (DOCS_ROOT / "OPERATIONS.md").read_text(encoding="utf-8")
    mcp = (DOCS_ROOT / "mcp.md").read_text(encoding="utf-8")

    for stale in ("br demo", "scripts/docker_manager.sh"):
        assert stale not in operations
    for stale in (
        "scripts/ops/mcp_docker_stdio.sh",
        "configs/claude/mcp.http.template.json.tmpl",
    ):
        assert stale not in mcp
