#!/usr/bin/env python3
"""LLM-assisted matcher for Cognitive Atlas tasks → ONVOC anchors."""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import typer
from pydantic import BaseModel, Field, ValidationError

# Reuse scoring / fetching utilities from the existing mapper
sys.path.append(str(Path(__file__).resolve().parent))
import onvoc_mapper as mapper  # noqa: E402

app = typer.Typer(help="LLM assisted Task → ONVOC matcher (Gemini)")

STUDY_DESIGN_ONVOC = "ONVOC_0000007"
DEFAULT_MODEL = "gemini-2.5-flash-lite"


@dataclass
class LLMConfig:
    api_key: str
    model: str = DEFAULT_MODEL
    temperature: float = 0.2
    top_p: float = 0.9
    top_k: int = 40
    max_tokens: int = 1024
    endpoint: str = "https://generativelanguage.googleapis.com/v1beta/models"


@dataclass
class TaskPrompt:
    """Task plus the ONVOC candidates shown to the LLM."""

    task: mapper.TaskRecord
    candidates: List[Dict[str, str]]
    stage: str = "l2"
    parent_l2: Optional[str] = None
    parent_l2_label: Optional[str] = None


class Prediction(BaseModel):
    task_id: str
    onvoc_id: str = Field(..., alias="onvoc_id")
    score: float
    rationale: Optional[str] = None
    evidence: List[str] = Field(default_factory=list)


class LLMResponse(BaseModel):
    predictions: List[Prediction] = Field(default_factory=list)


def _load_llm_config(model: str) -> LLMConfig:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise typer.BadParameter("GEMINI_API_KEY env var not set")
    return LLMConfig(api_key=api_key, model=model)


def _build_onvoc_reference(batch: List[TaskPrompt]) -> List[Dict[str, str]]:
    lookup: Dict[str, Dict[str, str]] = {}
    for prompt in batch:
        for cand in prompt.candidates:
            lookup.setdefault(
                cand["id"],
                {
                    "id": cand["id"],
                    "label": cand.get("label") or cand["id"],
                    "definition": cand.get("definition", ""),
                },
            )
    return sorted(lookup.values(), key=lambda ref: ref["id"])


def _find_candidate_label(candidates: List[Dict[str, str]], onvoc_id: str) -> str:
    for cand in candidates or []:
        if cand.get("id") == onvoc_id:
            return cand.get("label") or onvoc_id
    return onvoc_id


def _render_batch_prompt(batch: List[TaskPrompt]) -> str:
    if not batch:
        return ""
    stage = batch[0].stage or "l2"
    onvoc_refs = _build_onvoc_reference(batch)
    if stage == "l3":
        intro = [
            "You refine Cognitive Atlas tasks to ONVOC Level-3 IDs under the specified Level-2 parent.",
            "Use only the ONVOC Level-3 IDs provided for each task. Choose exactly one child or NONE if none apply.",
        ]
    else:
        intro = [
            "You map Cognitive Atlas tasks to ONVOC Level-2 cognitive process IDs.",
            "Use only the ONVOC IDs provided. Prefer the most specific applicable anchor and reply NONE if uncertain.",
        ]
    intro.append("Never choose ONVOC_0000007 (Study Design) unless the task is purely a rest/localizer/fixation control.")
    intro.append("")
    intro.append("ONVOC reference list (id: label — short note):")
    for ref in onvoc_refs:
        label = ref.get("label") or ref["id"]
        note = (ref.get("definition") or label)[:200]
        intro.append(f"- {ref['id']}: {label} — {note}")

    intro.append("")
    if stage == "l3":
        intro.append("Tasks (parent Level-2 is provided; stay within that subtree):")
    else:
        intro.append("Tasks (include only confident predictions; skip if uncertain):")
    intro.append("Always reference the provided task_id (in brackets) when returning JSON.")

    for idx, prompt in enumerate(batch, start=1):
        task = prompt.task
        desc = (task.description or task.definition or "(no description)").strip().replace("\n", " ")[:800]
        header = f"{idx}. [task_id={task.id}] {task.name or task.id}"
        if stage == "l3":
            parent_label = prompt.parent_l2_label or prompt.parent_l2 or "unknown"
            parent_id = prompt.parent_l2 or "unknown"
            intro.append(
                f"{header} (parent L2: {parent_id} — {parent_label}) — {desc}"
            )
        else:
            intro.append(f"{header} — {desc}")

    intro.append("")
    intro.append("Return STRICT minified JSON matching schema {\"predictions\": [{\"task_id\": str, \"onvoc_id\": str, \"score\": 0-1}]}")
    intro.append("Only include entries for tasks you mapped with high confidence; omit Study Design outputs unless explicitly instructed.")
    intro.append("No additional fields or commentary are allowed; end the JSON cleanly.")
    return "\n".join(intro)


def _response_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "predictions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "onvoc_id": {"type": "string"},
                        "score": {"type": "number"},
                    },
                    "required": ["task_id", "onvoc_id", "score"],
                },
            }
        },
        "required": ["predictions"],
    }


def _call_gemini(
    prompt: str,
    cfg: LLMConfig,
    max_attempts: int = 2,
    backoff: float = 2.0,
) -> LLMResponse:
    url = f"{cfg.endpoint}/{cfg.model}:generateContent?key={cfg.api_key}"
    last_error: Optional[Exception] = None
    delay = max(backoff, 0.5)
    for attempt in range(max_attempts):
        prompt_text = prompt if attempt == 0 else f"{prompt}\nReturn only valid JSON that matches the schema."
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt_text}],
                }
            ],
            "generationConfig": {
                "temperature": cfg.temperature,
                "topP": cfg.top_p,
                "topK": cfg.top_k,
                "maxOutputTokens": cfg.max_tokens,
                "responseMimeType": "application/json",
                "responseSchema": _response_schema(),
            },
            "safetySettings": [],
        }
        resp = requests.post(url, json=payload, timeout=60)
        if resp.status_code == 429:
            last_error = RuntimeError("Gemini API 429 Too Many Requests")
            time.sleep(delay)
            delay = min(delay * 1.5, 60.0)
            continue
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            body = None
            try:
                body = resp.text
            except Exception:
                body = "<unavailable>"
            last_error = RuntimeError(f"{exc}: {body}")
            time.sleep(delay)
            delay = min(delay * 1.5, 60.0)
            continue
        data = resp.json()
        try:
            part = data["candidates"][0]["content"]["parts"][0]
        except (KeyError, IndexError):
            last_error = RuntimeError(f"Unexpected Gemini response: {data}")
            continue
        payload_obj: Any
        if isinstance(part, dict) and "functionCall" in part:
            payload_obj = part["functionCall"].get("args")
        else:
            payload_obj = part.get("text") if isinstance(part, dict) else None
        if payload_obj is None:
            last_error = RuntimeError(f"Missing content payload in Gemini response: {data}")
            continue
        try:
            if isinstance(payload_obj, str):
                parsed = json.loads(payload_obj)
            else:
                parsed = payload_obj
            return LLMResponse.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError) as exc:
            preview = payload_obj if isinstance(payload_obj, str) else json.dumps(payload_obj)
            typer.echo(
                f"LLM parse error (attempt {attempt + 1}): {exc}: {repr(preview)[:1200]}",
                err=True,
            )
            if isinstance(payload_obj, str):
                try:
                    debug_path = Path("outputs/llm_debug_payload.json")
                    debug_path.write_text(payload_obj)
                except Exception:
                    pass
            last_error = exc
            continue
    raise RuntimeError(f"Gemini output invalid after {max_attempts} attempts: {last_error}")


def _batched_votes(
    batch: List[TaskPrompt],
    llm_cfg: LLMConfig,
    votes: int,
    max_attempts: int,
    batch_delay: float,
    backoff: float,
) -> List[LLMResponse]:
    if not batch:
        return []
    prompt = _render_batch_prompt(batch)
    results: List[LLMResponse] = []
    for attempt in range(votes):
        try:
            results.append(
                _call_gemini(prompt, llm_cfg, max_attempts=max_attempts, backoff=backoff)
            )
        except RuntimeError as exc:
            typer.echo(
                f"LLM error for batch starting with {batch[0].task.id}: {exc}", err=True
            )
            break
        if batch_delay and attempt < votes - 1:
            time.sleep(batch_delay)
    return results


def _group_predictions(
    batch: List[TaskPrompt], votes_payload: List[LLMResponse]
) -> Dict[str, List[Prediction]]:
    per_task: Dict[str, List[Prediction]] = {prompt.task.id: [] for prompt in batch}
    allowed_map: Dict[str, set[str]] = {
        prompt.task.id: {cand["id"] for cand in prompt.candidates}
        for prompt in batch
    }
    for vote in votes_payload:
        for pred in vote.predictions:
            allowed = allowed_map.get(pred.task_id)
            if not allowed:
                continue
            if pred.onvoc_id not in allowed and pred.onvoc_id.upper() != "NONE":
                continue
            per_task[pred.task_id].append(pred)
    return per_task


def _aggregate_predictions(predictions: List[Prediction]) -> List[Dict[str, Any]]:
    stats: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"score": 0.0, "count": 0, "rationales": [], "evidence": []}
    )
    for pred in predictions:
        onvoc = pred.onvoc_id
        if not onvoc:
            continue
        score = float(pred.score)
        meta = stats[onvoc]
        meta["score"] += score
        meta["count"] += 1
        if pred.rationale:
            meta["rationales"].append(pred.rationale)
        if pred.evidence:
            meta["evidence"].extend(pred.evidence[:3])
    aggregated = []
    for onvoc, meta in stats.items():
        avg_score = meta["score"] / max(meta["count"], 1)
        aggregated.append(
            {
                "onvoc_id": onvoc,
                "avg_score": avg_score,
                "votes": meta["count"],
                "rationales": meta["rationales"],
                "evidence": meta["evidence"],
            }
        )
    aggregated.sort(key=lambda r: (r["avg_score"], r["votes"]), reverse=True)
    return aggregated


def _select_candidates(
    task: mapper.TaskRecord,
    anchors: List[mapper.Anchor],
    max_candidates: int,
    required_level: Optional[int] = None,
) -> List[Dict[str, str]]:
    scored = []
    for anchor in anchors:
        if required_level is not None and getattr(anchor, "level", None) != required_level:
            continue
        result = anchor.score(task)
        if result:
            scored.append((result.score, anchor))
    scored.sort(key=lambda tup: tup[0], reverse=True)
    candidates = []
    for score, anchor in scored[:max_candidates]:
        if anchor.onvoc_uri == STUDY_DESIGN_ONVOC:
            continue
        candidates.append({
            "id": anchor.onvoc_uri,
            "label": anchor.label or anchor.onvoc_uri,
            "definition": "",
            "level": getattr(anchor, "level", None),
        })
    if not candidates:
        fallback: List[Dict[str, str]] = []
        for anchor in anchors:
            if required_level is not None and getattr(anchor, "level", None) != required_level:
                continue
            if anchor.onvoc_uri == STUDY_DESIGN_ONVOC:
                continue
            fallback.append({
                "id": anchor.onvoc_uri,
                "label": anchor.label or anchor.onvoc_uri,
                "definition": "",
                "level": getattr(anchor, "level", None),
            })
        fallback.sort(key=lambda item: item["label"])
        candidates = fallback[:max_candidates]
    return candidates


def _should_accept(best: Dict[str, Any], runner: Optional[Dict[str, Any]], votes: int, threshold: float, margin: float) -> bool:
    if not best:
        return False
    if best["avg_score"] < threshold:
        return False
    if best["onvoc_id"] == STUDY_DESIGN_ONVOC:
        return False
    gap = best["avg_score"] - (runner["avg_score"] if runner else 0.0)
    if gap >= margin:
        return True
    if best["votes"] >= max(1, int(votes * 0.6)) and gap >= 0.05:
        return True
    return False


def _write_edge(
    session,
    task_id: str,
    onvoc_id: str,
    score: float,
    margin: float,
    llm_payload: Dict[str, Any],
    loader_version: str,
    *,
    onvoc_level: Optional[int] = None,
    parent_l2: Optional[str] = None,
) -> None:
    session.run(
        """
        MATCH (t:Task {id:$task_id})
        MATCH (o:ONVOC {id:$onvoc})
        MERGE (t)-[r:MAPS_TO]->(o)
        SET r.source=$source,
            r.method=$method,
            r.vocab="ONVOC",
            r.confidence=$score,
            r.margin=$margin,
            r.loader_version=$loader,
            r.evidence_json=$evidence,
            r.llm_votes=$votes,
            r.updated_at=datetime(),
            r.onvoc_level = coalesce($onvoc_level, r.onvoc_level),
            r.parent_l2 = CASE WHEN $parent_l2 IS NOT NULL THEN $parent_l2 ELSE r.parent_l2 END
        """,
        task_id=task_id,
        onvoc=onvoc_id,
        score=round(score, 4),
        margin=round(margin, 4),
        evidence=json.dumps(llm_payload, ensure_ascii=False),
        loader=loader_version,
        source="onvoc_llm",
        method="llm_gemini_v1",
        votes=llm_payload.get("votes"),
        onvoc_level=onvoc_level,
        parent_l2=parent_l2,
    )


def _fetch_borderline_tasks(driver, normalization, limit, database, sources):
    tasks = mapper.fetch_tasks(
        driver,
        normalization=normalization,
        only_unmapped=True,
        limit=limit,
        sources=sources,
        database=database,
    )
    return tasks


@app.command()

def run(
    config: Path = typer.Option(..., exists=True, readable=True, help="mapping_rules.yaml"),
    generated_rules: Optional[Path] = typer.Option(None, exists=True, readable=True, help="Optional generated rules file"),
    settings: Optional[Path] = typer.Option(None, exists=True, readable=True, help="mapping_settings.yaml"),
    uri: str = typer.Option("bolt://localhost:7687", help="Neo4j URI"),
    user: str = typer.Option("neo4j", help="Neo4j user"),
    password: str = typer.Option(..., prompt=True, hide_input=True, help="Neo4j password"),
    database: str = typer.Option("neo4j", help="Neo4j database"),
    model: str = typer.Option(DEFAULT_MODEL, help="Gemini model identifier"),
    limit: Optional[int] = typer.Option(None, help="Max tasks to process"),
    min_llm_score: Optional[float] = typer.Option(None, help="Override L2 acceptance threshold (default from config)"),
    min_llm_margin: Optional[float] = typer.Option(None, help="Override margin threshold (default 0.20)"),
    candidates_k: int = typer.Option(6, help="Fallback top-N anchors to show LLM"),
    votes: int = typer.Option(5, help="LLM vote count"),
    max_retries: int = typer.Option(1, min=0, help="Extra retries per vote on invalid JSON"),
    batch_size: int = typer.Option(10, min=1, help="Number of tasks per LLM batch"),
    batch_delay: float = typer.Option(1.0, help="Seconds to wait between votes"),
    llm_backoff: float = typer.Option(2.0, help="Initial backoff used after rate limits"),
    dry_run: bool = typer.Option(False, help="Log acceptances but skip writes"),
    hierarchy_mode: Optional[str] = typer.Option(None, help="Override hierarchical mode: l2_only or l2_then_l3"),
) -> None:
    llm_cfg = _load_llm_config(model)
    rules_cfg, map_settings = mapper.load_settings(config, settings, generated_rules)
    hier_cfg = map_settings.hierarchical
    hier_mode = (hierarchy_mode or hier_cfg.mode or "l2_only").lower()
    if hier_mode not in {"l2_only", "l2_then_l3"}:
        hier_mode = "l2_only"

    l2_threshold = min_llm_score if min_llm_score is not None else hier_cfg.l2_threshold or 0.85
    margin_threshold = min_llm_margin if min_llm_margin is not None else 0.20
    l3_threshold = hier_cfg.l3_threshold or max(l2_threshold, 0.90)
    l2_candidate_cap = hier_cfg.max_l2_candidates or candidates_k
    l3_candidate_cap = hier_cfg.max_l3_candidates or max(10, candidates_k)

    anchors = mapper.load_anchors(rules_cfg, map_settings)

    driver = mapper.build_driver(uri, user, password)
    hierarchy_meta = mapper.fetch_onvoc_hierarchy_map(driver, database)
    mapper.annotate_anchor_hierarchy(anchors, hierarchy_meta)
    l2_anchors = [anchor for anchor in anchors if getattr(anchor, "level", None) == 2]
    if not l2_anchors:
        l2_anchors = anchors
    tasks = _fetch_borderline_tasks(
        driver,
        map_settings.normalization,
        limit=limit,
        database=database,
        sources=map_settings.proposer.sources,
    )

    prompts: List[TaskPrompt] = []
    for task in tasks:
        candidates = _select_candidates(task, l2_anchors, l2_candidate_cap, required_level=2)
        if candidates:
            prompts.append(TaskPrompt(task=task, candidates=candidates, stage="l2"))

    if not prompts:
        typer.echo("No candidate tasks found for LLM pass.")
        driver.close()
        return

    accepted_entries: List[Dict[str, Any]] = []
    review_count = 0

    with driver.session(database=database) as session:
        for idx in range(0, len(prompts), batch_size):
            batch = prompts[idx : idx + batch_size]
            votes_payload = _batched_votes(
                batch,
                llm_cfg,
                votes,
                max_attempts=max_retries + 1,
                batch_delay=batch_delay,
                backoff=llm_backoff,
            )
            total_votes = len(votes_payload)
            grouped = _group_predictions(batch, votes_payload)
            for prompt_entry in batch:
                task = prompt_entry.task
                predictions = grouped.get(task.id, [])
                agg = _aggregate_predictions(predictions)
                best = agg[0] if agg else None
                runner = agg[1] if len(agg) > 1 else None
                if _should_accept(best, runner, total_votes, l2_threshold, margin_threshold):
                    llm_data = {
                        "votes": total_votes,
                        "raw_predictions": [pred.model_dump() for pred in predictions],
                        "candidates": prompt_entry.candidates,
                    }
                    margin = best["avg_score"] - (runner["avg_score"] if runner else 0.0)
                    accepted_entries.append(
                        {
                            "task": task,
                            "l2_id": best["onvoc_id"],
                            "l2_label": _find_candidate_label(prompt_entry.candidates, best["onvoc_id"]),
                            "l2_score": best["avg_score"],
                            "margin": margin,
                            "llm_data": llm_data,
                        }
                    )
                else:
                    if best:
                        label = best["onvoc_id"]
                        best_score = float(best.get("avg_score", 0.0))
                        best_votes = int(best.get("votes", 0))
                        print(
                            f"REVIEW  {task.id} (best={label}, score={best_score:.2f}, votes={best_votes})"
                        )
                    else:
                        print(f"REVIEW  {task.id} (best=none)")
                    review_count += 1

        if hier_mode == "l2_then_l3" and accepted_entries:
            l3_prompts: List[TaskPrompt] = []
            entry_by_task: Dict[str, Dict[str, Any]] = {}
            for entry in accepted_entries:
                children = mapper.fetch_onvoc_children(
                    driver,
                    parent_onvoc_id=entry["l2_id"],
                    limit=l3_candidate_cap,
                    database=database,
                )
                if not children:
                    continue
                candidate_list = [
                    {
                        "id": child["onvoc_id"],
                        "label": child.get("label") or child["onvoc_id"],
                        "definition": child.get("definition", ""),
                        "parent_l2": child.get("parent_l2"),
                    }
                    for child in children
                ]
                entry["l3_candidate_ids"] = {cand["id"] for cand in candidate_list}
                entry_by_task[entry["task"].id] = entry
                l3_prompts.append(
                    TaskPrompt(
                        task=entry["task"],
                        candidates=candidate_list,
                        stage="l3",
                        parent_l2=entry["l2_id"],
                        parent_l2_label=entry["l2_label"],
                    )
                )

            if l3_prompts:
                l3_votes_payload = _batched_votes(
                    l3_prompts,
                    llm_cfg,
                    votes,
                    max_attempts=max_retries + 1,
                    batch_delay=batch_delay,
                    backoff=llm_backoff,
                )
                total_child_votes = len(l3_votes_payload)
                grouped_children = _group_predictions(l3_prompts, l3_votes_payload)
                for prompt_entry in l3_prompts:
                    entry = entry_by_task[prompt_entry.task.id]
                    predictions = grouped_children.get(prompt_entry.task.id, [])
                    agg = _aggregate_predictions(predictions)
                    best = agg[0] if agg else None
                    runner = agg[1] if len(agg) > 1 else None
                    if not best or best["onvoc_id"].upper() == "NONE":
                        continue
                    if best["onvoc_id"] not in entry.get("l3_candidate_ids", set()):
                        continue
                    parent_ok = True
                    if hier_cfg.require_parent_consistency:
                        parent_ok = any(
                            cand["id"] == best["onvoc_id"] and cand.get("parent_l2", entry["l2_id"]) == entry["l2_id"]
                            for cand in prompt_entry.candidates
                        )
                    if parent_ok and _should_accept(best, runner, total_child_votes, l3_threshold, margin_threshold):
                        entry["l3_prediction"] = {
                            "onvoc_id": best["onvoc_id"],
                            "score": best["avg_score"],
                            "margin": best["avg_score"] - (runner["avg_score"] if runner else 0.0),
                            "llm_data": {
                                "votes": total_child_votes,
                                "raw_predictions": [pred.model_dump() for pred in predictions],
                                "candidates": prompt_entry.candidates,
                            },
                        }

        loader_version = rules_cfg.get("version", "dev")
        accepted_count = 0
        l3_count = 0
        for entry in accepted_entries:
            accepted_count += 1
            if dry_run:
                print(
                    f"DRY-RUN ACCEPT {entry['task'].id} → {entry['l2_id']} (avg={entry['l2_score']:.2f})"
                )
            else:
                _write_edge(
                    session,
                    entry["task"].id,
                    entry["l2_id"],
                    entry["l2_score"],
                    entry["margin"],
                    entry["llm_data"],
                    loader_version,
                    onvoc_level=2,
                )
                print(
                    f"ACCEPT {entry['task'].id} → {entry['l2_id']} (avg={entry['l2_score']:.2f})"
                )

            l3_pred = entry.get("l3_prediction")
            if l3_pred:
                l3_count += 1
                if dry_run:
                    print(
                        f"DRY-RUN    + L3 {entry['task'].id} → {l3_pred['onvoc_id']} (avg={l3_pred['score']:.2f})"
                    )
                else:
                    _write_edge(
                        session,
                        entry["task"].id,
                        l3_pred["onvoc_id"],
                        l3_pred["score"],
                        l3_pred["margin"],
                        l3_pred["llm_data"],
                        loader_version,
                        onvoc_level=3,
                        parent_l2=entry["l2_id"],
                    )
                    print(
                        f"         + L3 {entry['task'].id} → {l3_pred['onvoc_id']} (avg={l3_pred['score']:.2f})"
                    )

    driver.close()
    mode = "DRY-RUN" if dry_run else "APPLY"
    print(
        f"LLM mapping complete ({mode}). accepted={len(accepted_entries)}, l3={l3_count}, review={review_count}"
    )
if __name__ == "__main__":
    app()
