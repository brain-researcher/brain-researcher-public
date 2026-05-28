#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Dict, List

import nibabel as nib
import numpy as np
import pandas as pd
from nilearn import datasets, image
from nilearn.maskers import NiftiLabelsMasker
from sklearn.linear_model import Ridge

DEFAULT_ROOT = Path("data/openneuro_glmfitlins/stat_maps")
DEFAULT_OUT = Path("outputs/forward_encoding_v2")
ONVOC_CONCEPTS = Path("data/ontologies/onvoc/onvoc_concepts.json")
ONVOC_RELATIONSHIPS = Path("data/ontologies/onvoc/onvoc_relationships.json")
DEFAULT_KG_FEATURE_MAP = Path("outputs/forward_encoding_v2/kg_feature_map.json")

ALLOWED_NODE_TYPES = {"Concept", "Construct", "Task", "Condition", "Contrast"}

KG_ALLOWED_PREFIXES = ("task:", "contrast:", "tsk_", "trm_", "cnt_", "con_", "ONVOC_")
KG_BLOCK_PREFIXES = ("neurostore_task:", "4:")

CANONICAL_TASK = {
    "abstractconcretejudgment": "abstract concrete judgment task",
    "antisaccadetaskwithfixedorder": "antisaccade task",
    "balloonanalogrisktask": "balloon analog risk task",
    "cmp": "language comprehension task",
    "covertverbgeneration": "language production task",
    "deterministicclassification": "probabilistic learning task",
    "discounting": "decision making task",
    "dis": "moral judgment task",
    "ec": "emotion regulation task",
    "emotionregulation": "emotion regulation task",
    "emotionalregulation": "emotion regulation task",
    "emotionalfaces": "emotional faces task",
    "facerecognition": "face recognition task",
    "figure2backwith1backlures": "n-back task",
    "fingerfootlips": "finger tapping task",
    "flanker": "stroop task",
    "letter0backtask": "n-back task",
    "letter1backtask": "n-back task",
    "letter2backtask": "n-back task",
    "mixedeventrelatedprobe": "probabilistic learning task",
    "mixedgamblestask": "decision making task",
    "music": "auditory perception task",
    "nonmusic": "auditory perception task",
    "objectviewing": "object viewing task",
    "overtverbgeneration": "language production task",
    "overtwordrepetition": "language production task",
    "passiveimageviewing": "passive image viewing task",
    "probabilisticclassification": "probabilistic learning task",
    "reversalweatherprediction": "probabilistic learning task",
    "stopsignal": "stop-signal task",
    "conditionalstopsignal": "stop-signal task",
    "theoryofmindwithmanualresponse": "theory of mind task",
    "trainedhandtrainedsequence": "motor sequence learning task",
    "trainedhanduntrainedsequence": "motor sequence learning task",
    "untrainedhandtrainedsequence": "motor sequence learning task",
    "untrainedhanduntrainedsequence": "motor sequence learning task",
    "weatherprediction": "probabilistic learning task",
}

# Raw KG-style task->construct mapping from prior MCP task_to_concept_mapping runs.
CONCEPTS_BY_TASK = {
    "n-back task": ["Cognitive Load", "Working Memory"],
    "antisaccade task": ["Cognitive Load", "Cognitive Inhibition"],
    "balloon analog risk task": ["Cognitive Load", "Decision Making"],
    "decision making task": ["Cognitive Load", "Decision Making"],
    "abstract concrete judgment task": ["Cognitive Load", "Language"],
    "emotional faces task": ["Emotion Regulation", "Perception"],
    "face recognition task": ["Social Cognition", "Perception"],
    "object viewing task": ["Perception"],
    "passive image viewing task": ["Perception"],
    "moral judgment task": ["Moral Reasoning", "Decision Making", "Social Cognition"],
    "language comprehension task": ["Language", "Perception"],
    "language production task": ["Language", "Motor Control"],
    "theory of mind task": ["Social Cognition"],
    "auditory perception task": ["Perception"],
    "motor sequence learning task": ["Movement", "Learning", "Motor Control"],
    "finger tapping task": ["Movement", "Motor Control"],
    "stop-signal task": ["Cognitive Inhibition", "Cognitive Load"],
    "stroop task": ["Cognitive Inhibition", "Cognitive Load"],
    "probabilistic learning task": ["Learning", "Decision Making", "Cognitive Load"],
    "emotion regulation task": ["Emotion Regulation", "Cognitive Inhibition"],
}

TASK_CA_IDS = {
    "n-back task": "tsk_4a57abb949bcd",
    "stop-signal task": "tsk_4a57abb949e1a",
    "stroop task": "tsk_4a57abb949e27",
    "finger tapping task": "tsk_4a57abb949b2f",
}

# Lexical cues to deepen construct features from task/contrast text.
TOKEN_TO_CONCEPTS = {
    "back": ["Working Memory", "Cognitive Load"],
    "nback": ["Working Memory", "Cognitive Load"],
    "letter": ["Language", "Perception"],
    "word": ["Language"],
    "verb": ["Language", "Motor Control"],
    "face": ["Social Cognition", "Perception", "Emotion"],
    "emotion": ["Emotion Regulation", "Emotion"],
    "stroop": ["Cognitive Inhibition", "Executive Function"],
    "incongruent": ["Cognitive Inhibition"],
    "congruent": ["Cognitive Inhibition"],
    "stop": ["Cognitive Inhibition", "Motor Control"],
    "go": ["Movement", "Motor Control"],
    "signal": ["Cognitive Inhibition"],
    "finger": ["Movement", "Motor Control"],
    "foot": ["Movement", "Motor Control"],
    "lips": ["Movement", "Motor Control"],
    "motor": ["Motor Control", "Movement"],
    "movement": ["Movement"],
    "music": ["Perception"],
    "auditory": ["Perception"],
    "image": ["Perception"],
    "object": ["Perception"],
    "decision": ["Decision Making"],
    "risk": ["Decision Making"],
    "reward": ["Decision Making", "Learning"],
    "learning": ["Learning"],
    "probabilistic": ["Learning", "Decision Making"],
    "moral": ["Moral Reasoning", "Social Cognition"],
    "theory": ["Social Cognition"],
    "mind": ["Social Cognition"],
    "abstract": ["Language"],
    "concrete": ["Language"],
    "memory": ["Working Memory", "Memory"],
}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


def canonicalize_task(task_raw: str) -> str:
    key = task_raw.strip().lower()
    return CANONICAL_TASK.get(key, key.replace("_", " "))


def lexical_tokens(*texts: str) -> list[str]:
    token_set: set[str] = set()
    for txt in texts:
        if not txt:
            continue
        base = slugify(txt)
        dense = base.replace("_", "")
        for token in TOKEN_TO_CONCEPTS:
            if token in dense:
                token_set.add(token)
        for token in base.split("_"):
            if len(token) >= 3:
                token_set.add(token)
    return sorted(token_set)


def parse_contrast_signature(contrast: str) -> tuple[list[str], list[str], str, str]:
    cslug = slugify(contrast)
    if not cslug:
        return ["unknown"], [], "single", "1"

    parts = [p for p in re.split(r"v+", cslug) if p]
    if len(parts) <= 1:
        pos = [parts[0] if parts else cslug]
        neg: list[str] = []
        polarity = "single"
        arity = "1"
    elif len(parts) == 2:
        pos = [parts[0]]
        neg = [parts[1]]
        polarity = "pos_vs_neg"
        arity = "2"
    else:
        pos = [parts[0]]
        neg = parts[1:]
        polarity = "pos_vs_multi"
        arity = "multi"
    return pos, neg, polarity, arity


def filter_kg_ids(ids: list[str]) -> list[str]:
    out: list[str] = []
    for raw in ids:
        kid = str(raw).strip()
        if not kid:
            continue
        if any(kid.startswith(p) for p in KG_BLOCK_PREFIXES):
            continue
        if any(kid.startswith(p) for p in KG_ALLOWED_PREFIXES):
            out.append(kid)
    # preserve order unique
    seen = set()
    return [x for x in out if not (x in seen or seen.add(x))]


def load_kg_feature_map(path: Path) -> dict[tuple[str, str], dict]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    items = data.get("items", [])
    out: dict[tuple[str, str], dict] = {}
    for it in items:
        task_raw = str(it.get("task_raw", "")).strip().lower()
        contrast = str(it.get("contrast", "")).strip().lower()
        if not task_raw or not contrast:
            continue
        it = dict(it)
        it["kg_feature_ids"] = filter_kg_ids(list(it.get("kg_feature_ids", []) or []))
        it["onvoc_ids"] = [x for x in filter_kg_ids(list(it.get("onvoc_ids", []) or [])) if x.startswith("ONVOC_")]
        out[(task_raw, contrast)] = it
    return out


def list_stat_maps(root: Path) -> pd.DataFrame:
    rows: List[dict] = []
    patt = re.compile(r"contrast-(.+?)_stat-z_statmap\.nii\.gz$")

    for p in root.rglob("*stat-z_statmap.nii.gz"):
        parts = p.parts
        if "stat_maps" not in parts:
            continue
        try:
            base_idx = parts.index("stat_maps") + 1
            dataset = parts[base_idx]
            task_part = parts[base_idx + 1]
        except Exception:
            continue

        if not task_part.startswith("task-"):
            continue

        task_raw = task_part.replace("task-", "")
        level = "other"
        if "node-runLevel" in parts:
            level = "run"
        elif "node-dataLevel" in parts:
            level = "data"

        m = patt.search(p.name)
        if not m:
            continue

        sub_match = re.search(r"/sub-([A-Za-z0-9]+)/", str(p))
        subj = f"sub-{sub_match.group(1)}" if sub_match else ""

        rows.append(
            {
                "dataset": dataset,
                "task_raw": task_raw,
                "canonical_task": canonicalize_task(task_raw),
                "contrast": m.group(1),
                "subject": subj,
                "map_path": str(p),
                "level": level,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df[df["map_path"].map(lambda x: Path(x).exists())].copy()
    df = df.sort_values(
        ["level", "dataset", "task_raw", "subject", "contrast", "map_path"]
    ).reset_index(drop=True)
    return df


def select_maps(df: pd.DataFrame, max_per_task: int, max_samples: int) -> pd.DataFrame:
    run_df = df[df["level"] == "run"].copy()
    data_df = df[df["level"] == "data"].copy()

    if not run_df.empty:
        run_tasks = set(run_df["canonical_task"].unique())
        data_fallback = data_df[~data_df["canonical_task"].isin(run_tasks)]
        selected = pd.concat([run_df, data_fallback], ignore_index=True)
    else:
        selected = data_df if not data_df.empty else df.copy()

    selected = selected.sort_values(
        ["dataset", "canonical_task", "task_raw", "subject", "contrast", "map_path"]
    ).reset_index(drop=True)

    if max_per_task > 0:
        selected = (
            selected.groupby("canonical_task", group_keys=False)
            .head(max_per_task)
            .reset_index(drop=True)
        )

    if max_samples > 0 and len(selected) > max_samples:
        groups = {
            g: gdf.index.tolist()
            for g, gdf in selected.groupby("canonical_task", sort=True)
        }
        chosen: List[int] = []
        exhausted = False
        while len(chosen) < max_samples and not exhausted:
            exhausted = True
            for g in sorted(groups):
                if groups[g]:
                    chosen.append(groups[g].pop(0))
                    exhausted = False
                    if len(chosen) >= max_samples:
                        break
        selected = selected.loc[sorted(chosen)].reset_index(drop=True)

    return selected


def load_onvoc() -> tuple[dict, dict, dict, dict, set[str], dict[str, int]]:
    concepts = json.loads(ONVOC_CONCEPTS.read_text())
    rels = json.loads(ONVOC_RELATIONSHIPS.read_text())

    id_to_label: Dict[str, str] = {}
    label_to_id: Dict[str, str] = {}
    top_concepts: set[str] = set()
    for c in concepts:
        cid = c["id"]
        label = c.get("label", cid)
        id_to_label[cid] = label
        label_to_id[label.strip().casefold()] = cid
        if c.get("is_top_concept"):
            top_concepts.add(cid)

    parents_by_child: Dict[str, set[str]] = defaultdict(set)
    children_by_parent: Dict[str, set[str]] = defaultdict(set)
    for r in rels:
        child = r.get("child_id")
        parent = r.get("parent_id")
        if not child or not parent:
            continue
        parents_by_child[child].add(parent)
        children_by_parent[parent].add(child)

    degree_by_id: dict[str, int] = {}
    for cid in set(parents_by_child) | set(children_by_parent):
        degree_by_id[cid] = len(parents_by_child.get(cid, set()) | children_by_parent.get(cid, set()))

    return (
        id_to_label,
        label_to_id,
        dict(parents_by_child),
        dict(children_by_parent),
        top_concepts,
        degree_by_id,
    )


def add_feature(dest: dict[str, float], key: str, value: float, node_type: str) -> None:
    if node_type not in ALLOWED_NODE_TYPES:
        return
    dest[key] = max(float(value), float(dest.get(key, 0.0)))


def raw_task_features(
    canonical_task: str,
    task_raw: str,
    contrast: str,
    label_to_onvoc: dict[str, str],
    kg_item: dict | None,
    allow_lexical: bool,
) -> tuple[dict[str, float], list[str], list[str], str]:
    feats: dict[str, float] = {}

    add_feature(feats, f"TASK::{slugify(canonical_task)}", 1.0, "Task")
    add_feature(feats, f"TASK_RAW::{slugify(task_raw)}", 0.5, "Task")
    add_feature(feats, f"CONTRAST_ID::{slugify(contrast)}", 1.0, "Contrast")
    pos_cond, neg_cond, polarity, arity = parse_contrast_signature(contrast)
    add_feature(feats, f"POLARITY::{polarity}", 1.0, "Contrast")
    add_feature(feats, f"CONTRAST_ARITY::{arity}", 1.0, "Contrast")
    for c in pos_cond:
        add_feature(feats, f"COND_POS::{slugify(c)}", 0.8, "Condition")
    for c in neg_cond:
        add_feature(feats, f"COND_NEG::{slugify(c)}", 0.8, "Condition")
    if pos_cond and neg_cond:
        add_feature(
            feats,
            f"COND_PAIR::{slugify(pos_cond[0])}__vs__{slugify(neg_cond[0])}",
            0.9,
            "Contrast",
        )
    if canonical_task in TASK_CA_IDS:
        add_feature(feats, f"CA_TASK::{TASK_CA_IDS[canonical_task]}", 1.0, "Task")

    source = "kg"
    constructs: list[str] = []
    onvoc_ids: list[str] = []

    if kg_item:
        task_node_id = str(kg_item.get("task_node_id", "")).strip()
        if task_node_id:
            add_feature(feats, f"KG_TASK::{task_node_id}", 1.0, "Task")
        for kid in filter_kg_ids(list(kg_item.get("kg_feature_ids", []) or [])):
            kid = str(kid).strip()
            if not kid:
                continue
            if kid.startswith("ONVOC_"):
                add_feature(feats, f"ONVOC::{kid}", 1.0, "Concept")
                onvoc_ids.append(kid)
            else:
                add_feature(feats, f"KG_NODE::{kid}", 0.9, "Construct")
        for oid in filter_kg_ids(list(kg_item.get("onvoc_ids", []) or [])):
            oid = str(oid).strip()
            if oid.startswith("ONVOC_"):
                add_feature(feats, f"ONVOC::{oid}", 1.0, "Concept")
                onvoc_ids.append(oid)

    if not onvoc_ids and allow_lexical:
        source = "lexical_fallback"
        constructs = list(CONCEPTS_BY_TASK.get(canonical_task, ["Cognitive Load"]))
        tokens = lexical_tokens(canonical_task, task_raw, contrast)
        for t in tokens:
            add_feature(feats, f"TOKEN::{slugify(t)}", 0.2, "Contrast")
            constructs.extend(TOKEN_TO_CONCEPTS.get(t, []))

        seen = set()
        constructs = [c for c in constructs if not (c in seen or seen.add(c))]
        for label in constructs:
            cid = label_to_onvoc.get(label.casefold())
            if cid:
                add_feature(feats, f"ONVOC::{cid}", 1.0, "Concept")
                onvoc_ids.append(cid)
            else:
                add_feature(feats, f"CONCEPT::{slugify(label)}", 1.0, "Concept")

    # Always keep order uniqueness for onvoc.
    seen_onvoc = set()
    onvoc_ids = [x for x in onvoc_ids if not (x in seen_onvoc or seen_onvoc.add(x))]
    return feats, constructs, onvoc_ids, source


def smooth_onvoc_features(
    raw_feats: dict[str, float],
    parents_by_child: dict[str, set[str]],
    children_by_parent: dict[str, set[str]],
    top_concepts: set[str],
    degree_by_id: dict[str, int],
    max_onvoc_degree: int,
    max_hops: int,
    alpha: float,
) -> dict[str, float]:
    smooth = dict(raw_feats)

    for key, weight in raw_feats.items():
        if not key.startswith("ONVOC::"):
            continue
        cid = key.split("::", 1)[1]

        q: deque[tuple[str, int]] = deque([(cid, 0)])
        visited = {cid}
        while q:
            cur, hops = q.popleft()
            if hops >= max_hops:
                continue
            neighbors = parents_by_child.get(cur, set()) | children_by_parent.get(cur, set())
            for nxt in neighbors:
                if nxt in visited:
                    continue
                visited.add(nxt)
                is_generic = (nxt in top_concepts) or (
                    max_onvoc_degree > 0 and degree_by_id.get(nxt, 0) > max_onvoc_degree
                )
                if not is_generic:
                    anc_key = f"ONVOC::{nxt}"
                    anc_w = float(weight) * (alpha ** (hops + 1))
                    smooth[anc_key] = max(smooth.get(anc_key, 0.0), anc_w)
                q.append((nxt, hops + 1))

    return smooth


def dicts_to_matrix(dicts: list[dict[str, float]], vocab: list[str]) -> np.ndarray:
    idx = {k: i for i, k in enumerate(vocab)}
    X = np.zeros((len(dicts), len(vocab)), dtype=np.float32)
    for i, d in enumerate(dicts):
        for k, v in d.items():
            j = idx.get(k)
            if j is not None:
                X[i, j] = float(v)
    return X


def build_feature_matrices(
    df: pd.DataFrame,
    label_to_onvoc: dict[str, str],
    parents_by_child: dict[str, set[str]],
    children_by_parent: dict[str, set[str]],
    top_concepts: set[str],
    degree_by_id: dict[str, int],
    max_onvoc_degree: int,
    max_hops: int,
    alpha: float,
    blend_lambda: float,
    min_feature_df: int,
    max_feature_df_ratio: float,
    max_features: int,
    kg_lookup: dict[tuple[str, str], dict],
    allow_lexical: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict], pd.DataFrame]:
    raw_dicts: list[dict[str, float]] = []
    smooth_dicts: list[dict[str, float]] = []
    concept_labels: list[list[str]] = []
    onvoc_ids: list[list[str]] = []
    feature_sources: list[str] = []

    for _, row in df.iterrows():
        key = (str(row["task_raw"]).strip().lower(), str(row["contrast"]).strip().lower())
        kg_item = kg_lookup.get(key)
        raw_feats, labels, ids, source = raw_task_features(
            str(row["canonical_task"]),
            str(row["task_raw"]),
            str(row["contrast"]),
            label_to_onvoc,
            kg_item=kg_item,
            allow_lexical=allow_lexical,
        )
        smooth_feats = smooth_onvoc_features(
            raw_feats,
            parents_by_child,
            children_by_parent,
            top_concepts,
            degree_by_id,
            max_onvoc_degree,
            max_hops,
            alpha,
        )
        raw_dicts.append(raw_feats)
        smooth_dicts.append(smooth_feats)
        concept_labels.append(labels)
        onvoc_ids.append(ids)
        feature_sources.append(source)

    df = df.copy()
    df["concept_labels_json"] = [json.dumps(v, ensure_ascii=False) for v in concept_labels]
    df["onvoc_ids_json"] = [json.dumps(v, ensure_ascii=False) for v in onvoc_ids]
    df["feature_source"] = feature_sources

    vocab_full = sorted(
        {k for d in raw_dicts for k in d.keys()} | {k for d in smooth_dicts for k in d.keys()}
    )
    X_raw_full = dicts_to_matrix(raw_dicts, vocab_full)
    X_smooth_full = dicts_to_matrix(smooth_dicts, vocab_full)
    X_blend_full = ((1.0 - blend_lambda) * X_raw_full) + (blend_lambda * X_smooth_full)

    df_count = np.asarray((X_blend_full > 0).sum(axis=0)).ravel()
    keep = np.where(df_count >= max(1, int(min_feature_df)))[0]
    if 0.0 < max_feature_df_ratio < 1.0 and len(keep) > 0:
        max_df = max(1, int(max_feature_df_ratio * len(df)))
        keep = np.asarray([j for j in keep if df_count[j] <= max_df], dtype=int)
    if len(keep) == 0:
        keep = np.where(df_count >= max(1, int(min_feature_df)))[0]

    if max_features > 0 and len(keep) > max_features:
        def rank_key(j: int) -> tuple:
            feat = vocab_full[j]
            if feat.startswith(("CONTRAST_ID::", "COND_POS::", "COND_NEG::", "COND_PAIR::", "POLARITY::", "CONTRAST_ARITY::")):
                type_bonus = 4
            elif feat.startswith("ONVOC::"):
                type_bonus = 3
            elif feat.startswith(("KG_NODE::", "KG_TASK::")):
                type_bonus = 2
            elif feat.startswith("TOKEN::"):
                type_bonus = 1
            else:
                type_bonus = 0
            return (int(df_count[j]), type_bonus, feat)

        keep = np.array(sorted(keep, key=rank_key, reverse=True)[:max_features], dtype=int)

    keep = np.sort(keep)
    vocab = [vocab_full[j] for j in keep]
    X_raw = X_raw_full[:, keep]
    X_smooth = X_smooth_full[:, keep]
    X_blend = X_blend_full[:, keep]

    feature_meta: list[dict] = []
    for local_j, feat in enumerate(vocab):
        if feat.startswith("ONVOC::"):
            ftype = "Concept"
        elif (
            feat.startswith("TASK::")
            or feat.startswith("CA_TASK::")
            or feat.startswith("TASK_RAW::")
            or feat.startswith("KG_TASK::")
        ):
            ftype = "Task"
        elif feat.startswith("TOKEN::"):
            ftype = "Contrast"
        elif feat.startswith("KG_NODE::"):
            ftype = "Construct"
        else:
            ftype = "Construct"
        feature_meta.append(
            {
                "feature": feat,
                "node_type": ftype,
                "df_count": int(df_count[keep[local_j]]),
            }
        )

    return X_raw, X_smooth, X_blend, feature_meta, df


def load_resampled_Y(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, nib.Nifti1Image, np.ndarray]:
    template = datasets.load_mni152_template()
    template = image.resample_img(
        template,
        target_affine=np.diag([3.0, 3.0, 3.0]),
        interpolation="continuous",
        copy_header=True,
        force_resample=True,
    )

    tdata = template.get_fdata(dtype=np.float32)
    mask = np.isfinite(tdata) & (np.abs(tdata) > 0)

    mats: list[np.ndarray] = []
    keep: list[bool] = []
    for i, p in enumerate(df["map_path"].tolist()):
        try:
            img = nib.load(p)
            rimg = image.resample_to_img(
                img,
                template,
                interpolation="continuous",
                copy_header=True,
                force_resample=True,
            )
            arr = rimg.get_fdata(dtype=np.float32)
            arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
            mats.append(arr[mask])
            keep.append(True)
        except Exception:
            keep.append(False)
        if (i + 1) % 100 == 0:
            print(f"[Y] loaded {i + 1}/{len(df)} maps")

    if not mats:
        raise RuntimeError("No maps could be loaded after resampling.")

    Y = np.stack(mats, axis=0).astype(np.float32)
    keep_mask = np.asarray(keep, dtype=bool)
    return Y, mask, template, keep_mask


def load_parcel_Y_schaefer(
    df: pd.DataFrame,
    *,
    n_rois: int = 400,
    yeo_networks: int = 7,
    resolution_mm: int = 2,
    atlas_path: Path | None = None,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    if atlas_path is not None:
        labels_img = str(atlas_path)
        atlas_name = f"Schaefer2018(custom:{atlas_path.name})"
        labels: list[str] = []
    else:
        atlas = datasets.fetch_atlas_schaefer_2018(
            n_rois=n_rois,
            yeo_networks=yeo_networks,
            resolution_mm=resolution_mm,
        )
        labels_img = atlas.maps
        atlas_name = "Schaefer2018"
        labels = [
            (x.decode("utf-8") if isinstance(x, bytes) else str(x))
            for x in atlas.labels
        ]

    # Fit on one representative map so label resampling happens once at fit-time.
    # This avoids repeated transform-time resampling warnings/noise.
    fit_img = None
    for p in df["map_path"].tolist():
        if Path(str(p)).exists():
            fit_img = str(p)
            break

    masker = NiftiLabelsMasker(
        labels_img=labels_img,
        standardize=False,
        resampling_target="data",
    )
    if fit_img is not None:
        masker.fit(fit_img)
    else:
        masker.fit()

    mats: list[np.ndarray] = []
    keep: list[bool] = []
    for i, p in enumerate(df["map_path"].tolist()):
        try:
            arr = np.asarray(masker.transform(str(p)), dtype=np.float32)
            if arr.ndim == 1:
                vec = arr
            elif arr.ndim == 2:
                vec = arr[0]
            else:
                raise ValueError(f"Unexpected parcel transform shape: {arr.shape}")
            vec = np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)
            mats.append(vec)
            keep.append(True)
        except Exception:
            keep.append(False)
        if (i + 1) % 100 == 0:
            print(f"[Y] loaded {i + 1}/{len(df)} maps")

    if not mats:
        raise RuntimeError("No maps could be loaded for parcel representation.")

    Y = np.stack(mats, axis=0).astype(np.float32)
    keep_mask = np.asarray(keep, dtype=bool)
    meta = {
        "target_space": "schaefer",
        "atlas_name": atlas_name,
        "labels_img": str(labels_img),
        "labels": labels,
        "n_targets": int(Y.shape[1]),
        "n_rois": int(n_rois),
        "yeo_networks": int(yeo_networks),
        "resolution_mm": int(resolution_mm),
    }
    return Y, keep_mask, meta


def load_Y(
    df: pd.DataFrame,
    *,
    target_space: str,
    schaefer_n_rois: int = 400,
    schaefer_yeo_networks: int = 7,
    schaefer_resolution_mm: int = 2,
    schaefer_atlas_path: Path | None = None,
) -> tuple[np.ndarray, np.ndarray | None, nib.Nifti1Image | None, np.ndarray, dict[str, Any]]:
    target = str(target_space).strip().lower()
    if target == "voxel":
        Y, mask, template, keep_mask = load_resampled_Y(df)
        meta = {
            "target_space": "voxel",
            "n_targets": int(Y.shape[1]),
            "template_shape": list(template.shape) if hasattr(template, "shape") else None,
        }
        return Y, mask, template, keep_mask, meta
    if target == "schaefer":
        Y, keep_mask, meta = load_parcel_Y_schaefer(
            df,
            n_rois=schaefer_n_rois,
            yeo_networks=schaefer_yeo_networks,
            resolution_mm=schaefer_resolution_mm,
            atlas_path=schaefer_atlas_path,
        )
        return Y, None, None, keep_mask, meta
    raise ValueError(f"Unsupported target_space={target_space}")


def pearsonr_fast(a: np.ndarray, b: np.ndarray) -> float:
    aa = a.astype(np.float64, copy=False)
    bb = b.astype(np.float64, copy=False)
    aa = aa - aa.mean()
    bb = bb - bb.mean()
    na = float(np.linalg.norm(aa))
    nb = float(np.linalg.norm(bb))
    if na <= 1e-12 or nb <= 1e-12:
        return float("nan")
    return float(np.dot(aa, bb) / (na * nb))


def peak_distance_mm(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    mask: np.ndarray | None,
    affine: np.ndarray | None,
) -> float:
    if mask is None or affine is None:
        return float("nan")
    vox = np.column_stack(np.where(mask))
    i_true = int(np.argmax(np.abs(y_true)))
    i_pred = int(np.argmax(np.abs(y_pred)))
    xyz_true = nib.affines.apply_affine(affine, vox[i_true])
    xyz_pred = nib.affines.apply_affine(affine, vox[i_pred])
    return float(np.linalg.norm(xyz_true - xyz_pred))


def evaluate_loto(
    name: str,
    X: np.ndarray,
    Y: np.ndarray,
    df: pd.DataFrame,
    mask: np.ndarray | None,
    affine: np.ndarray | None,
    ridge_alpha: float,
    min_train: int,
) -> tuple[pd.DataFrame, dict]:
    rows: list[dict] = []
    groups = sorted(df["canonical_task"].unique())

    for group in groups:
        test_idx = np.where(df["canonical_task"].values == group)[0]
        train_idx = np.where(df["canonical_task"].values != group)[0]
        if len(test_idx) == 0 or len(train_idx) < min_train:
            continue

        Xtr, Xte = X[train_idx], X[test_idx]
        Ytr, Yte = Y[train_idx], Y[test_idx]

        model = Ridge(alpha=ridge_alpha, fit_intercept=True)
        model.fit(Xtr, Ytr)
        Yhat = model.predict(Xte)

        y_mean = Ytr.mean(axis=0)

        for local_i, idx in enumerate(test_idx):
            y_true = Yte[local_i]
            y_pred = Yhat[local_i]

            r = pearsonr_fast(y_true, y_pred)
            r_base = pearsonr_fast(y_true, y_mean)
            dpk = peak_distance_mm(y_true, y_pred, mask, affine)
            dpk_base = peak_distance_mm(y_true, y_mean, mask, affine)

            row = {
                "model": name,
                "sample_index": int(idx),
                "dataset": df.iloc[idx]["dataset"],
                "task_raw": df.iloc[idx]["task_raw"],
                "canonical_task": df.iloc[idx]["canonical_task"],
                "contrast": df.iloc[idx]["contrast"],
                "level": df.iloc[idx]["level"],
                "voxel_r": r,
                "voxel_r_baseline": r_base,
                "delta_r": r - r_base if np.isfinite(r) and np.isfinite(r_base) else np.nan,
                "peak_distance_mm": dpk,
                "peak_distance_mm_baseline": dpk_base,
                "delta_peak_mm": dpk_base - dpk if np.isfinite(dpk) and np.isfinite(dpk_base) else np.nan,
            }
            rows.append(row)

    mdf = pd.DataFrame(rows)
    if mdf.empty:
        summary = {
            "model": name,
            "n_eval_samples": 0,
            "n_eval_groups": 0,
            "error": "No evaluable LOTO splits.",
        }
        return mdf, summary

    summary = {
        "model": name,
        "n_eval_samples": int(len(mdf)),
        "n_eval_groups": int(mdf["canonical_task"].nunique()),
        "mean_voxel_r": float(mdf["voxel_r"].mean()),
        "median_voxel_r": float(mdf["voxel_r"].median()),
        "mean_voxel_r_baseline": float(mdf["voxel_r_baseline"].mean()),
        "mean_delta_r": float(mdf["delta_r"].mean()),
        "win_rate_r": float((mdf["delta_r"] > 0).mean()),
        "mean_peak_distance_mm": float(mdf["peak_distance_mm"].mean()),
        "mean_peak_distance_mm_baseline": float(mdf["peak_distance_mm_baseline"].mean()),
        "mean_delta_peak_mm": float(mdf["delta_peak_mm"].mean()),
        "win_rate_peak": float((mdf["delta_peak_mm"] > 0).mean()),
    }
    return mdf, summary


def save_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def load_rdoc_rules(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    rules = data.get("rules", [])
    out: dict[str, dict] = {}
    for r in rules:
        onvoc = r.get("onvoc", {})
        cid = onvoc.get("id")
        if cid:
            out[cid] = r
    return out


def export_tuning_maps_and_rdoc(
    X_blend: np.ndarray,
    Y: np.ndarray,
    feature_meta: list[dict],
    mask: np.ndarray | None,
    template: nib.Nifti1Image | None,
    out_dir: Path,
    ridge_alpha: float,
    max_maps: int,
    onvoc_id_to_label: dict[str, str],
    rdoc_rules: dict[str, dict],
) -> tuple[pd.DataFrame, dict]:
    if mask is None or template is None:
        empty = pd.DataFrame(
            columns=[
                "feature",
                "onvoc_id",
                "onvoc_label",
                "mean_abs_beta",
                "map_path",
                "rdoc_domain",
                "rdoc_construct",
                "rdoc_confidence",
            ]
        )
        empty.to_csv(out_dir / "tuning_map_manifest.csv", index=False)
        payload = {
            "n_tuning_maps": 0,
            "rdoc_aggregation": [],
            "message": "Target space is non-voxel; voxel tuning maps were skipped.",
        }
        save_json(out_dir / "rdoc_projection_summary.json", payload)
        return empty, payload

    model = Ridge(alpha=ridge_alpha, fit_intercept=True)
    model.fit(X_blend, Y)
    coef = model.coef_  # [n_voxels, n_features]

    feat_df = pd.DataFrame(feature_meta)
    feat_df["feature_index"] = np.arange(len(feat_df))
    feat_df["mean_abs_beta"] = [float(np.mean(np.abs(coef[:, j]))) for j in range(coef.shape[1])]

    onvoc_feat = feat_df[feat_df["feature"].str.startswith("ONVOC::")].copy()
    if onvoc_feat.empty:
        return pd.DataFrame(), {"message": "No ONVOC features for tuning maps."}

    onvoc_feat = onvoc_feat.sort_values("mean_abs_beta", ascending=False).head(max_maps)

    rows: list[dict] = []
    for _, r in onvoc_feat.iterrows():
        feat = str(r["feature"])
        j = int(r["feature_index"])
        cid = feat.split("::", 1)[1]
        label = onvoc_id_to_label.get(cid, cid)

        vol = np.zeros(mask.shape, dtype=np.float32)
        vol[mask] = coef[:, j].astype(np.float32)

        fname = f"tuning_{slugify(label)}_{cid}.nii.gz"
        fpath = out_dir / fname
        nib.save(nib.Nifti1Image(vol, template.affine), str(fpath))

        rule = rdoc_rules.get(cid, {})
        primary = rule.get("rdoc_primary", {})
        rows.append(
            {
                "feature": feat,
                "onvoc_id": cid,
                "onvoc_label": label,
                "mean_abs_beta": float(r["mean_abs_beta"]),
                "map_path": str(fpath),
                "rdoc_domain": primary.get("domain", ""),
                "rdoc_construct": primary.get("construct", ""),
                "rdoc_confidence": float(rule.get("confidence", 0.0)) if rule else np.nan,
            }
        )

    mdf = pd.DataFrame(rows)
    mdf.to_csv(out_dir / "tuning_map_manifest.csv", index=False)

    # Domain-level aggregation for interpretability.
    agg_rows = []
    if not mdf.empty:
        grp = (
            mdf.groupby(["rdoc_domain", "rdoc_construct"], dropna=False)["mean_abs_beta"]
            .sum()
            .reset_index()
            .sort_values("mean_abs_beta", ascending=False)
        )
        for _, rr in grp.iterrows():
            agg_rows.append(
                {
                    "rdoc_domain": rr["rdoc_domain"],
                    "rdoc_construct": rr["rdoc_construct"],
                    "total_mean_abs_beta": float(rr["mean_abs_beta"]),
                }
            )

    payload = {
        "n_tuning_maps": int(len(mdf)),
        "rdoc_aggregation": agg_rows,
    }
    save_json(out_dir / "rdoc_projection_summary.json", payload)
    return mdf, payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Forward encoding v2 with ontology smoothing.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--kg-feature-map", type=Path, default=DEFAULT_KG_FEATURE_MAP)
    parser.add_argument("--allow-lexical-fallback", action="store_true")
    parser.add_argument("--max-samples", type=int, default=900)
    parser.add_argument("--max-per-task", type=int, default=80)
    parser.add_argument("--min-train", type=int, default=40)
    parser.add_argument("--max-hops", type=int, default=3)
    parser.add_argument("--max-onvoc-degree", type=int, default=20)
    parser.add_argument("--alpha", type=float, default=0.6)
    parser.add_argument("--blend-lambda", type=float, default=0.35)
    parser.add_argument("--min-feature-df", type=int, default=3)
    parser.add_argument("--max-feature-df-ratio", type=float, default=0.9)
    parser.add_argument("--max-features", type=int, default=128)
    parser.add_argument("--ridge-alpha", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-tuning-maps", type=int, default=16)
    parser.add_argument(
        "--target-space",
        choices=["voxel", "schaefer"],
        default="voxel",
        help="Target representation for Y.",
    )
    parser.add_argument("--schaefer-n-rois", type=int, default=400)
    parser.add_argument("--schaefer-yeo-networks", type=int, default=7)
    parser.add_argument("--schaefer-resolution-mm", type=int, default=2)
    parser.add_argument(
        "--schaefer-atlas-path",
        type=Path,
        default=None,
        help="Optional local labels image path for Schaefer atlas.",
    )
    args = parser.parse_args()

    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    (
        onvoc_id_to_label,
        onvoc_label_to_id,
        parents_by_child,
        children_by_parent,
        top_concepts,
        degree_by_id,
    ) = load_onvoc()

    all_maps = list_stat_maps(args.root)
    if all_maps.empty:
        raise RuntimeError(f"No stat-z maps found under {args.root}")

    kg_lookup = load_kg_feature_map(args.kg_feature_map)

    selected = select_maps(all_maps, args.max_per_task, args.max_samples)
    if selected.empty:
        raise RuntimeError("Map selection returned 0 samples.")

    X_raw, X_smooth, X_blend, feature_meta, selected = build_feature_matrices(
        selected,
        onvoc_label_to_id,
        parents_by_child,
        children_by_parent,
        top_concepts,
        degree_by_id,
        max_onvoc_degree=args.max_onvoc_degree,
        max_hops=args.max_hops,
        alpha=args.alpha,
        blend_lambda=args.blend_lambda,
        min_feature_df=args.min_feature_df,
        max_feature_df_ratio=args.max_feature_df_ratio,
        max_features=args.max_features,
        kg_lookup=kg_lookup,
        allow_lexical=args.allow_lexical_fallback,
    )

    Y, mask, template, keep_mask, target_meta = load_Y(
        selected,
        target_space=args.target_space,
        schaefer_n_rois=args.schaefer_n_rois,
        schaefer_yeo_networks=args.schaefer_yeo_networks,
        schaefer_resolution_mm=args.schaefer_resolution_mm,
        schaefer_atlas_path=args.schaefer_atlas_path,
    )
    if not keep_mask.all():
        selected = selected[keep_mask].reset_index(drop=True)
        X_raw = X_raw[keep_mask]
        X_smooth = X_smooth[keep_mask]
        X_blend = X_blend[keep_mask]

    # Save manifest and vocab.
    selected.to_csv(out / "manifest.csv", index=False)
    save_json(out / "feature_vocab.json", {"features": feature_meta})

    affine = template.affine if template is not None else None
    metrics_raw_df, metrics_raw = evaluate_loto(
        "raw", X_raw, Y, selected, mask, affine, args.ridge_alpha, args.min_train
    )
    metrics_smooth_df, metrics_smooth = evaluate_loto(
        "smooth", X_smooth, Y, selected, mask, affine, args.ridge_alpha, args.min_train
    )
    metrics_blend_df, metrics_blend = evaluate_loto(
        "blend", X_blend, Y, selected, mask, affine, args.ridge_alpha, args.min_train
    )

    rng = np.random.default_rng(args.seed)
    perm = rng.permutation(len(X_blend))
    X_null = X_blend[perm]
    metrics_null_df, metrics_null = evaluate_loto(
        "null", X_null, Y, selected, mask, affine, args.ridge_alpha, args.min_train
    )

    metrics_raw_df.to_csv(out / "sample_metrics_raw.csv", index=False)
    metrics_smooth_df.to_csv(out / "sample_metrics_smooth.csv", index=False)
    metrics_blend_df.to_csv(out / "sample_metrics_blend.csv", index=False)
    metrics_null_df.to_csv(out / "sample_metrics_null.csv", index=False)

    common_meta = {
        "n_selected_samples": int(len(selected)),
        "n_selected_tasks": int(selected["canonical_task"].nunique()),
        "n_features": int(X_blend.shape[1]),
        "n_targets": int(Y.shape[1]),
        "n_voxels": int(Y.shape[1]),
        "target_space": str(target_meta.get("target_space", args.target_space)),
        "target_meta": target_meta,
        "selection": {
            "max_samples": args.max_samples,
            "max_per_task": args.max_per_task,
            "min_train": args.min_train,
            "min_feature_df": args.min_feature_df,
            "max_feature_df_ratio": args.max_feature_df_ratio,
            "max_features": args.max_features,
            "max_onvoc_degree": args.max_onvoc_degree,
            "kg_feature_map": str(args.kg_feature_map),
            "allow_lexical_fallback": bool(args.allow_lexical_fallback),
            "target_space": args.target_space,
            "schaefer_n_rois": args.schaefer_n_rois,
            "schaefer_yeo_networks": args.schaefer_yeo_networks,
            "schaefer_resolution_mm": args.schaefer_resolution_mm,
            "schaefer_atlas_path": str(args.schaefer_atlas_path) if args.schaefer_atlas_path else None,
        },
        "smoothing": {
            "max_hops": args.max_hops,
            "alpha": args.alpha,
            "blend_lambda": args.blend_lambda,
        },
        "leakage_policy": {
            "allowed_node_types": sorted(ALLOWED_NODE_TYPES),
            "blocked_node_types": ["StatsMap", "Dataset", "Publication", "Region"],
        },
        "notes": [
            "Features prioritize MCP-derived KG nodes (Task/Concept/Contrast/ONVOC).",
            "Ontology smoothing propagates ONVOC activations over parent+child hops with exponential decay.",
            (
                "Y uses resampled glmfitlins stat-z maps at MNI152 3mm grid."
                if str(target_meta.get("target_space")) == "voxel"
                else "Y uses Schaefer parcel representation for denoised target modeling."
            ),
            f"KG lookup entries loaded: {len(kg_lookup)}",
            f"Feature source counts: {dict(pd.Series(selected['feature_source']).value_counts())}",
        ],
    }

    save_json(out / "metrics_raw.json", {**common_meta, "results": metrics_raw})
    save_json(out / "metrics_smooth.json", {**common_meta, "results": metrics_smooth})
    save_json(out / "metrics_blend.json", {**common_meta, "results": metrics_blend})
    save_json(out / "metrics_null.json", {**common_meta, "results": metrics_null})

    rdoc_rules = load_rdoc_rules(out / "rdoc_projection_rules.json")
    tuning_df, rdoc_summary = export_tuning_maps_and_rdoc(
        X_blend,
        Y,
        feature_meta,
        mask,
        template,
        out,
        args.ridge_alpha,
        args.max_tuning_maps,
        onvoc_id_to_label,
        rdoc_rules,
    )

    blend_r = metrics_blend.get("mean_voxel_r", float("nan"))
    blend_rb = metrics_blend.get("mean_voxel_r_baseline", float("nan"))
    blend_dpk = metrics_blend.get("mean_peak_distance_mm", float("nan"))
    blend_dpkb = metrics_blend.get("mean_peak_distance_mm_baseline", float("nan"))
    null_r = metrics_null.get("mean_voxel_r", float("nan"))
    is_voxel = str(target_meta.get("target_space", "voxel")) == "voxel"

    if is_voxel:
        gate_pass = bool(
            np.isfinite(blend_r)
            and np.isfinite(blend_rb)
            and np.isfinite(blend_dpk)
            and np.isfinite(blend_dpkb)
            and blend_r > blend_rb
            and blend_dpk < blend_dpkb
            and (not np.isfinite(null_r) or blend_r > null_r)
        )
    else:
        gate_pass = bool(
            np.isfinite(blend_r)
            and np.isfinite(blend_rb)
            and blend_r > blend_rb
            and (not np.isfinite(null_r) or blend_r > null_r)
        )

    gate = {
        "decision": "go" if gate_pass else "conditional_go",
        "criteria": {
            "blend_r_gt_baseline": bool(np.isfinite(blend_r) and np.isfinite(blend_rb) and blend_r > blend_rb),
            "blend_peak_lt_baseline": (
                bool(np.isfinite(blend_dpk) and np.isfinite(blend_dpkb) and blend_dpk < blend_dpkb)
                if is_voxel
                else None
            ),
            "blend_r_gt_null": bool(not np.isfinite(null_r) or (np.isfinite(blend_r) and blend_r > null_r)),
        },
    }
    save_json(out / "gate_decision.json", gate)

    report_lines = [
        "# Forward Encoding V2 (Hybrid Ontology Smoothing)",
        "",
        "## Data",
        f"- Selected samples: {len(selected)}",
        f"- Selected task families: {selected['canonical_task'].nunique()}",
        f"- Feature dimensions: {X_blend.shape[1]}",
        f"- Target space: {target_meta.get('target_space', 'voxel')}",
        f"- Targets: {Y.shape[1]}",
        "",
        "## LOTO Results",
        f"- Raw mean r: {metrics_raw.get('mean_voxel_r', float('nan')):.4f} (baseline {metrics_raw.get('mean_voxel_r_baseline', float('nan')):.4f})",
        f"- Smooth mean r: {metrics_smooth.get('mean_voxel_r', float('nan')):.4f} (baseline {metrics_smooth.get('mean_voxel_r_baseline', float('nan')):.4f})",
        f"- Blend mean r: {metrics_blend.get('mean_voxel_r', float('nan')):.4f} (baseline {metrics_blend.get('mean_voxel_r_baseline', float('nan')):.4f})",
        f"- Blend mean peak distance (mm): {metrics_blend.get('mean_peak_distance_mm', float('nan')):.2f} (baseline {metrics_blend.get('mean_peak_distance_mm_baseline', float('nan')):.2f})",
        f"- Null mean r: {metrics_null.get('mean_voxel_r', float('nan')):.4f}",
        "",
        "## Tuning and RDoC Projection",
        f"- Saved tuning maps: {len(tuning_df)}",
        f"- RDoC aggregated entries: {len(rdoc_summary.get('rdoc_aggregation', []))}",
        "",
        "## Gate",
        f"- Decision: {gate['decision']}",
        f"- Criteria: {json.dumps(gate['criteria'])}",
    ]
    (out / "report.md").write_text("\n".join(report_lines))

    print(json.dumps({"ok": True, "out": str(out), "gate": gate}, indent=2))


if __name__ == "__main__":
    main()
