import concurrent.futures
import json
import pathlib
import random
import re
from collections import Counter
from typing import Any

import os
from openai import OpenAI

from .dr_score import dr_score, normalise_by_task
from .vocab_loader import id2level0, id2name, load_vocab, task2concept

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
if not DEEPSEEK_API_KEY:
    raise RuntimeError(
        "DEEPSEEK_API_KEY must be set to use DeepSeek via OpenAI-compatible API"
    )

DEEPSEEK_API_URL = os.getenv(
    "DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions"
)
DEEPSEEK_API_BASE = os.getenv(
    "DEEPSEEK_API_BASE",
    # Derive base from URL if provided (strip path like /v1/chat/completions)
    DEEPSEEK_API_URL.split("/v1")[0]
    if "/v1" in DEEPSEEK_API_URL
    else "https://api.deepseek.com",
)

client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_API_BASE)


def _mock_llm(prompt: str, model: str, temperature: float, vocab: list) -> str:
    # For demonstration, randomly select 2-5 constructs from vocab
    # Not used in the actual implementation
    k = random.randint(2, min(5, len(vocab)))
    constructs = random.sample(vocab, k)
    return json.dumps(
        [
            {
                "id": c["id"],
                "name": c["name"],
                "confidence": round(random.uniform(0.6, 1.0), 2),
            }
            for c in constructs
        ]
    )


def _calc_cs(confs: list[float]) -> float:
    """Calculate CS_norm: proportion of constructs with confidence >= 0.8."""
    if not confs:
        return 0.0
    k_hi = sum(c >= 0.8 for c in confs)
    return round(k_hi / len(confs), 2)


def build_llm_prompt(
    task_id, contrast_name, task_description, excerpt, vocab, allowed_concepts=None
):
    """Build an LLM prompt with task-linked concepts for enrichment, using strict id-name pairs."""
    id2name_map = id2name()
    task2concept_map = task2concept()
    # Get task-linked concept names
    concept_ids = list(task2concept_map.get(task_id, []))
    concept_names = [id2name_map[cid] for cid in concept_ids if cid in id2name_map]
    context_line = (
        f"Known task-linked concepts: {', '.join(concept_names[:10])}"
        if concept_names
        else ""
    )
    # Build full id-name JSON list for TERMINOLOGY
    terminology_json = json.dumps(
        [{"id": v["id"], "name": v["name"]} for v in vocab], indent=2
    )
    prompt = f"""
You are a neuroscience expert. Given the following contrast and excerpt, annotate the most relevant Cognitive Atlas concepts.
You must select constructs ONLY from the following list (TERMINOLOGY).
For each construct, return its "id" and "name" exactly as given. Do not invent new ids or names. id and name must match TERMINOLOGY exactly.

For every selected construct, include the direction based on the contrast expression:
- "+1" if the construct is positively associated with the contrast
- "-1" if the construct is negatively associated with the contrast
- "0" if the association is neutral or unclear

Example output:
[
  {{"id": "CAO_00036", "name": "working memory", "llm_confidence": 0.95, "direction": "+1"}},
  {{"id": "CAO_00002", "name": "attention", "llm_confidence": 0.85, "direction": "-1"}}
]

TERMINOLOGY = {terminology_json}

{context_line}
CONTRAST: {contrast_name}
TASK: {task_description}
EXCERPT: {excerpt}
"""
    return prompt


def _deepseek_reasoner_llm(
    prompt: str, model: str, temperature: float, vocab: list
) -> str:
    messages = [{"role": "user", "content": prompt}]
    response = client.chat.completions.create(
        model=model,  # "deepseek-reasoner"
        messages=messages,
        temperature=temperature,
        max_tokens=1024,
    )
    content = response.choices[0].message.content
    reasoning_content = getattr(response.choices[0].message, "reasoning_content", None)
    # Optionally, you can log or return reasoning_content for QC
    return content


def extract_json_from_markdown(text):
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        return match.group(1)
    return text


def annotate_dataset(
    contrasts_json: str | pathlib.Path,
    vocab_json: str | pathlib.Path,
    n_passes: int = 5,
    model: str = "deepseek-reasoner",
    temperature: float = 0.7,
    parallel: bool = False,
    max_workers: int = 5,
) -> list[dict[str, Any]]:
    """
    Annotate all contrasts in a dataset using an LLM ensemble and Cognitive Atlas vocab.
    Writes <dataset>_annotations.json and returns the annotation list.
    If parallel=True, LLM calls for n_passes are made concurrently (max_workers controls concurrency).
    """
    # Load input JSON
    with open(contrasts_json) as f:
        contrast_data = json.load(f)
    # Load vocab
    vocab = (
        load_vocab()
        if isinstance(vocab_json, str) and vocab_json.endswith(".json")
        else vocab_json
    )
    id2name_map = id2name()
    id2level0_map = id2level0()
    task2concept_map = task2concept()
    # Load ns_counts.json for DR_norm
    ns_counts_path = "data/ns_counts.json"
    if not pathlib.Path(ns_counts_path).exists():
        ns_counts_path = pathlib.Path(__file__).parent.parent / "data/ns_counts.json"
    with open(ns_counts_path) as f:
        ns_index = json.load(f)
    pubmed_cache = {}
    results = []
    log_hit_dict = {}
    output_dir = pathlib.Path("llm_cogitive_function/data/processed_with_direction")
    # previous output_dir = pathlib.Path("llm_cogitive_function/data/processed")
    output_dir.mkdir(parents=True, exist_ok=True)

    for dataset, contrasts in contrast_data.items():
        dataset_results = []
        for c_name, c_info in contrasts.items():
            task = c_info["task_name"]
            expr = c_info["contrast"]
            excerpt = c_info["excerpt"]
            # Build LLM prompt with enrichment
            prompt = build_llm_prompt(task, c_name, expr, excerpt, vocab)
            # n-pass ensemble (parallel or serial)
            constructs_list = []
            if parallel:
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=max_workers
                ) as executor:
                    futures = [
                        executor.submit(
                            _deepseek_reasoner_llm, prompt, model, temperature, vocab
                        )
                        for _ in range(n_passes)
                    ]
                    for fut in concurrent.futures.as_completed(futures):
                        try:
                            resp = fut.result()
                            clean_resp = extract_json_from_markdown(resp)
                            try:
                                constructs_list.append(json.loads(clean_resp))
                            except json.JSONDecodeError:
                                fixed = clean_resp.replace("'", '"')
                                try:
                                    constructs_list.append(json.loads(fixed))
                                except Exception as e:
                                    print(
                                        f"LLM call failed (after fix): {e}\nRaw output: {clean_resp}"
                                    )
                        except Exception as e:
                            print(f"LLM call failed: {e}")
            else:
                for _ in range(n_passes):
                    resp = _deepseek_reasoner_llm(prompt, model, temperature, vocab)
                    clean_resp = extract_json_from_markdown(resp)
                    try:
                        constructs_list.append(json.loads(clean_resp))
                    except json.JSONDecodeError:
                        fixed = clean_resp.replace("'", '"')
                        try:
                            constructs_list.append(json.loads(fixed))
                        except Exception as e:
                            print(
                                f"LLM call failed (after fix): {e}\nRaw output: {clean_resp}"
                            )
            # Aggregate frequency (ensemble-frequency confidence)
            freq = Counter(item["id"] for run in constructs_list for item in run)
            constructs = [
                {
                    "id": id_,
                    "name": id2name_map.get(id_, "UNKNOWN"),
                    "llm_confidence": round(freq[id_] / n_passes, 2),
                    "direction": (
                        max(
                            (
                                item["direction"]
                                for run in constructs_list
                                for item in run
                                if item["id"] == id_
                            ),
                            key=lambda x: sum(
                                1
                                for run in constructs_list
                                for item in run
                                if item["id"] == id_ and item["direction"] == x
                            ),
                        )
                        if any(
                            "direction" in item
                            for run in constructs_list
                            for item in run
                            if item["id"] == id_
                        )
                        else "0"
                    ),
                }
                for id_ in freq
            ]
            # DR log_hit_dict accumulate
            for c in constructs:
                key = (task, c["id"])
                log_hit = dr_score(task, c["id"], ns_index, pubmed_cache)
                log_hit_dict[key] = log_hit
            cs_norm = _calc_cs([c["llm_confidence"] for c in constructs])
            # Level-0 functional clusters
            clusters = {}
            for c in constructs:
                dom = id2level0_map.get(c["id"], "Other")
                clusters.setdefault(dom, []).append(c["name"])
            output = {
                "contrast_name": c_name,
                "task_name": task,
                "constructs": constructs,
                "CS_norm": cs_norm,
                "functional_clusters": clusters,
            }
            results.append(output)
            dataset_results.append(output)
        # Write per-dataset JSON to output_dir
        out_path = output_dir / f"{dataset}_annotations.json"
        with open(out_path, "w") as f:
            json.dump(dataset_results, f, indent=2)

    # After all, normalize and add DR_norm
    dr_norm_dict = normalise_by_task(log_hit_dict)
    for block in results:
        task = block["task_name"]
        for c in block["constructs"]:
            cid = c["id"]
            c["DR_norm"] = dr_norm_dict.get((task, cid), 0.1)

    return results


# Test case for DeepSeek Reasoner LLM integration
if __name__ == "__main__":
    test_prompt = 'List two cognitive constructs in JSON: [{"id":"CAO_00001","name":"working memory","confidence":0.95}]'
    response = client.chat.completions.create(
        model="deepseek-reasoner",
        messages=[{"role": "user", "content": test_prompt}],
        temperature=0.7,
        max_tokens=1024,
    )
    content = response.choices[0].message.content
    reasoning_content = getattr(response.choices[0].message, "reasoning_content", None)
    print("DeepSeek Reasoner output (content):", content)
    print("DeepSeek Reasoner output (reasoning_content):", reasoning_content)
    try:
        clean_content = extract_json_from_markdown(content)
        parsed = json.loads(clean_content)
        print("Parsed output:", parsed)
    except Exception as e:
        print("Failed to parse LLM output:", e)
