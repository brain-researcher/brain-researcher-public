#!/usr/bin/env python3
"""
Official-asset-aware neurometabench adapter and screening workflow.

This script now dispatches each meta-analysis to the best-matching official
benchmark asset track:
  1. NiMADS / BrainMap-backed cases
  2. PMC full-text backed cases
  3. PubMed metadata backed cases

For screening-capable routes it measures the recall ceiling of:
  candidate retrieval → efetch abstracts → LLM single-abstract screening

against neurometabench ground-truth included studies.

Two diagnostic numbers are reported when screening is run:
  candidate_recall  – did the candidate source even find the GT papers?
  screen_recall     – after LLM filtering, how many GT papers survived?

Usage
-----
python scripts/neurometabench_screening_pipeline.py \
    --meta-pmid 36100907 \
    --max-candidates 500 \
    --llm-model gemini-2.5-pro \
    --output-dir /tmp/neurometabench_results/36100907
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import logging
import os
import random
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None  # type: ignore[assignment]
    genai_types = None  # type: ignore[assignment]

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.neurometabench_v1.shared import build_screening_criteria

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── PubMed E-utilities ────────────────────────────────────────────────────────
PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
PMC_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EFETCH_BATCH = 200
ESEARCH_RETMAX = 5000
REQUEST_TIMEOUT = 60
# Polite rate limit: NCBI allows 3 req/s without API key, 10 req/s with.
RATE_SLEEP = 0.4
MAX_RETRIES = 3
BACKOFF = 1.0
PMC_MIN_CANDIDATES = 10
DOI_BATCH_SIZE = 50
NIMADS_FINAL_MERGE_THRESHOLD = 0.90
NIMADS_FINAL_MERGE_EXACT_COORD_OVERRIDE = True
NIMADS_MERGE_REPORT_FILE = "fuzzy_merge_summary.html"
NIMADS_MERGE_DIAGNOSTICS_FILE = "fuzzy_merge_diagnostics.json"
_NIMADS_MERGE_MODULE: Any = None


# ── Data loading ──────────────────────────────────────────────────────────────


def load_meta_row(data_dir: Path, meta_pmid: str) -> Dict:
    """Return the row from meta_datasets.csv for the given PMID."""
    src = data_dir / "meta_datasets.csv"
    with src.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if (row.get("pmid") or "").strip() == meta_pmid:
                # Build fallback search from topic + modality when search is empty/short
                search = (row.get("search") or "").strip()
                row["_original_search"] = search
                if len(search) < 10:
                    modality_fb = (row.get("modality") or "").strip() or 'fMRI OR neuroimaging OR PET OR "brain imaging"'
                    fallback = f"{row.get('topic', '')} {modality_fb}".strip()
                    logger.warning(
                        "search field empty/short (%r); using fallback: %r",
                        search,
                        fallback,
                    )
                    row["search"] = fallback
                return row
    raise ValueError(f"meta_pmid {meta_pmid!r} not found in {src}")


def load_ground_truth(data_dir: Path, meta_pmid: str) -> set:
    """Return set of study PMIDs included in the meta-analysis ground truth."""
    src = data_dir / "included_studies.csv"
    pmids: set = set()
    with src.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if (row.get("meta_pmid") or "").strip() == meta_pmid:
                sp = (row.get("study_pmid") or "").strip()
                if sp:
                    pmids.add(sp)
    return pmids


def load_closed_world_candidates(data_dir: Path, meta_pmid: str) -> List[str]:
    """Load candidate PMIDs from all_studies.csv if available for this meta_pmid.

    Returns a list of PMIDs (deduplicated, preserving order) or empty list if
    all_studies.csv has no entries for this meta_pmid.
    """
    src = data_dir / "all_studies.csv"
    if not src.exists():
        return []
    pmids: List[str] = []
    seen: set = set()
    try:
        with src.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if (row.get("meta_pmid") or "").strip() != meta_pmid:
                    continue
                sp = (row.get("study_pmid") or "").strip()
                if sp and sp not in seen:
                    seen.add(sp)
                    pmids.append(sp)
    except Exception as exc:
        logger.warning("Could not read all_studies.csv: %s", exc)
    return pmids


def load_all_study_universe(data_dir: Path) -> List[str]:
    pmids: List[str] = []
    seen: set = set()
    for filename in ("all_studies.csv", "included_studies.csv"):
        src = data_dir / filename
        if not src.exists():
            continue
        with src.open("r", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                pmid = (row.get("study_pmid") or "").strip()
                if pmid and pmid not in seen:
                    seen.add(pmid)
                    pmids.append(pmid)
    return pmids


def load_mixed_pool_candidates(
    data_dir: Path,
    meta_pmid: str,
    *,
    noise_ratio: int = 5,
    seed: int = 0,
    max_total: Optional[int] = None,
) -> List[str]:
    gt_pmids = sorted(load_ground_truth(data_dir, meta_pmid), key=lambda p: (int(p), p) if p.isdigit() else (10**20, p))
    if not gt_pmids:
        return []
    gt_set = set(gt_pmids)
    universe = [pmid for pmid in load_all_study_universe(data_dir) if pmid not in gt_set]
    rng = random.Random(f"{seed}:{meta_pmid}:mixed_pool")
    rng.shuffle(universe)
    n_noise_target = max(0, int(noise_ratio)) * len(gt_pmids)
    if max_total is not None:
        n_noise_target = min(n_noise_target, max(0, int(max_total) - len(gt_pmids)))
    n_noise = min(len(universe), n_noise_target)
    pool = list(gt_pmids) + universe[:n_noise]
    rng.shuffle(pool)
    return pool


def load_all_meta_rows(data_dir: Path) -> List[Dict[str, str]]:
    """Load all curated meta-analysis rows from meta_datasets.csv."""
    src = data_dir / "meta_datasets.csv"
    with src.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def normalize_folder_name(topic_name: str) -> str:
    """Normalize a topic name to the official project folder convention."""
    normalized = topic_name.lower()
    normalized = normalized.replace(" ", "_").replace("-", "_")
    normalized = re.sub(r"\([^)]*\)", "", normalized)
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)
    normalized = re.sub(r"_+", "_", normalized)
    return normalized.strip("_")


def find_nimads_assets(data_dir: Path, topic: str) -> Dict[str, Any]:
    """Return available official NiMADS assets for a topic."""
    project_key = normalize_folder_name(topic)
    project_dir = data_dir / "nimads" / project_key
    if not project_dir.exists():
        return {
            "project_key": project_key,
            "project_dir": None,
            "raw_jsons": [],
            "merged_studyset": None,
            "merged_annotation": None,
        }

    raw_jsons = sorted(
        str(path)
        for path in project_dir.glob("*.json")
        if path.is_file()
    )
    merged_dir = project_dir / "merged"
    merged_studyset = merged_dir / "nimads_studyset.json"
    merged_annotation = merged_dir / "nimads_annotation.json"
    return {
        "project_key": project_key,
        "project_dir": str(project_dir),
        "raw_jsons": raw_jsons,
        "merged_studyset": str(merged_studyset) if merged_studyset.exists() else None,
        "merged_annotation": str(merged_annotation) if merged_annotation.exists() else None,
    }


def _count_nimads_entities(paths: List[str]) -> Tuple[int, int]:
    """Return aggregate (n_studies, n_analyses) across NiMADS JSON files."""
    n_studies = 0
    n_analyses = 0
    for path_str in paths:
        try:
            payload = json.loads(Path(path_str).read_text(encoding="utf-8"))
        except Exception:
            continue
        studies = payload.get("studies", [])
        if not isinstance(studies, list):
            continue
        n_studies += len(studies)
        for study in studies:
            analyses = study.get("analyses", []) if isinstance(study, dict) else []
            if isinstance(analyses, list):
                n_analyses += len(analyses)
    return n_studies, n_analyses


def _pmc_digits(value: str) -> str:
    return re.sub(r"[^0-9]", "", value or "")


def _local_pmc_root(data_dir: Path) -> Path:
    return data_dir / "meta-studies" / "pmc-oa"


def find_local_pmc_bundle(data_dir: Path, meta_pmid: str, pmcid: str) -> Optional[Path]:
    """Find the local PMC OA bundle containing this meta-analysis, if present."""
    pmcid_digits = _pmc_digits(pmcid)
    root = _local_pmc_root(data_dir)
    if not root.exists():
        return None

    for metadata_csv in root.rglob("metadata.csv"):
        try:
            with metadata_csv.open("r", encoding="utf-8", newline="") as fh:
                for row in csv.DictReader(fh):
                    row_pmid = (row.get("pmid") or "").strip()
                    row_pmcid = _pmc_digits(row.get("pmcid") or "")
                    if row_pmid == meta_pmid or (pmcid_digits and row_pmcid == pmcid_digits):
                        return metadata_csv.parents[1]
        except Exception:
            continue
    return None


def resolve_case_dispatch(row: Dict[str, Any], data_dir: Path) -> Dict[str, Any]:
    """Resolve the official benchmark route for a meta-analysis case."""
    topic = (row.get("topic") or "").strip()
    method = (row.get("method") or "").strip()
    additional_methods = (row.get("additional_methods") or "").strip()
    original_search = (row.get("_original_search") or row.get("search") or "").strip()
    pmcid = (row.get("pmcid") or "").strip()

    nimads_assets = find_nimads_assets(data_dir, topic)
    nimads_paths = list(nimads_assets["raw_jsons"])
    if nimads_assets["merged_studyset"]:
        nimads_paths.append(nimads_assets["merged_studyset"])
    n_nimads_studies, n_nimads_analyses = _count_nimads_entities(nimads_paths)

    local_pmc_bundle = find_local_pmc_bundle(data_dir, str(row.get("pmid") or ""), pmcid)
    has_pmc = bool(pmcid) or local_pmc_bundle is not None

    brainmap_like = any(
        marker in f"{method} {additional_methods} {original_search}".lower()
        for marker in ("brainmap", "data-driven clustering", "image-based meta-analysis")
    )

    if brainmap_like and nimads_assets["project_dir"]:
        return {
            "official_route": "nimads_brainmap",
            "dispatch_reason": (
                "Methodology is BrainMap/NiMADS-backed rather than metadata-only article retrieval."
            ),
            "recommended_workflow": "analysis_reproduction",
            "nimads_assets": {
                **nimads_assets,
                "n_studies": n_nimads_studies,
                "n_analyses": n_nimads_analyses,
            },
            "pmc_assets": {
                "pmcid": pmcid or None,
                "local_bundle": str(local_pmc_bundle) if local_pmc_bundle else None,
            },
        }

    if has_pmc:
        return {
            "official_route": "pmc_fulltext",
            "dispatch_reason": (
                "Meta-analysis has PMC full-text coverage, so bibliography/full-text assets are preferred "
                "over live PubMed metadata search."
            ),
            "recommended_workflow": "screening_from_fulltext",
            "nimads_assets": {
                **nimads_assets,
                "n_studies": n_nimads_studies,
                "n_analyses": n_nimads_analyses,
            },
            "pmc_assets": {
                "pmcid": pmcid or None,
                "local_bundle": str(local_pmc_bundle) if local_pmc_bundle else None,
            },
        }

    return {
        "official_route": "pubmed_metadata",
        "dispatch_reason": (
            "No official NiMADS/BrainMap routing and no PMC full-text asset found; fall back to metadata search."
        ),
        "recommended_workflow": "screening_from_metadata",
        "nimads_assets": {
            **nimads_assets,
            "n_studies": n_nimads_studies,
            "n_analyses": n_nimads_analyses,
        },
        "pmc_assets": {
            "pmcid": pmcid or None,
            "local_bundle": str(local_pmc_bundle) if local_pmc_bundle else None,
        },
    }


def build_case_adapter_manifest(
    row: Dict[str, Any],
    data_dir: Path,
    dispatch: Dict[str, Any],
    gt_pmids: set,
) -> Dict[str, Any]:
    """Build a persistent adapter manifest for one benchmark case."""
    return {
        "meta_pmid": (row.get("pmid") or "").strip(),
        "topic": (row.get("topic") or "").strip(),
        "method": (row.get("method") or "").strip(),
        "year": (row.get("year") or "").strip(),
        "pmcid": (row.get("pmcid") or "").strip() or None,
        "official_route": dispatch["official_route"],
        "dispatch_reason": dispatch["dispatch_reason"],
        "recommended_workflow": dispatch["recommended_workflow"],
        "ground_truth_n_studies": len(gt_pmids),
        "data_dir": str(data_dir),
        "nimads_assets": dispatch["nimads_assets"],
        "nimads_reproduction": dispatch.get("nimads_reproduction"),
        "pmc_assets": dispatch["pmc_assets"],
        "official_entrypoint": dispatch.get("official_entrypoint"),
        "closed_world_candidate_count": len(load_closed_world_candidates(data_dir, (row.get("pmid") or "").strip())),
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_official_nimads_merge_module() -> Any:
    """Load the official NeurometaBench NiMADS merge helpers with caching."""
    global _NIMADS_MERGE_MODULE
    if _NIMADS_MERGE_MODULE is not None:
        return _NIMADS_MERGE_MODULE

    script_path = _repo_root() / "external" / "neurometabench" / "scripts" / "convert_sleuth_to_nimads.py"
    if not script_path.exists():
        raise FileNotFoundError(f"Official NiMADS merge script not found: {script_path}")

    spec = importlib.util.spec_from_file_location("neurometabench_convert_sleuth", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec from {script_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _NIMADS_MERGE_MODULE = module
    return module


def _build_nimads_runner_command(data_dir: Path, project_key: str) -> str:
    analysis_dir = Path("/tmp/neurometabench_analysis") / project_key
    return (
        "python external/neurometabench/scripts/run_meta_analyses.py "
        f"--data-dir {data_dir.resolve()} "
        f"--projects {project_key} "
        f"--analysis-dir {analysis_dir}"
    )


def ensure_nimads_reproduction_adapter(data_dir: Path, nimads_assets: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure a merged NiMADS studyset/annotation pair exists for reproduction."""
    project_key = (nimads_assets.get("project_key") or "").strip()
    project_dir_str = nimads_assets.get("project_dir")
    if not project_key or not project_dir_str:
        return {
            "merge_status": "missing_project",
            "merged_studyset": None,
            "merged_annotation": None,
            "diagnostics_file": None,
            "report_file": None,
            "summary": None,
            "error": "No NiMADS project directory was available for this case.",
            "official_runner_command": None,
        }

    project_dir = Path(project_dir_str)
    merged_dir = project_dir / "merged"
    studyset_path = merged_dir / "nimads_studyset.json"
    annotation_path = merged_dir / "nimads_annotation.json"
    diagnostics_path = merged_dir / NIMADS_MERGE_DIAGNOSTICS_FILE
    report_path = merged_dir / NIMADS_MERGE_REPORT_FILE
    runner_command = _build_nimads_runner_command(data_dir, project_key)

    if studyset_path.exists() and annotation_path.exists():
        summary = None
        if diagnostics_path.exists():
            try:
                diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
                summary = diagnostics.get("summary")
            except Exception:
                summary = None
        return {
            "merge_status": "existing",
            "merged_studyset": str(studyset_path),
            "merged_annotation": str(annotation_path),
            "diagnostics_file": str(diagnostics_path) if diagnostics_path.exists() else None,
            "report_file": str(report_path) if report_path.exists() else None,
            "summary": summary,
            "error": None,
            "official_runner_command": runner_command,
        }

    try:
        module = _load_official_nimads_merge_module()
        output_dir, diagnostics = module.run_final_project_merge(
            project=project_key,
            nimads_root=data_dir / "nimads",
            output_subdir="merged",
            threshold=NIMADS_FINAL_MERGE_THRESHOLD,
            exact_coord_override=NIMADS_FINAL_MERGE_EXACT_COORD_OVERRIDE,
            report_file=NIMADS_MERGE_REPORT_FILE,
            diagnostics_file=NIMADS_MERGE_DIAGNOSTICS_FILE,
        )
        generated_studyset = output_dir / "nimads_studyset.json"
        generated_annotation = output_dir / "nimads_annotation.json"
        generated_diagnostics = output_dir / NIMADS_MERGE_DIAGNOSTICS_FILE
        generated_report = output_dir / NIMADS_MERGE_REPORT_FILE
        return {
            "merge_status": "generated",
            "merged_studyset": str(generated_studyset),
            "merged_annotation": str(generated_annotation),
            "diagnostics_file": str(generated_diagnostics) if generated_diagnostics.exists() else None,
            "report_file": str(generated_report) if generated_report.exists() else None,
            "summary": diagnostics.get("summary"),
            "error": None,
            "official_runner_command": runner_command,
        }
    except Exception as exc:
        return {
            "merge_status": "error",
            "merged_studyset": None,
            "merged_annotation": None,
            "diagnostics_file": None,
            "report_file": None,
            "summary": None,
            "error": str(exc),
            "official_runner_command": runner_command,
        }


# ── Query reformulation ───────────────────────────────────────────────────────

# A small set of commonly used neuroimaging acronyms → MeSH expansions.
_MESH_EXPANSIONS: Dict[str, str] = {
    "ptsd": '"Stress Disorders, Post-Traumatic"[MeSH]',
    "post-traumatic stress disorder": '"Stress Disorders, Post-Traumatic"[MeSH]',
    "fmri": '"Magnetic Resonance Imaging, Functional"[MeSH]',
    "functional mri": '"Magnetic Resonance Imaging, Functional"[MeSH]',
    "vbm": '"Voxel-Based Morphometry"[MeSH]',
    "voxel-based morphometry": '"Voxel-Based Morphometry"[MeSH]',
    "mri": '"Magnetic Resonance Imaging"[MeSH]',
    "alzheimer": '"Alzheimer Disease"[MeSH]',
    "schizophrenia": '"Schizophrenia"[MeSH]',
    "depression": '"Depression"[MeSH]',
    "anxiety": '"Anxiety Disorders"[MeSH]',
    "stroke": '"Stroke"[MeSH]',
    "parkinson": '"Parkinson Disease"[MeSH]',
}


def _rule_based_reformulate(raw: str) -> str:
    """Translate free-text search description into PubMed query syntax.

    Strategy:
    1. Strip surrounding quotes from individual tokens.
    2. Replace `+` with AND.
    3. Wrap plain multi-word phrases in quotes and add [Title/Abstract].
    4. Inject MeSH expansion where an obvious term is detected.
    """
    # Normalise whitespace
    q = raw.strip()

    # Already looks like PubMed syntax if it contains field tags
    if "[" in q and "]" in q:
        return q

    # Replace ' + ' separator with ' AND '
    q = re.sub(r"\s+\+\s+", " AND ", q)
    # Remove bare '+' at start/end of tokens (e.g. "+PTSD" → "PTSD")
    q = re.sub(r"(?<!\w)\+(?=\w)", "", q)

    # Tokenise on common boolean operators (case-insensitive) while preserving
    # quoted strings.
    token_re = re.compile(
        r'"[^"]*"'  # quoted phrase
        r'|(?:AND|OR|NOT)\b'  # boolean ops
        r'|[^\s"()]+',  # bare words / operators
        re.IGNORECASE,
    )
    tokens = token_re.findall(q)
    out_tokens: List[str] = []

    for tok in tokens:
        upper = tok.upper()
        if upper in ("AND", "OR", "NOT"):
            out_tokens.append(upper)
            continue

        # Skip bare punctuation tokens (e.g. '+', '.', ';')
        if re.fullmatch(r"[^A-Za-z0-9\"()\[\]]+", tok):
            continue

        # Strip surrounding quotes for content inspection
        bare = tok.strip('"')
        lower = bare.lower()

        # MeSH expansion check – add alongside the original term with OR
        if lower in _MESH_EXPANSIONS:
            mesh = _MESH_EXPANSIONS[lower]
            out_tokens.append(f'("{bare}"[Title/Abstract] OR {mesh})')
        elif tok.startswith('"'):
            # Already quoted – add [Title/Abstract]
            out_tokens.append(f"{tok}[Title/Abstract]")
        else:
            # Bare word
            out_tokens.append(f'"{bare}"[Title/Abstract]')

    return " ".join(out_tokens) if out_tokens else q


def _llm_reformulate(raw: str, client: "genai.Client", model: str) -> str:
    """Use an LLM call to produce a valid PubMed query from free-text."""
    rules = (
        "Rules for the output PubMed query:\n"
        "- Use BARE TERMS ONLY — do NOT add field tags like [Title/Abstract], [MeSH Terms], [tw], etc.\n"
        "  Bare terms in PubMed search all fields including MeSH, keywords, and abstract automatically.\n"
        "  Field tags dramatically reduce recall for older papers.\n"
        "- Exception: you MAY use 'Humans'[MeSH Terms] as an additional filter if the topic is human-only.\n"
        "- Use Boolean operators: AND, OR, NOT (uppercase). Use parentheses to group OR clauses.\n"
        "- Include common synonyms in OR groups (e.g. fMRI OR 'functional MRI' OR 'functional magnetic resonance imaging').\n"
        "- Retrieval target: eligible primary studies for downstream screening, not review articles.\n"
        "- Do NOT add review OR meta-analysis terms unless the inclusion criteria explicitly require review papers.\n"
        "- If review/meta-analysis terms appear only as bibliography-expansion hints, exclude them from the primary-study query.\n"
        "- Prefer high recall and preserve the original disease/task/method synonym groups.\n"
        "- Treat date cutoffs as PubMed date filters outside the query when possible; do not bury dates in concept groups.\n"
        "- Output ONLY the PubMed query string with no explanation.\n"
        "- Keep it concise — 2-4 concept groups joined by AND is ideal.\n"
    )
    prompt = (
        "You are a PubMed expert. Convert the user's free-text search description "
        "into a valid PubMed query string using proper Boolean syntax and parentheses.\n\n"
        f"{rules}\n"
        f"Free-text search description:\n{raw}"
    )
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=genai_types.GenerateContentConfig(temperature=0, max_output_tokens=4096),
    )
    return resp.text.strip()


def reformulate_query(
    raw: str,
    client: Optional["genai.Client"] = None,
    model: str = "gemini-2.0-flash",
    use_llm: bool = False,
) -> str:
    if use_llm and client is not None:
        try:
            return _llm_reformulate(raw, client, model)
        except Exception as exc:
            logger.warning("LLM query reformulation failed (%s); falling back to rule-based.", exc)
    return _rule_based_reformulate(raw)


# ── PMC full-text helpers ─────────────────────────────────────────────────────


def _strip_xml_namespaces(xml_text: str) -> str:
    """Drop namespace declarations and prefixes so ElementTree can parse PMC XML robustly."""
    clean = re.sub(r'\s+xmlns(?::[\w.-]+)?="[^"]*"', "", xml_text)
    clean = re.sub(r'(<\/?)([\w.-]+:)', r'\1', clean)
    clean = re.sub(r'\s+[\w.-]+:([\w.-]+)=', r' \1=', clean)
    return clean


def _iter_local_articleset_xmls(bundle_dir: Path) -> List[Path]:
    articlesets = bundle_dir / "articlesets"
    if not articlesets.exists():
        return []
    return sorted(articlesets.glob("*.xml"))


def _extract_matching_article_xml(xml_text: str, meta_pmid: str, pmcid: str) -> Optional[str]:
    """Extract a single article XML block matching the target PMID/PMCID."""
    clean = _strip_xml_namespaces(xml_text)
    try:
        root = ET.fromstring(clean)
    except ET.ParseError:
        return None

    pmcid_digits = _pmc_digits(pmcid)
    pmcid_variants = {pmcid_digits, f"PMC{pmcid_digits}"} if pmcid_digits else set()

    for article in root.findall(".//article"):
        article_pmid = (article.findtext(".//article-id[@pub-id-type='pmid']") or "").strip()
        article_pmcid = (article.findtext(".//article-id[@pub-id-type='pmcid']") or "").strip()
        if article_pmid == meta_pmid or (article_pmcid and article_pmcid in pmcid_variants):
            return ET.tostring(article, encoding="unicode")
    return None


def _load_local_pmc_article_xml(data_dir: Path, meta_pmid: str, pmcid: str) -> Optional[str]:
    """Load article XML for a meta-analysis from local PMC OA assets when available."""
    bundle_dir = find_local_pmc_bundle(data_dir, meta_pmid, pmcid)
    if bundle_dir is None:
        return None

    for xml_path in _iter_local_articleset_xmls(bundle_dir):
        try:
            article_xml = _extract_matching_article_xml(
                xml_path.read_text(encoding="utf-8"),
                meta_pmid=meta_pmid,
                pmcid=pmcid,
            )
        except Exception:
            article_xml = None
        if article_xml:
            return article_xml
    return None


def _fetch_remote_pmc_article_xml(pmcid: str) -> Optional[str]:
    """Fetch article XML for a PMCID directly from PMC EFetch."""
    pmcid_digits = _pmc_digits(pmcid)
    if not pmcid_digits:
        return None

    params = {
        "db": "pmc",
        "id": pmcid_digits,
        "rettype": "xml",
        "retmode": "xml",
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(PMC_EFETCH, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            article_xml = _extract_matching_article_xml(
                resp.text,
                meta_pmid="",
                pmcid=pmcid_digits,
            )
            return article_xml or resp.text
        except Exception as exc:
            if attempt == MAX_RETRIES:
                logger.warning("PMC efetch failed for PMCID %s: %s", pmcid, exc)
                return None
            time.sleep(BACKOFF * attempt)
    return None


def _text_or_empty(el: Optional[ET.Element]) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


def _parse_pmc_reference_records(article_xml: str) -> List[Dict[str, str]]:
    """Parse a PMC article reference list into lightweight reference records."""
    clean = _strip_xml_namespaces(article_xml)
    try:
        root = ET.fromstring(clean)
    except ET.ParseError as exc:
        logger.warning("PMC article XML parse failed: %s", exc)
        return []

    refs: List[Dict[str, str]] = []
    for ref in root.findall(".//ref-list/ref"):
        citation = ref.find("element-citation")
        if citation is None:
            citation = ref.find("mixed-citation")
        if citation is None:
            citation = ref
        refs.append(
            {
                "pmid": (citation.findtext(".//pub-id[@pub-id-type='pmid']") or "").strip(),
                "doi": (citation.findtext(".//pub-id[@pub-id-type='doi']") or "").strip(),
                "title": _text_or_empty(citation.find(".//article-title")),
                "year": _text_or_empty(citation.find(".//year")),
            }
        )
    return refs


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _resolve_pmids_from_pmc_refs(refs: List[Dict[str, str]], api_key: Optional[str]) -> List[str]:
    """Resolve PMIDs from PMC references via direct PMID, DOI, then title/year fallback."""
    pmids: List[str] = []

    direct_pmids = [
        re.sub(r"[^0-9]", "", ref.get("pmid", ""))
        for ref in refs
        if ref.get("pmid")
    ]
    pmids.extend([pmid for pmid in direct_pmids if pmid])

    dois = _dedupe_preserve_order(
        [
            ref.get("doi", "").strip()
            for ref in refs
            if ref.get("doi") and not ref.get("pmid")
        ]
    )
    for i in range(0, len(dois), DOI_BATCH_SIZE):
        batch = dois[i : i + DOI_BATCH_SIZE]
        query = " OR ".join(f'"{doi}"[doi]' for doi in batch)
        if query:
            pmids.extend(pubmed_esearch(query, retmax=DOI_BATCH_SIZE, api_key=api_key, max_total=DOI_BATCH_SIZE))
            time.sleep(RATE_SLEEP)

    unresolved = [
        ref
        for ref in refs
        if not ref.get("pmid") and not ref.get("doi") and ref.get("title")
    ]
    # Title matching is the noisiest fallback; keep it bounded.
    for ref in unresolved[:100]:
        title = ref.get("title", "").replace('"', " ").strip()
        year = re.sub(r"[^0-9]", "", ref.get("year", ""))[:4]
        query = f'"{title}"[Title]'
        if year:
            query += f' AND "{year}"[Date - Publication]'
        ids = pubmed_esearch(query, retmax=5, api_key=api_key, max_total=5)
        if len(ids) == 1:
            pmids.append(ids[0])
        time.sleep(RATE_SLEEP)

    return _dedupe_preserve_order(pmids)


def load_pmc_reference_candidates(
    data_dir: Path,
    meta_pmid: str,
    row: Dict[str, Any],
    api_key: Optional[str],
    allow_remote_fetch: bool = True,
) -> Tuple[List[str], Dict[str, Any]]:
    """Load candidate PMIDs from the official PMC full-text bibliography when available."""
    pmcid = (row.get("pmcid") or "").strip()
    if not pmcid:
        return [], {
            "candidate_source": "pmc_reference_list",
            "pmc_source_detail": "missing_pmcid",
            "n_reference_records": 0,
        }

    article_xml = _load_local_pmc_article_xml(data_dir, meta_pmid=meta_pmid, pmcid=pmcid)
    pmc_source_detail = "local_pmc_oa_bundle"
    if article_xml is None and allow_remote_fetch:
        article_xml = _fetch_remote_pmc_article_xml(pmcid)
        pmc_source_detail = "remote_pmc_efetch"
    if article_xml is None:
        return [], {
            "candidate_source": "pmc_reference_list",
            "pmc_source_detail": "pmc_article_unavailable",
            "n_reference_records": 0,
        }

    refs = _parse_pmc_reference_records(article_xml)
    pmids = _resolve_pmids_from_pmc_refs(refs, api_key=api_key)
    return pmids, {
        "candidate_source": "pmc_reference_list",
        "pmc_source_detail": pmc_source_detail,
        "n_reference_records": len(refs),
    }


# ── PubMed esearch ────────────────────────────────────────────────────────────


def _parse_date_range(dates_str: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse the `dates` column into (mindate, maxdate) strings for esearch.

    Common patterns observed in the dataset:
      ''            → no filter
      '- 5/2020'    → maxdate only
      '2002-2020'   → range
      '2000-01/2022'
    """
    if not dates_str or not dates_str.strip():
        return None, None

    s = dates_str.strip()

    # Pattern: '- MM/DD/YYYY' (e.g. '- 8/1/2020')
    m = re.match(r"^-\s*(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        month, day, year = m.group(1), m.group(2), m.group(3)
        maxdate = f"{year}/{int(month):02d}/{int(day):02d}"
        return None, maxdate

    # Pattern: '- MM/YYYY' or '- YYYY'
    m = re.match(r"^-\s*(?:(\d{1,2})/)?(\d{4})$", s)
    if m:
        month, year = m.group(1), m.group(2)
        maxdate = f"{year}/{int(month):02d}/01" if month else f"{year}/12/31"
        return None, maxdate

    # Pattern: 'YYYY-YYYY' or 'YYYY/YYYY'
    m = re.match(r"^(\d{4})[\-/](\d{4})$", s)
    if m:
        return f"{m.group(1)}/01/01", f"{m.group(2)}/12/31"

    logger.debug("Could not parse dates field %r; ignoring date filter.", dates_str)
    return None, None


def pubmed_esearch(
    query: str,
    retmax: int = ESEARCH_RETMAX,
    mindate: Optional[str] = None,
    maxdate: Optional[str] = None,
    api_key: Optional[str] = None,
    max_total: int = 20000,
) -> List[str]:
    """Run esearch and return ALL matching PMIDs (sorted oldest-first).

    Uses usehistory + paging to retrieve results beyond PubMed's single-request
    retmax limit of 9999, so old GT papers that rank low by relevance are included.
    Caps total retrieved at max_total to control downstream screening cost.
    """
    BATCH = 9999  # PubMed per-request maximum

    # Step 1: Post query to history server, get total count + WebEnv/query_key
    params: Dict = {
        "db": "pubmed",
        "term": query,
        "usehistory": "y",
        "retmode": "json",
        "sort": "pub+date",  # oldest-first → GT papers from 2000-2010 come early
    }
    if mindate:
        params.update({"datetype": "pdat", "mindate": mindate})
    if maxdate:
        params.setdefault("datetype", "pdat")
        params["maxdate"] = maxdate
    if api_key:
        params["api_key"] = api_key

    try:
        resp = requests.get(PUBMED_ESEARCH, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()["esearchresult"]
    except Exception as exc:
        logger.error("esearch failed: %s", exc)
        return []

    total = int(data.get("count", 0))
    webenv = data.get("webenv", "")
    query_key = data.get("querykey", "1")
    logger.info("esearch: %d total hits for query", total)

    if total == 0:
        return []

    # Collect first batch (already returned inline by the history post)
    all_ids: List[str] = list(data.get("idlist", []))

    # Step 2: Page through remaining results
    to_fetch = min(total, max_total) - len(all_ids)
    retstart = len(all_ids)

    while to_fetch > 0 and retstart < min(total, max_total):
        batch_size = min(BATCH, to_fetch)
        fetch_params: Dict = {
            "db": "pubmed",
            "query_key": query_key,
            "WebEnv": webenv,
            "retstart": retstart,
            "retmax": batch_size,
            "retmode": "json",
        }
        if api_key:
            fetch_params["api_key"] = api_key
        try:
            r = requests.get(PUBMED_ESEARCH, params=fetch_params, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            # PubMed sometimes embeds literal \n in JSON — strip control chars before parsing
            try:
                page_data = r.json()
            except Exception:
                import re as _re
                clean_text = _re.sub(r'[\x00-\x1f]', ' ', r.text)
                page_data = json.loads(clean_text)
            batch_ids = page_data["esearchresult"].get("idlist", [])
            if not batch_ids:
                break
            all_ids.extend(batch_ids)
            retstart += len(batch_ids)
            to_fetch -= len(batch_ids)
        except Exception as exc:
            logger.warning("esearch paging error at retstart=%d: %s", retstart, exc)
            break
        time.sleep(RATE_SLEEP)

    logger.info("esearch retrieved %d/%d PMIDs (cap=%d)", len(all_ids), total, max_total)
    return all_ids


def validate_esearch_count(query: str, api_key: Optional[str] = None) -> int:
    """Return the hit count for a PubMed esearch query without fetching IDs."""
    params: Dict[str, str] = {
        "db": "pubmed",
        "term": query,
        "rettype": "count",
        "retmode": "json",
    }
    if api_key:
        params["api_key"] = api_key
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(PUBMED_ESEARCH, params=params, timeout=30)
            r.raise_for_status()
            return int(r.json()["esearchresult"]["count"])
        except Exception:
            if attempt == MAX_RETRIES:
                return 0
            time.sleep(BACKOFF * attempt)
    return 0


# ── efetch abstracts ──────────────────────────────────────────────────────────


def _parse_efetch_xml(xml_text: str) -> Dict[str, Dict]:
    """Parse PubmedArticleSet XML and return {pmid: {pmid, title, abstract}}."""
    results: Dict[str, Dict] = {}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("XML parse error in efetch response: %s", exc)
        return results

    for article in root.findall(".//PubmedArticle"):
        pmid_el = article.find(".//PMID")
        pmid = pmid_el.text.strip() if pmid_el is not None and pmid_el.text else ""
        if not pmid:
            continue

        art = article.find(".//Article")
        title = ""
        abstract = ""
        if art is not None:
            title_el = art.find("ArticleTitle")
            if title_el is not None:
                # ArticleTitle may contain child elements; itertext() collects all text
                title = "".join(title_el.itertext()).strip()
            abstract_parts = []
            for at in art.findall(".//AbstractText"):
                label = at.get("Label") or ""
                text = "".join(at.itertext()).strip()
                if label:
                    abstract_parts.append(f"{label}: {text}")
                else:
                    abstract_parts.append(text)
            abstract = " ".join(abstract_parts).strip()

        results[pmid] = {"pmid": pmid, "title": title, "abstract": abstract}
    return results


def efetch_abstracts(
    pmids: List[str],
    batch_size: int = EFETCH_BATCH,
    api_key: Optional[str] = None,
) -> Dict[str, Dict]:
    """Fetch title + abstract for a list of PMIDs in batches."""
    out: Dict[str, Dict] = {}
    total = len(pmids)
    for i in range(0, total, batch_size):
        batch = pmids[i : i + batch_size]
        params: Dict = {
            "db": "pubmed",
            "id": ",".join(batch),
            "rettype": "abstract",
            "retmode": "xml",
        }
        if api_key:
            params["api_key"] = api_key
        try:
            resp = requests.get(PUBMED_EFETCH, params=params, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            parsed = _parse_efetch_xml(resp.text)
            out.update(parsed)
            logger.info(
                "efetch batch %d-%d: %d/%d parsed",
                i + 1,
                min(i + batch_size, total),
                len(parsed),
                len(batch),
            )
        except Exception as exc:
            logger.warning("efetch batch %d-%d failed: %s", i + 1, i + batch_size, exc)
        time.sleep(RATE_SLEEP)
    return out


# ── LLM screening ─────────────────────────────────────────────────────────────

_SCREEN_SYSTEM = """You are a systematic review screener for neuroimaging meta-analyses.
Your goal is HIGH RECALL — it is much worse to miss an eligible study than to pass an ineligible one.
Rules:
- INCLUDE if the abstract clearly meets the inclusion criteria.
- EXCLUDE only if the abstract clearly and explicitly violates an exclusion criterion.
- UNCERTAIN (treated as include) when the abstract is ambiguous, lacks detail, or you cannot
  confidently determine eligibility from the abstract alone.
Pay special attention to exclusion criteria like ROI-only analysis, null effects, overlapping
samples, and non-coordinate results — but require CLEAR evidence before excluding."""

_ANALYSIS_SYSTEM = """You are a neuroimaging meta-analysis coordinator selecting which analysis/contrast
from a paper should contribute coordinates to the meta-analysis.

Select analyses that meet ALL of these criteria:
- Whole-brain analysis (not ROI-only)
- Task contrast between experimental conditions (not brain-behavior correlation, not resting-state connectivity)
- Reports coordinates in MNI or Talairach space
- Between-group or condition contrast (not within-group only)
- Not a null-effects report

When a paper reports multiple eligible analyses, list all eligible ones.
If no analysis is clearly eligible from the abstract alone, return "uncertain"."""

_ANALYSIS_USER = """\
META-ANALYSIS TOPIC: {topic}
INCLUSION CRITERIA: {inclusion}
EXCLUSION CRITERIA: {exclusion}

PAPER (PMID {pmid}):
{title}
{abstract}

List the analyses/contrasts from this paper that should be included in the meta-analysis.
If the abstract does not describe specific analyses, return "uncertain".

Respond with JSON only:
{{
  "pmid": "{pmid}",
  "eligible_analyses": ["<contrast name 1>", "<contrast name 2>"],
  "excluded_analyses": ["<contrast name>: <reason>"],
  "decision": "include" | "exclude" | "uncertain",
  "reason": "<one sentence>"
}}"""

_SCREEN_USER = """\
INCLUSION CRITERIA: {inclusion}
EXCLUSION CRITERIA: {exclusion}

CANONICAL CRITERION IDS:
{criteria_catalog}

ABSTRACT (PMID {pmid}):
{title}
{abstract}

Screening rule: INCLUDE unless there is CLEAR evidence of an exclusion criterion.
When in doubt → "uncertain" (which is treated as include).
Use only the CANONICAL CRITERION IDS listed above. If none applies, return an empty
criterion_ids list rather than inventing a new ID.

Respond with JSON only:
{{
  "decision": "include" | "exclude" | "uncertain",
  "criterion_ids": ["<canonical criterion_id from the list above>"],
  "evidence_spans": ["<short quote from title or abstract supporting the criterion; replace internal double quotes with single quotes>"],
  "reason": "<one sentence>",
  "confidence": 0.0
}}"""


def _format_criteria_catalog(criteria: List[Dict[str, str]]) -> str:
    if not criteria:
        return "- none"
    return "\n".join(
        f"- {item.get('criterion_id')}: [{item.get('polarity')}] {item.get('text')}"
        for item in criteria
    )


def _as_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, list):
        return [str(value)]
    out: List[str] = []
    for item in value:
        if item is not None and str(item).strip():
            out.append(str(item).strip())
    return out


def _parse_float_0_1(value: Any, default: float) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, score))


def _extract_json_object(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _quoted_list_after_key(raw: str, key: str) -> List[str]:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\[(.*?)\]', raw, flags=re.DOTALL)
    if not match:
        return []
    body = match.group(1)
    return [item.strip() for item in re.findall(r'"([^"\n]{1,300})"', body) if item.strip()]


def _string_after_key(raw: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"\n]{{0,500}})', raw, flags=re.DOTALL)
    return match.group(1).strip() if match else ""


def parse_screening_json(raw: str) -> Dict[str, Any]:
    """Parse strict JSON, with a fallback for common near-JSON model output."""

    text = _extract_json_object(raw)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        decision_match = re.search(r'"decision"\s*:\s*"(include|exclude|uncertain)"', text, flags=re.IGNORECASE)
        if not decision_match:
            raise
        confidence_match = re.search(r'"confidence"\s*:\s*([0-9]*\.?[0-9]+)', text)
        parsed = {
            "decision": decision_match.group(1),
            "criterion_ids": _quoted_list_after_key(text, "criterion_ids"),
            "evidence_spans": _quoted_list_after_key(text, "evidence_spans"),
            "reason": _string_after_key(text, "reason"),
            "confidence": confidence_match.group(1) if confidence_match else None,
            "parse_recovered": True,
        }
    decision = str(parsed.get("decision") or "uncertain").strip().lower()
    if decision not in ("include", "exclude", "uncertain"):
        decision = "uncertain"
    return {
        "decision": decision,
        "criterion_ids": _as_string_list(parsed.get("criterion_ids")),
        "evidence_spans": _as_string_list(parsed.get("evidence_spans")),
        "reason": str(parsed.get("reason") or "").strip(),
        "confidence": _parse_float_0_1(parsed.get("confidence"), 0.5 if decision == "uncertain" else 0.0),
        "parse_recovered": bool(parsed.get("parse_recovered")),
    }


def llm_screen_single(
    pmid: str,
    title: str,
    abstract: str,
    inclusion: str,
    exclusion: str,
    screening_criteria: List[Dict[str, str]],
    client: "genai.Client",
    model: str,
) -> Dict:
    """Screen a single abstract. Returns dict with decision, reason, pmid."""
    title_text = title or ""
    abstract_text = abstract or ""
    if not abstract_text.strip() and not title_text.strip():
        return {
            "pmid": pmid,
            "decision": "uncertain",
            "title": title_text,
            "abstract": abstract_text,
            "criterion_ids": [],
            "evidence_spans": [],
            "reason": "No abstract available.",
            "confidence": 0.0,
        }

    prompt = _SCREEN_SYSTEM + "\n\n" + _SCREEN_USER.format(
        inclusion=inclusion or "(none specified)",
        exclusion=exclusion or "(none specified)",
        criteria_catalog=_format_criteria_catalog(screening_criteria),
        pmid=pmid,
        title=title_text,
        abstract=abstract_text,
    )
    try:
        last_exc: Optional[Exception] = None
        for attempt in range(1, 3):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        temperature=0,
                        max_output_tokens=4096,
                        response_mime_type="application/json",
                    ),
                )
                raw = (getattr(resp, "text", None) or "").strip()
                if not raw:
                    raise ValueError("Empty JSON response from screening model")
                parsed = parse_screening_json(raw)
                return {
                    "pmid": pmid,
                    "decision": parsed["decision"],
                    "title": title_text,
                    "abstract": abstract_text,
                    "criterion_ids": parsed["criterion_ids"],
                    "evidence_spans": parsed["evidence_spans"],
                    "reason": parsed["reason"],
                    "confidence": parsed["confidence"],
                    "parse_recovered": parsed["parse_recovered"],
                }
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    logger.warning(
                        "Screening parse failed for PMID %s on attempt %d/2: %s",
                        pmid,
                        attempt,
                        exc,
                    )
                    time.sleep(0.5)
                    continue
                raise
    except Exception as exc:
        logger.warning("Screening failed for PMID %s: %s", pmid, exc)
        return {
            "pmid": pmid,
            "decision": "uncertain",
            "title": title_text,
            "abstract": abstract_text,
            "criterion_ids": [],
            "evidence_spans": [],
            "reason": f"Error: {exc}",
            "confidence": 0.0,
        }


# ── Analysis/contrast selection ──────────────────────────────────────────


def llm_select_analyses(
    pmid: str,
    title: str,
    abstract: str,
    topic: str,
    inclusion: str,
    exclusion: str,
    model: str,
    client: "genai.Client",
) -> Dict:
    """Select eligible analyses/contrasts from a single paper."""
    title_text = title or ""
    abstract_text = abstract or ""
    if not abstract_text.strip() and not title_text.strip():
        return {
            "pmid": pmid,
            "decision": "uncertain",
            "eligible_analyses": [],
            "excluded_analyses": [],
            "reason": "No abstract available.",
        }

    prompt = _ANALYSIS_SYSTEM + "\n\n" + _ANALYSIS_USER.format(
        topic=topic or "(not specified)",
        inclusion=inclusion or "(none specified)",
        exclusion=exclusion or "(none specified)",
        pmid=pmid,
        title=title_text,
        abstract=abstract_text,
    )
    try:
        for attempt in range(1, 3):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=genai_types.GenerateContentConfig(
                        temperature=0,
                        max_output_tokens=2048,
                        response_mime_type="application/json",
                    ),
                )
                raw = (getattr(resp, "text", None) or "").strip()
                if not raw:
                    raise ValueError("Empty JSON response from analysis-selection model")
                parsed = json.loads(raw)
                decision = str(parsed.get("decision") or "uncertain").strip().lower()
                if decision not in ("include", "exclude", "uncertain"):
                    decision = "uncertain"
                return {
                    "pmid": pmid,
                    "eligible_analyses": parsed.get("eligible_analyses") or [],
                    "excluded_analyses": parsed.get("excluded_analyses") or [],
                    "decision": decision,
                    "reason": str(parsed.get("reason") or ""),
                }
            except Exception as exc:
                if attempt < 2:
                    logger.warning(
                        "Analysis selection parse failed for PMID %s on attempt %d/2: %s",
                        pmid,
                        attempt,
                        exc,
                    )
                    time.sleep(0.5)
                    continue
                raise
    except Exception as exc:
        logger.warning("Analysis selection failed for PMID %s: %s", pmid, exc)
        return {
            "pmid": pmid,
            "decision": "uncertain",
            "eligible_analyses": [],
            "excluded_analyses": [],
            "reason": f"Error: {exc}",
        }


def run_analysis_selection(
    included_abstracts: List[Dict],
    topic: str,
    inclusion: str,
    exclusion: str,
    model: str,
    client: "genai.Client",
    output_dir: Path,
) -> List[Dict]:
    """Run analysis/contrast selection for all included papers.

    Parameters
    ----------
    included_abstracts : list of dicts with keys ``pmid``, ``title``, ``abstract``
    topic, inclusion, exclusion : meta-analysis criteria strings
    model : Gemini model name
    client : google.genai Client
    output_dir : directory to write ``analysis_selection.jsonl``

    Returns
    -------
    List of analysis selection result dicts.
    """
    results: List[Dict] = []
    total = len(included_abstracts)
    for idx, paper in enumerate(included_abstracts, 1):
        result = llm_select_analyses(
            pmid=paper["pmid"],
            title=paper.get("title", ""),
            abstract=paper.get("abstract", ""),
            topic=topic,
            inclusion=inclusion,
            exclusion=exclusion,
            model=model,
            client=client,
        )
        results.append(result)
        if idx % 10 == 0:
            logger.info("  Analysis selection %d/%d …", idx, total)

    # Persist
    sel_path = output_dir / "analysis_selection.jsonl"
    with sel_path.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    logger.info("Analysis selection written to %s", sel_path)

    return results


# ── Evaluation ────────────────────────────────────────────────────────────────


def evaluate(
    candidate_pmids: List[str],
    included_pmids: set,
    gt_pmids: set,
) -> Dict:
    candidate_set = set(candidate_pmids)
    included_set = set(included_pmids)

    # Candidate recall: did esearch retrieve the GT papers at all?
    candidate_recall = len(candidate_set & gt_pmids) / len(gt_pmids) if gt_pmids else 0.0

    # Screening metrics
    tp = included_set & gt_pmids
    precision = len(tp) / len(included_set) if included_set else 0.0
    recall = len(tp) / len(gt_pmids) if gt_pmids else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )

    return {
        "n_gt": len(gt_pmids),
        "n_candidates": len(candidate_set),
        "candidate_recall": round(candidate_recall, 4),
        "n_included_by_llm": len(included_set),
        "n_tp": len(tp),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


# ── Main pipeline ─────────────────────────────────────────────────────────────


def run_pipeline(
    meta_pmid: str,
    data_dir: Path,
    max_candidates: int,
    llm_model: str,
    output_dir: Path,
    api_key_pubmed: Optional[str],
    use_llm_reformulation: bool,
    adapter_only: bool,
    candidate_source_mode: str = "auto",
    min_candidate_recall_to_screen: Optional[float] = None,
    mixed_pool_noise_ratio: int = 5,
    mixed_pool_seed: int = 0,
    skip_analysis_selection: bool = False,
) -> Dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 0: Load criteria and GT
    logger.info("Loading meta row for PMID %s", meta_pmid)
    row = load_meta_row(data_dir, meta_pmid)
    inclusion = (row.get("inclusion") or "").strip()
    exclusion = (row.get("exclusion") or "").strip()
    screening_criteria = build_screening_criteria(inclusion, exclusion)
    raw_search = (row.get("search") or "").strip()
    dates_str = (row.get("dates") or "").strip()
    topic = (row.get("topic") or meta_pmid).strip()

    logger.info("Topic: %s", topic)
    logger.info("Raw search: %s", raw_search[:200])

    gt_pmids = load_ground_truth(data_dir, meta_pmid)
    logger.info("Ground truth: %d included studies", len(gt_pmids))

    dispatch = resolve_case_dispatch(row, data_dir)
    logger.info(
        "Official route: %s (%s)",
        dispatch["official_route"],
        dispatch["recommended_workflow"],
    )
    logger.info("Dispatch reason: %s", dispatch["dispatch_reason"])

    if dispatch["official_route"] == "nimads_brainmap":
        nimads_reproduction = ensure_nimads_reproduction_adapter(
            data_dir=data_dir,
            nimads_assets=dispatch["nimads_assets"],
        )
        dispatch["nimads_reproduction"] = nimads_reproduction
        dispatch["official_entrypoint"] = {
            "mode": "official_merged_nimads_runner",
            "runner_script": str(
                _repo_root() / "external" / "neurometabench" / "scripts" / "run_meta_analyses.py"
            ),
            "example_command": nimads_reproduction.get("official_runner_command"),
        }
        if nimads_reproduction.get("merged_studyset"):
            dispatch["nimads_assets"]["merged_studyset"] = nimads_reproduction["merged_studyset"]
        if nimads_reproduction.get("merged_annotation"):
            dispatch["nimads_assets"]["merged_annotation"] = nimads_reproduction["merged_annotation"]
        logger.info(
            "NiMADS reproduction adapter status: %s",
            nimads_reproduction.get("merge_status"),
        )
        if nimads_reproduction.get("error"):
            logger.warning("NiMADS reproduction adapter error: %s", nimads_reproduction["error"])

    adapter_manifest = build_case_adapter_manifest(
        row=row,
        data_dir=data_dir,
        dispatch=dispatch,
        gt_pmids=gt_pmids,
    )
    adapter_path = output_dir / "case_adapter.json"
    adapter_path.write_text(json.dumps(adapter_manifest, indent=2, ensure_ascii=False))
    logger.info("Case adapter written to %s", adapter_path)

    if adapter_only:
        metrics = {
            "meta_pmid": meta_pmid,
            "topic": topic,
            "official_route": dispatch["official_route"],
            "recommended_workflow": dispatch["recommended_workflow"],
            "dispatch_reason": dispatch["dispatch_reason"],
            "adapter_only": True,
            "screening_skipped": True,
            "n_gt": len(gt_pmids),
        }
        if dispatch.get("nimads_reproduction") is not None:
            metrics["nimads_reproduction"] = dispatch["nimads_reproduction"]
            metrics["official_entrypoint"] = dispatch.get("official_entrypoint")
        results_path = output_dir / "results.json"
        results_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
        logger.info("Results written to %s", results_path)
        return metrics

    if dispatch["official_route"] == "nimads_brainmap":
        nimads_reproduction = dispatch.get("nimads_reproduction", {})
        metrics = {
            "meta_pmid": meta_pmid,
            "topic": topic,
            "official_route": dispatch["official_route"],
            "recommended_workflow": dispatch["recommended_workflow"],
            "dispatch_reason": dispatch["dispatch_reason"],
            "screening_skipped": True,
            "n_gt": len(gt_pmids),
            "n_nimads_studies": dispatch["nimads_assets"]["n_studies"],
            "n_nimads_analyses": dispatch["nimads_assets"]["n_analyses"],
            "reproduction_ready": bool(
                nimads_reproduction.get("merged_studyset") and nimads_reproduction.get("merged_annotation")
            ),
            "nimads_reproduction": nimads_reproduction,
            "official_entrypoint": dispatch.get("official_entrypoint"),
        }
        results_path = output_dir / "results.json"
        results_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
        logger.info("Results written to %s", results_path)
        logger.info(
            "Skipping abstract-screening workflow for NiMADS/BrainMap case; use official NiMADS assets instead."
        )
        return metrics

    # Check for closed-world candidate set (e.g. Social, Dementia benchmarks)
    closed_world = load_closed_world_candidates(data_dir, meta_pmid)
    candidate_pmids: List[str] = []
    candidate_source = ""
    pubmed_query = ""
    retrieval_details: Dict[str, Any] = {}
    source_lists: List[Tuple[str, List[str]]] = []

    if candidate_source_mode == "mixed_pool":
        candidate_pmids = load_mixed_pool_candidates(
            data_dir,
            meta_pmid,
            noise_ratio=mixed_pool_noise_ratio,
            seed=mixed_pool_seed,
            max_total=max_candidates,
        )
        candidate_source = f"mixed_pool_gt_noise_{mixed_pool_noise_ratio}:1"
        pubmed_query = "(mixed GT + random non-GT candidate pool)"
        retrieval_details = {
            "mixed_pool_noise_ratio": mixed_pool_noise_ratio,
            "mixed_pool_seed": mixed_pool_seed,
        }

    if closed_world and candidate_source_mode in {"auto", "closed_world", "union"}:
        logger.info(
            "Using closed-world candidates from all_studies.csv: %d papers",
            len(closed_world),
        )
        if candidate_source_mode == "union":
            source_lists.append(("closed_world_all_studies", closed_world))
        else:
            candidate_pmids = closed_world
            candidate_source = "closed_world_all_studies"
            pubmed_query = "(closed-world candidates from all_studies.csv)"
    if (
        not candidate_pmids
        and candidate_source_mode in {"auto", "union"}
        and dispatch["official_route"] == "pmc_fulltext"
    ):
        logger.info("Loading candidates from PMC full-text reference list")
        candidate_pmids, retrieval_details = load_pmc_reference_candidates(
            data_dir=data_dir,
            meta_pmid=meta_pmid,
            row=row,
            api_key=api_key_pubmed,
        )
        candidate_source = retrieval_details.get("candidate_source", "pmc_reference_list")
        pubmed_query = f"(PMC reference list for PMCID {row.get('pmcid', '')})"
        if candidate_source_mode == "union":
            if candidate_pmids:
                source_lists.append((candidate_source, candidate_pmids))
            candidate_pmids = []
            candidate_source = ""
            pubmed_query = ""
        elif len(candidate_pmids) < PMC_MIN_CANDIDATES:
            logger.warning(
                "PMC reference route yielded %d candidates; falling back to PubMed metadata search",
                len(candidate_pmids),
            )
            candidate_pmids = []

    use_pubmed_metadata = candidate_source_mode in {"pubmed", "union"} or (
        candidate_source_mode == "auto" and not candidate_pmids
    )
    if use_pubmed_metadata:
        # Step 1: Query reformulation. Only initialize Gemini here when the
        # user explicitly requests LLM reformulation; screening-model setup is
        # deferred until after the retrieval gate.
        reformulation_client = None
        if use_llm_reformulation:
            gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if genai is None:
                raise RuntimeError("google-genai package is not installed. Run: pip install google-genai")
            reformulation_client = genai.Client(api_key=gemini_key)
        logger.info("Reformulating query (use_llm=%s)", use_llm_reformulation)
        pubmed_query = reformulate_query(
            raw_search,
            client=reformulation_client,
            model=llm_model,
            use_llm=use_llm_reformulation,
        )
        logger.info("PubMed query: %s", pubmed_query[:300])

        # Validate query returns results; fall back to simpler topic-based query if not
        hit_count = validate_esearch_count(pubmed_query, api_key_pubmed)
        if hit_count == 0:
            logger.warning("Reformulated query returned 0 hits; trying topic-based fallback")
            modality = (row.get("modality") or "fMRI").strip()
            pubmed_query = f'("{topic}"[Title/Abstract]) AND ("{modality}"[Title/Abstract])'
            hit_count = validate_esearch_count(pubmed_query, api_key_pubmed)
            logger.info("Fallback query hit count: %d", hit_count)
            logger.info("Fallback PubMed query: %s", pubmed_query)

        # Step 2: PubMed metadata retrieval
        mindate, maxdate = _parse_date_range(dates_str)

        # Auto-derive maxdate from meta-analysis year if not set by dates field
        if maxdate is None:
            meta_year = (row.get("year") or "").strip()
            if meta_year.isdigit():
                maxdate = f"{meta_year}/12/31"
                logger.info("Auto-derived maxdate=%s from meta-analysis year", maxdate)

        logger.info("Date filter: mindate=%s maxdate=%s", mindate, maxdate)
        all_pmids = pubmed_esearch(
            pubmed_query,
            retmax=ESEARCH_RETMAX,
            mindate=mindate,
            maxdate=maxdate,
            api_key=api_key_pubmed,
        )
        # Cap candidates
        pubmed_pmids = all_pmids[:max_candidates]
        if candidate_source_mode == "union":
            source_lists.append(("pubmed_metadata", pubmed_pmids))
            seen_pmids: set = set()
            union_pmids: List[str] = []
            union_sources: List[str] = []
            for source_name, source_pmids in source_lists:
                if source_name not in union_sources:
                    union_sources.append(source_name)
                for pmid in source_pmids:
                    if pmid not in seen_pmids:
                        seen_pmids.add(pmid)
                        union_pmids.append(pmid)
            candidate_pmids = union_pmids[:max_candidates]
            candidate_source = "union:" + "+".join(union_sources)
            retrieval_details["source_counts"] = {
                source_name: len(source_pmids) for source_name, source_pmids in source_lists
            }
        else:
            candidate_pmids = pubmed_pmids
            candidate_source = "pubmed_metadata"
        logger.info(
            "Candidates: %d (capped at %d from %d total hits)",
            len(candidate_pmids),
            max_candidates,
            len(all_pmids),
        )
    # Quick candidate recall before expensive screening
    pre_screen_recall = (
        len(set(candidate_pmids) & gt_pmids) / len(gt_pmids) if gt_pmids else 0.0
    )
    logger.info("Pre-screening candidate recall: %.3f", pre_screen_recall)
    if min_candidate_recall_to_screen is not None and pre_screen_recall < min_candidate_recall_to_screen:
        metrics = evaluate(candidate_pmids, [], gt_pmids)
        metrics.update(
            {
                "meta_pmid": meta_pmid,
                "topic": topic,
                "official_route": dispatch["official_route"],
                "recommended_workflow": dispatch["recommended_workflow"],
                "dispatch_reason": dispatch["dispatch_reason"],
                "candidate_source": candidate_source,
                "candidate_source_mode": candidate_source_mode,
                "pubmed_query": pubmed_query,
                "screening_skipped": True,
                "skip_reason": "candidate_recall_below_gate",
                "min_candidate_recall_to_screen": min_candidate_recall_to_screen,
                "retrieval_details": retrieval_details,
            }
        )
        results_path = output_dir / "results.json"
        results_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
        logger.warning(
            "Skipping screening: candidate_recall %.3f < gate %.3f",
            pre_screen_recall,
            min_candidate_recall_to_screen,
        )
        return metrics

    # Initialise Gemini only after retrieval clears the gate.
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if genai is None:
        raise RuntimeError("google-genai package is not installed. Run: pip install google-genai")
    client = genai.Client(api_key=gemini_key)

    # Step 3: efetch abstracts
    logger.info("Fetching abstracts for %d candidates …", len(candidate_pmids))
    abstracts = efetch_abstracts(candidate_pmids, api_key=api_key_pubmed)
    logger.info("Fetched %d abstracts", len(abstracts))

    # Step 4: LLM screening
    logger.info("Screening %d abstracts with %s …", len(candidate_pmids), llm_model)
    screening_results: List[Dict] = []
    included_pmids: set = set()
    for idx, pmid in enumerate(candidate_pmids, 1):
        info = abstracts.get(pmid, {})
        result = llm_screen_single(
            pmid=pmid,
            title=info.get("title", ""),
            abstract=info.get("abstract", ""),
            inclusion=inclusion,
            exclusion=exclusion,
            screening_criteria=screening_criteria,
            client=client,
            model=llm_model,
        )
        screening_results.append(result)
        # uncertain is treated as include (recall-biased)
        if result["decision"] in ("include", "uncertain"):
            included_pmids.add(pmid)
        if idx % 50 == 0:
            logger.info("  Screened %d/%d …", idx, len(candidate_pmids))

    logger.info(
        "Screening complete: %d include/uncertain, %d exclude",
        len(included_pmids),
        len(candidate_pmids) - len(included_pmids),
    )

    n_with_eligible: Optional[int] = None
    if skip_analysis_selection:
        logger.info("Skipping analysis selection by request; Layer A screening outputs are complete.")
    else:
        # Build list of included abstracts for downstream stages
        included_abstracts: List[Dict] = []
        for pmid in included_pmids:
            info = abstracts.get(pmid, {})
            included_abstracts.append({
                "pmid": pmid,
                "title": info.get("title", ""),
                "abstract": info.get("abstract", ""),
            })

        # Stage 5: Analysis/contrast selection for included papers
        logger.info("Stage 5: Analysis selection for %d included papers", len(included_abstracts))
        analysis_results = run_analysis_selection(
            included_abstracts=included_abstracts,
            topic=topic,
            inclusion=inclusion,
            exclusion=exclusion,
            model=llm_model,
            client=client,
            output_dir=output_dir,
        )
        n_with_eligible = sum(1 for r in analysis_results if r.get("eligible_analyses"))
        logger.info("Analysis selection: %d/%d papers have eligible analyses", n_with_eligible, len(included_abstracts))

    # Step 6: Evaluate
    metrics = evaluate(candidate_pmids, included_pmids, gt_pmids)
    metrics["meta_pmid"] = meta_pmid
    metrics["topic"] = topic
    metrics["llm_model"] = llm_model
    metrics["pubmed_query"] = pubmed_query
    metrics["official_route"] = dispatch["official_route"]
    metrics["recommended_workflow"] = dispatch["recommended_workflow"]
    metrics["dispatch_reason"] = dispatch["dispatch_reason"]
    metrics["candidate_source"] = candidate_source
    metrics["candidate_source_mode"] = candidate_source_mode
    metrics["retrieval_details"] = retrieval_details
    metrics["analysis_selection_skipped"] = skip_analysis_selection
    if n_with_eligible is not None:
        metrics["n_with_eligible_analyses"] = n_with_eligible

    # Persist outputs
    results_path = output_dir / "results.json"
    results_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    logger.info("Results written to %s", results_path)

    screening_path = output_dir / "screening_decisions.jsonl"
    with screening_path.open("w", encoding="utf-8") as fh:
        for r in screening_results:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    logger.info("Screening decisions written to %s", screening_path)

    # Missed GT papers (for debugging)
    missed = gt_pmids - set(included_pmids)
    missed_in_candidates = missed & set(candidate_pmids)
    missed_not_retrieved = missed - set(candidate_pmids)
    debug = {
        "missed_by_screening": sorted(missed_in_candidates),
        "missed_not_retrieved_by_candidates": sorted(missed_not_retrieved),
    }
    debug_path = output_dir / "missed_gt.json"
    debug_path.write_text(json.dumps(debug, indent=2, ensure_ascii=False))

    return metrics


def _batch_summary_row(
    metrics: Dict[str, Any],
    meta_pmid: str,
    case_output_dir: Path,
    status: str,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "meta_pmid": meta_pmid,
        "topic": metrics.get("topic"),
        "official_route": metrics.get("official_route"),
        "recommended_workflow": metrics.get("recommended_workflow"),
        "status": status,
        "candidate_source": metrics.get("candidate_source"),
        "candidate_source_mode": metrics.get("candidate_source_mode"),
        "n_gt": metrics.get("n_gt"),
        "n_candidates": metrics.get("n_candidates"),
        "candidate_recall": metrics.get("candidate_recall"),
        "recall": metrics.get("recall"),
        "f1": metrics.get("f1"),
        "screening_skipped": metrics.get("screening_skipped", False),
        "skip_reason": metrics.get("skip_reason"),
        "error": error,
        "output_dir": str(case_output_dir),
    }


def _write_batch_summary(output_dir: Path, rows: List[Dict[str, Any]], summary: Dict[str, Any]) -> None:
    summary_path = output_dir / "batch_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    rows_path = output_dir / "batch_results.jsonl"
    with rows_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    csv_path = output_dir / "batch_results.csv"
    fieldnames = [
        "meta_pmid",
        "topic",
        "official_route",
        "recommended_workflow",
        "status",
        "candidate_source",
        "candidate_source_mode",
        "n_gt",
        "n_candidates",
        "candidate_recall",
        "recall",
        "f1",
        "screening_skipped",
        "skip_reason",
        "error",
        "output_dir",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def run_route_batch(
    route: str,
    data_dir: Path,
    output_dir: Path,
    max_candidates: int,
    llm_model: str,
    api_key_pubmed: Optional[str],
    use_llm_reformulation: bool,
    adapter_only: bool,
    candidate_source_mode: str,
    min_candidate_recall_to_screen: Optional[float],
    mixed_pool_noise_ratio: int,
    mixed_pool_seed: int,
    skip_analysis_selection: bool,
    batch_limit: Optional[int],
    skip_existing: bool,
) -> Dict[str, Any]:
    """Run the adapter/screening workflow across all cases assigned to one route."""
    rows = load_all_meta_rows(data_dir)
    pmids = [
        (row.get("pmid") or "").strip()
        for row in rows
        if resolve_case_dispatch(row, data_dir)["official_route"] == route
    ]
    pmids = [pmid for pmid in pmids if pmid]
    if batch_limit is not None:
        pmids = pmids[:batch_limit]

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Batch route %s: %d case(s)", route, len(pmids))

    rows_out: List[Dict[str, Any]] = []
    ok_count = 0
    error_count = 0
    skipped_existing_count = 0

    for idx, meta_pmid in enumerate(pmids, 1):
        case_output_dir = output_dir / meta_pmid
        results_path = case_output_dir / "results.json"
        logger.info("Batch [%d/%d] meta_pmid=%s", idx, len(pmids), meta_pmid)

        if skip_existing and results_path.exists():
            metrics = json.loads(results_path.read_text(encoding="utf-8"))
            rows_out.append(
                _batch_summary_row(
                    metrics=metrics,
                    meta_pmid=meta_pmid,
                    case_output_dir=case_output_dir,
                    status="skipped_existing",
                )
            )
            skipped_existing_count += 1
            continue

        try:
            metrics = run_pipeline(
                meta_pmid=meta_pmid,
                data_dir=data_dir,
                max_candidates=max_candidates,
                llm_model=llm_model,
                output_dir=case_output_dir,
                api_key_pubmed=api_key_pubmed,
                use_llm_reformulation=use_llm_reformulation,
                adapter_only=adapter_only,
                candidate_source_mode=candidate_source_mode,
                min_candidate_recall_to_screen=min_candidate_recall_to_screen,
                mixed_pool_noise_ratio=mixed_pool_noise_ratio,
                mixed_pool_seed=mixed_pool_seed,
                skip_analysis_selection=skip_analysis_selection,
            )
            rows_out.append(
                _batch_summary_row(
                    metrics=metrics,
                    meta_pmid=meta_pmid,
                    case_output_dir=case_output_dir,
                    status="ok",
                )
            )
            ok_count += 1
        except Exception as exc:
            case_output_dir.mkdir(parents=True, exist_ok=True)
            error_payload = {
                "meta_pmid": meta_pmid,
                "official_route": route,
                "status": "error",
                "error": str(exc),
            }
            (case_output_dir / "error.json").write_text(
                json.dumps(error_payload, indent=2, ensure_ascii=False)
            )
            rows_out.append(
                _batch_summary_row(
                    metrics=error_payload,
                    meta_pmid=meta_pmid,
                    case_output_dir=case_output_dir,
                    status="error",
                    error=str(exc),
                )
            )
            error_count += 1
            logger.exception("Batch case failed for meta_pmid=%s", meta_pmid)

    summary = {
        "route": route,
        "n_cases": len(pmids),
        "ok": ok_count,
        "errors": error_count,
        "skipped_existing": skipped_existing_count,
        "adapter_only": adapter_only,
        "llm_model": llm_model,
        "output_dir": str(output_dir),
        "results": rows_out,
    }
    _write_batch_summary(output_dir, rows_out, summary)
    return summary


# ── CLI ───────────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(
        description="neurometabench PubMed screening benchmark"
    )
    ap.add_argument(
        "--meta-pmid",
        help="PMID of the meta-analysis to benchmark (e.g. 36100907)",
    )
    ap.add_argument(
        "--batch-route",
        choices=["nimads_brainmap", "pmc_fulltext", "pubmed_metadata"],
        default=None,
        help="Run all cases assigned to one official route and write a batch summary.",
    )
    ap.add_argument(
        "--data-dir",
        type=Path,
        default=Path("external/neurometabench/data"),
        help="Directory containing meta_datasets.csv and included_studies.csv",
    )
    ap.add_argument(
        "--max-candidates",
        type=int,
        default=500,
        help="Cap on number of esearch candidates to screen (default: 500)",
    )
    ap.add_argument(
        "--llm-model",
        default="gemini-2.5-pro",
        help="Gemini model for screening (default: gemini-2.5-pro)",
    )
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to write results (default: /tmp/neurometabench_results/<meta-pmid>)",
    )
    ap.add_argument(
        "--pubmed-api-key",
        default=os.environ.get("PUBMED_API_KEY"),
        help="NCBI API key (raises rate limit from 3 to 10 req/s)",
    )
    ap.add_argument(
        "--use-llm-reformulation",
        action="store_true",
        default=False,
        help="Use LLM for query reformulation instead of rule-based heuristics",
    )
    ap.add_argument(
        "--candidate-source",
        choices=["auto", "pubmed", "closed_world", "mixed_pool", "union"],
        default="auto",
        help=(
            "Candidate source override. auto preserves official routing; pubmed forces "
            "metadata search; closed_world uses all_studies.csv only; mixed_pool uses "
            "GT plus random non-GT PMIDs; union fuses closed-world/PMC/PubMed candidates before screening."
        ),
    )
    ap.add_argument(
        "--mixed-pool-noise-ratio",
        type=int,
        default=5,
        help="For --candidate-source mixed_pool, number of random non-GT candidates per GT PMID.",
    )
    ap.add_argument(
        "--mixed-pool-seed",
        type=int,
        default=0,
        help="Deterministic seed for --candidate-source mixed_pool.",
    )
    ap.add_argument(
        "--min-candidate-recall-to-screen",
        type=float,
        default=None,
        help="Skip LLM screening when pre-screening candidate_recall is below this gate.",
    )
    ap.add_argument(
        "--adapter-only",
        action="store_true",
        default=False,
        help="Only resolve and persist the official benchmark adapter route; skip screening.",
    )
    ap.add_argument(
        "--skip-analysis-selection",
        action="store_true",
        default=False,
        help="Run Layer A screening only; skip downstream analysis/contrast selection.",
    )
    ap.add_argument(
        "--batch-limit",
        type=int,
        default=None,
        help="Optional limit on number of cases when --batch-route is used.",
    )
    ap.add_argument(
        "--skip-existing",
        action="store_true",
        default=False,
        help="When running --batch-route, skip case directories that already contain results.json.",
    )
    args = ap.parse_args()

    if args.batch_route:
        output_dir = args.output_dir or Path(f"/tmp/neurometabench_batch_{args.batch_route}")
        summary = run_route_batch(
            route=args.batch_route,
            data_dir=args.data_dir,
            output_dir=output_dir,
            max_candidates=args.max_candidates,
            llm_model=args.llm_model,
            api_key_pubmed=args.pubmed_api_key,
            use_llm_reformulation=args.use_llm_reformulation,
            adapter_only=args.adapter_only,
            candidate_source_mode=args.candidate_source,
            min_candidate_recall_to_screen=args.min_candidate_recall_to_screen,
            mixed_pool_noise_ratio=args.mixed_pool_noise_ratio,
            mixed_pool_seed=args.mixed_pool_seed,
            skip_analysis_selection=args.skip_analysis_selection,
            batch_limit=args.batch_limit,
            skip_existing=args.skip_existing,
        )
        print(json.dumps(summary, indent=2))
        print()
        print(
            f"ℹ  Batch route {args.batch_route} complete. "
            f"Summary files are in {output_dir}."
        )
        return

    if not args.meta_pmid:
        ap.error("--meta-pmid is required unless --batch-route is set.")

    output_dir = args.output_dir or Path(f"/tmp/neurometabench_results/{args.meta_pmid}")

    metrics = run_pipeline(
        meta_pmid=args.meta_pmid,
        data_dir=args.data_dir,
        max_candidates=args.max_candidates,
        llm_model=args.llm_model,
        output_dir=output_dir,
        api_key_pubmed=args.pubmed_api_key,
        use_llm_reformulation=args.use_llm_reformulation,
        adapter_only=args.adapter_only,
        candidate_source_mode=args.candidate_source,
        min_candidate_recall_to_screen=args.min_candidate_recall_to_screen,
        mixed_pool_noise_ratio=args.mixed_pool_noise_ratio,
        mixed_pool_seed=args.mixed_pool_seed,
        skip_analysis_selection=args.skip_analysis_selection,
    )

    print(json.dumps(metrics, indent=2))

    # Diagnostic guidance
    print()
    if metrics.get("screening_skipped") and metrics.get("skip_reason") == "candidate_recall_below_gate":
        print(
            "ℹ  Screening skipped by retrieval gate: "
            f"candidate_recall={metrics.get('candidate_recall')} "
            f"< min_candidate_recall_to_screen={metrics.get('min_candidate_recall_to_screen')}."
        )
    elif "candidate_recall" in metrics and "recall" in metrics:
        cr = metrics["candidate_recall"]
        sr = metrics["recall"]
        if cr < 0.5:
            print("⚠  candidate_recall < 0.5: retrieval/source coverage is the bottleneck.")
            print("   → Fix: improve the candidate source or query route")
        elif sr < 0.5:
            print("⚠  screen_recall < 0.5 despite good candidate_recall: LLM screening is the bottleneck.")
            print("   → Fix: improve the screening prompt or switch to a stronger model")
        else:
            print("✓  Both candidate_recall and screen_recall > 0.5 — viable for workflow registration.")
    else:
        print(
            "ℹ  This case was routed to a non-screening benchmark track. "
            "See case_adapter.json for the recommended official entrypoint."
        )


if __name__ == "__main__":
    main()
