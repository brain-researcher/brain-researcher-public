"""CLI commands for the sharded GABRIEL pipeline."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from brain_researcher.services.br_kg.etl.evaluation.gabriel_kggen_eval import (
    evaluate_kggen_coverage,
)
from brain_researcher.services.br_kg.etl.evaluation.gabriel_onvoc_map import (
    map_kggen_to_onvoc,
)
from brain_researcher.services.br_kg.etl.gabriel_generator import (
    DEFAULT_CACHE_DIR,
    DEFAULT_OUTPUT_ROOT,
    GabrielPipelineGenerator,
    load_manifest_status,
    resolve_manifest_path,
)
from brain_researcher.services.br_kg.etl.loaders.gabriel_loader import (
    GabrielMeasurementLoader,
)

app = typer.Typer(help="GABRIEL pipeline commands")
console = Console()

QUALITY_PROFILE_DESCRIPTIONS = {
    "high_precision": "strict, audit-focused gate",
    "balanced": "default ingest profile",
    "balanced_marginal": "near-threshold backfill profile",
    "kg_bootstrap": "bootstrap profile with broad recall",
    "kg_task_panel": "KGGEN task panel ingest profile",
}
QUALITY_PROFILE_ORDER = (
    "high_precision",
    "balanced",
    "balanced_marginal",
    "kg_bootstrap",
    "kg_task_panel",
)


def _quality_profile_choices_text() -> str:
    available_profiles = GabrielMeasurementLoader.QUALITY_PROFILES
    labeled_profiles: list[str] = []

    for profile_name in QUALITY_PROFILE_ORDER:
        if profile_name not in available_profiles:
            continue
        description = QUALITY_PROFILE_DESCRIPTIONS.get(profile_name)
        if description:
            labeled_profiles.append(f"{profile_name} ({description})")
        else:
            labeled_profiles.append(profile_name)

    for profile_name in sorted(available_profiles):
        if profile_name in QUALITY_PROFILE_ORDER:
            continue
        labeled_profiles.append(profile_name)

    return ", ".join(labeled_profiles)


QUALITY_PROFILE_HELP = (
    "GABRIEL gate profile. Available: "
    f"{_quality_profile_choices_text()}. Unknown values fall back to high_precision."
)


def _normalize_quality_profile(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in GabrielMeasurementLoader.QUALITY_PROFILES:
        return normalized

    available = ", ".join(sorted(GabrielMeasurementLoader.QUALITY_PROFILES))
    console.print(
        "[yellow]Unknown quality profile "
        f"'{value}'. Falling back to 'high_precision'. "
        f"Available: {available}.[/yellow]"
    )
    return "high_precision"


@app.command("generate")
def generate(
    limit: int = typer.Option(
        200,
        "--limit",
        "-n",
        min=0,
        help="Maximum number of publications to process (0 = all).",
    ),
    offset: int = typer.Option(
        0,
        "--offset",
        min=0,
        help="Publication offset for pagination.",
    ),
    shard_size: int = typer.Option(
        25,
        "--shard-size",
        "-s",
        min=1,
        help="Number of publications per output shard.",
    ),
    run_id: str | None = typer.Option(
        None,
        "--run-id",
        help="Optional run identifier. Defaults to timestamped run id.",
    ),
    output_root: Path = typer.Option(
        DEFAULT_OUTPUT_ROOT,
        "--output-root",
        help="Base output directory for generated shards.",
    ),
    cache_dir: Path = typer.Option(
        DEFAULT_CACHE_DIR,
        "--cache-dir",
        help="Scholarly metadata cache directory for fallback mode.",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Optional model hint passed to LLMRouter.",
    ),
    max_records_per_publication: int = typer.Option(
        1,
        "--max-records",
        min=1,
        max=5,
        help="Max records emitted per publication.",
    ),
    cache_fallback: bool = typer.Option(
        True,
        "--cache-fallback/--no-cache-fallback",
        help="Fallback to scholarly metadata cache when Neo4j has no publications.",
    ),
    pubget_extracted_dir: Path | None = typer.Option(
        None,
        "--pubget-extracted-dir",
        help=(
            "Optional pubget extractedData directory (expects metadata.csv + text.csv). "
            "When provided, generation uses pubget papers instead of querying Neo4j/cache."
        ),
    ),
    pubget_include_body: bool = typer.Option(
        True,
        "--pubget-include-body/--pubget-no-body",
        help="Include pubget body text in prompt payload.",
    ),
    pubget_body_char_limit: int = typer.Option(
        12000,
        "--pubget-body-char-limit",
        min=0,
        help="Max body characters per pubget paper included in prompt payload (0 disables body).",
    ),
    force_heuristic: bool = typer.Option(
        False,
        "--force-heuristic",
        help="Skip LLMRouter and always use heuristic generation.",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Replace existing run directory if run id already exists.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print full manifest as JSON.",
    ),
) -> None:
    """Generate sharded GABRIEL JSONL + raw responses + manifest."""

    generator = GabrielPipelineGenerator(
        output_root=output_root,
        cache_dir=cache_dir,
        model_hint=model,
        max_records_per_publication=max_records_per_publication,
    )

    try:
        manifest = generator.generate(
            limit=limit,
            offset=offset,
            shard_size=shard_size,
            run_id=run_id,
            use_cache_fallback=cache_fallback,
            force_heuristic=force_heuristic,
            overwrite=overwrite,
            pubget_extracted_dir=pubget_extracted_dir,
            pubget_include_body=pubget_include_body,
            pubget_body_char_limit=pubget_body_char_limit,
        )
    except Exception as exc:
        console.print(f"[red]Generation failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    if json_output:
        console.print_json(data=manifest)
        return

    counts = manifest.get("counts", {})
    paths = manifest.get("paths", {})
    source = manifest.get("source", "unknown")
    console.print(f"[green]Run:[/green] {manifest.get('run_id')}")
    console.print(f"[green]Source:[/green] {source}")
    console.print(f"[green]Manifest:[/green] {paths.get('manifest_path')}")
    console.print(
        "[green]Generated:[/green] "
        f"{counts.get('records_generated', 0)} records in "
        f"{counts.get('shards', 0)} shards"
    )
    console.print(
        "[dim]LLM records: "
        f"{counts.get('records_llm', 0)} | "
        f"Heuristic records: {counts.get('records_heuristic', 0)} | "
        f"LLM fallbacks: {counts.get('llm_errors', 0)}[/dim]"
    )
    failure_reasons = counts.get("llm_failure_reasons") or {}
    if failure_reasons:
        reason_summary = ", ".join(
            f"{reason}={count}" for reason, count in sorted(failure_reasons.items())
        )
        console.print(f"[dim]Fallback reasons:[/dim] {reason_summary}")


@app.command("ingest")
def ingest(
    manifest: Path | None = typer.Option(
        None,
        "--manifest",
        help=(
            "Path to generation manifest JSON. Defaults to latest run. "
            "Manifests marked promotion_strategy=exact_id_migration_only are "
            "migration-only and will be rejected by ingest."
        ),
    ),
    output_root: Path = typer.Option(
        DEFAULT_OUTPUT_ROOT,
        "--output-root",
        help="Output root used to infer latest manifest.",
    ),
    mode: str = typer.Option(
        "spine",
        "--mode",
        help="Loader mode passed to GabrielMeasurementLoader.",
    ),
    quality_profile: str = typer.Option(
        "balanced",
        "--quality-profile",
        callback=_normalize_quality_profile,
        help=QUALITY_PROFILE_HELP,
    ),
    ingest_checkpoint_path: Path | None = typer.Option(
        None,
        "--ingest-checkpoint-path",
        help="Optional loader checkpoint path. Defaults to run_dir/ingest_checkpoint.json.",
    ),
    resume: bool = typer.Option(
        True,
        "--resume/--no-resume",
        help="Skip shards already marked as completed in manifest.",
    ),
    create_missing_targets: bool = typer.Option(
        True,
        "--create-missing-targets/--no-create-missing-targets",
        help="Create missing Concept/Region/Task target nodes during ingest.",
    ),
    progress_log_every: int = typer.Option(
        100,
        "--progress-log-every",
        min=1,
        help="Emit ingest heartbeat logs every N parsed records.",
    ),
    stall_warn_seconds: int = typer.Option(
        180,
        "--stall-warn-seconds",
        min=0,
        help="Emit stall warnings after this many seconds of inactivity (0 disables).",
    ),
    log_timing_breakdown: bool = typer.Option(
        False,
        "--log-timing-breakdown/--no-log-timing-breakdown",
        help="Include average stage timing breakdown in ingest heartbeat logs.",
    ),
    progress_log_level: str = typer.Option(
        "info",
        "--progress-log-level",
        help="Progress log level for ingest heartbeats (info or debug).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print ingest result as JSON.",
    ),
) -> None:
    """Ingest previously generated shard files into Neo4j."""

    try:
        resolved_manifest = resolve_manifest_path(manifest, output_root)
    except Exception as exc:
        console.print(f"[red]Manifest resolution failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    generator = GabrielPipelineGenerator(output_root=output_root)

    try:
        result = generator.ingest(
            manifest_path=resolved_manifest,
            mode=mode,
            resume=resume,
            quality_profile=quality_profile,
            ingest_checkpoint_path=ingest_checkpoint_path,
            create_missing_targets=create_missing_targets,
            progress_log_every=progress_log_every,
            stall_warn_seconds=stall_warn_seconds,
            log_timing_breakdown=log_timing_breakdown,
            progress_log_level=progress_log_level,
        )
    except Exception as exc:
        console.print(f"[red]Ingest failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    if json_output:
        console.print_json(data=result)
        return

    console.print(f"[green]Manifest:[/green] {result.get('manifest_path')}")
    console.print(f"[green]Status:[/green] {result.get('status')}")
    console.print(
        "[green]Quality profile:[/green] "
        f"{result.get('quality_profile', quality_profile)}"
    )
    console.print(
        "[green]Create missing targets:[/green] "
        f"{result.get('create_missing_targets', create_missing_targets)}"
    )
    console.print(
        "[green]Shards:[/green] "
        f"{result.get('shards_completed', 0)} completed, "
        f"{result.get('shards_failed', 0)} failed, "
        f"{result.get('shards_skipped', 0)} skipped"
    )
    console.print(
        f"[green]Records ingested:[/green] {result.get('records_ingested', 0)}"
    )
    console.print(f"[dim]Review queue:[/dim] {result.get('review_queue_path')}")
    console.print(f"[dim]Checkpoint:[/dim] {result.get('ingest_checkpoint_path')}")


@app.command("ingest-candidate-only")
def ingest_candidate_only(
    manifest: Path | None = typer.Option(
        None,
        "--manifest",
        help=(
            "Optional generation manifest JSON used to infer "
            "review_queue_candidate_only.jsonl."
        ),
    ),
    queue: Path | None = typer.Option(
        None,
        "--queue",
        help=(
            "Direct path to review_queue_candidate_only.jsonl. Overrides --manifest."
        ),
    ),
    output_root: Path = typer.Option(
        DEFAULT_OUTPUT_ROOT,
        "--output-root",
        help="Output root used to infer latest manifest when --queue is omitted.",
    ),
    source_quality_profile: str = typer.Option(
        "candidate_only",
        "--source-quality-profile",
        help=(
            "Annotation-only quality profile written into candidate-lane metadata. "
            "This does not apply benchmark gating."
        ),
    ),
    create_missing_targets: bool = typer.Option(
        True,
        "--create-missing-targets/--no-create-missing-targets",
        help="Create missing Concept/Region/Task target nodes during candidate replay.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print candidate-lane ingest result as JSON.",
    ),
) -> None:
    """Load candidate-only review queue rows into live Neo4j."""

    generator = GabrielPipelineGenerator(output_root=output_root)
    try:
        result = generator.ingest_candidate_only(
            manifest_path=manifest,
            queue_path=queue,
            source_quality_profile=source_quality_profile,
            create_missing_targets=create_missing_targets,
        )
    except Exception as exc:
        console.print(f"[red]Candidate-only ingest failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    if json_output:
        console.print_json(data=result)
        return

    stats = result.get("stats") or {}
    if result.get("manifest_path"):
        console.print(f"[green]Manifest:[/green] {result.get('manifest_path')}")
    console.print(f"[green]Candidate queue:[/green] {result.get('queue_path')}")
    console.print(
        "[green]Source quality profile:[/green] "
        f"{result.get('source_quality_profile', source_quality_profile)}"
    )
    console.print(
        "[green]Create missing targets:[/green] "
        f"{result.get('create_missing_targets', create_missing_targets)}"
    )
    console.print(
        "[green]Queue rows:[/green] "
        f"{stats.get('queue_rows_loaded', 0)} loaded, "
        f"{stats.get('queue_rows_skipped', 0)} skipped, "
        f"{stats.get('parse_errors', 0)} parse errors"
    )
    console.print(
        "[green]Graph delta:[/green] "
        f"{stats.get('nodes_created', 0)} nodes, "
        f"{stats.get('relationships_created', 0)} relationships"
    )
    if (
        int(stats.get("files_failed", 0) or 0) > 0
        or result.get("status") != "completed"
    ):
        console.print(
            "[red]Candidate-only ingest completed with failures:[/red] "
            f"{stats.get('files_failed', 0)} file(s) failed"
        )
        raise typer.Exit(1)


@app.command("status")
def status(
    manifest: Path | None = typer.Option(
        None,
        "--manifest",
        help="Path to generation manifest JSON. Defaults to latest run.",
    ),
    output_root: Path = typer.Option(
        DEFAULT_OUTPUT_ROOT,
        "--output-root",
        help="Output root used to infer latest manifest.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print status payload as JSON.",
    ),
) -> None:
    """Show status of generated shards and ingest progress."""

    try:
        resolved_manifest = resolve_manifest_path(manifest, output_root)
        status_payload = load_manifest_status(resolved_manifest)
    except Exception as exc:
        console.print(f"[red]Status failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    if json_output:
        console.print_json(data=status_payload)
        return

    summary = status_payload.get("summary", {})

    console.print(f"[green]Run:[/green] {status_payload.get('run_id')}")
    console.print(f"[green]Manifest:[/green] {status_payload.get('manifest_path')}")
    console.print(
        "[green]Ingest status:[/green] "
        f"{status_payload.get('manifest_ingest_status', 'unknown')}"
    )

    top_table = Table(title="GABRIEL Summary")
    top_table.add_column("Metric", style="cyan")
    top_table.add_column("Value", style="green", justify="right")
    top_table.add_row("Shards total", str(summary.get("shards_total", 0)))
    top_table.add_row("Shards ingested", str(summary.get("shards_ingested", 0)))
    top_table.add_row("Records expected", str(summary.get("records_expected", 0)))
    top_table.add_row("Records on disk", str(summary.get("records_on_disk", 0)))
    top_table.add_row("Records ingested", str(summary.get("records_ingested", 0)))
    top_table.add_row("LLM records", str(summary.get("records_llm", 0)))
    top_table.add_row("Heuristic records", str(summary.get("records_heuristic", 0)))
    top_table.add_row("LLM fallbacks", str(summary.get("llm_errors", 0)))
    failure_reasons = summary.get("llm_failure_reasons") or {}
    if failure_reasons:
        reason_summary = ", ".join(
            f"{reason}={count}" for reason, count in sorted(failure_reasons.items())
        )
        top_table.add_row("Fallback reasons", reason_summary)
    console.print(top_table)

    shard_table = Table(title="Shard Status")
    shard_table.add_column("Shard", justify="right", style="cyan")
    shard_table.add_column("Records", justify="right")
    shard_table.add_column("On Disk", justify="right")
    shard_table.add_column("Ingest", style="green")
    shard_table.add_column("Ingested", justify="right")
    shard_table.add_column("Errors", justify="right", style="red")

    for shard in status_payload.get("shards", []):
        shard_table.add_row(
            str(shard.get("shard_id")),
            str(shard.get("records_expected", 0)),
            str(shard.get("records_on_disk", 0)),
            str(shard.get("ingest_status", "pending")),
            str(shard.get("records_ingested", 0)),
            str(shard.get("errors", 0)),
        )

    console.print(shard_table)


@app.command("eval-kggen")
def eval_kggen(
    kggen_input: Path = typer.Option(
        ...,
        "--kggen-input",
        help="Path to KGGen JSON/JSONL file or directory of outputs.",
    ),
    manifest: Path | None = typer.Option(
        None,
        "--manifest",
        help="Baseline Gabriel manifest path. Defaults to latest run if baseline-jsonl is omitted.",
    ),
    baseline_jsonl: list[Path] = typer.Option(
        [],
        "--baseline-jsonl",
        help="Optional baseline Gabriel JSONL shard path (repeat flag for multiple files).",
    ),
    output_root: Path = typer.Option(
        DEFAULT_OUTPUT_ROOT,
        "--output-root",
        help="Output root used to infer latest baseline manifest when --manifest is omitted.",
    ),
    output_dir: Path = typer.Option(
        Path("data/br-kg/raw/gabriel/eval/kggen"),
        "--output-dir",
        help="Directory to write evaluation report and artifacts.",
    ),
    sample_size: int = typer.Option(
        300,
        "--sample-size",
        min=1,
        help="Maximum number of overlapping paper IDs to evaluate.",
    ),
    seed: int = typer.Option(
        13,
        "--seed",
        help="Random seed for paper sampling.",
    ),
    quality_profile: str = typer.Option(
        "balanced",
        "--quality-profile",
        callback=_normalize_quality_profile,
        help=(
            "Quality gate profile used for both baseline and KGGen records. "
            f"{QUALITY_PROFILE_HELP}"
        ),
    ),
    annotate_fraction: float = typer.Option(
        0.10,
        "--annotate-fraction",
        min=0.0,
        max=1.0,
        help="Fraction of sampled papers targeted for manual annotation planning.",
    ),
    strict_provenance: bool = typer.Option(
        True,
        "--strict-provenance/--no-strict-provenance",
        help="Reject KGGen-adapted records with missing required provenance fields.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print full evaluation payload as JSON.",
    ),
) -> None:
    """Evaluate KGGen candidates against baseline Gabriel records (research-only)."""

    try:
        payload = evaluate_kggen_coverage(
            kggen_input=kggen_input,
            output_dir=output_dir,
            manifest_path=manifest,
            baseline_jsonl_paths=baseline_jsonl,
            output_root=output_root,
            sample_size=sample_size,
            seed=seed,
            quality_profile=quality_profile,
            annotate_fraction=annotate_fraction,
            strict_provenance=strict_provenance,
        )
    except Exception as exc:
        console.print(f"[red]KGGen evaluation failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    if json_output:
        console.print_json(data=payload)
        return

    sample = payload.get("sample", {})
    coverage = payload.get("coverage", {})
    baseline = payload.get("baseline", {})
    kggen = payload.get("kggen", {})
    artifacts = payload.get("artifacts", {})

    console.print("[green]KGGen evaluation complete[/green]")
    console.print(f"[green]Report:[/green] {artifacts.get('report_path')}")
    console.print(f"[green]Artifacts dir:[/green] {output_dir}")

    summary_table = Table(title="KGGen Coverage Evaluation")
    summary_table.add_column("Metric", style="cyan")
    summary_table.add_column("Value", style="green", justify="right")
    summary_table.add_row("Papers evaluated", str(sample.get("papers_evaluated", 0)))
    summary_table.add_row(
        "Baseline accepted edges", str(coverage.get("baseline_high_conf_edges", 0))
    )
    summary_table.add_row(
        "KGGen accepted edges", str(coverage.get("kggen_high_conf_edges", 0))
    )
    summary_table.add_row(
        "New high-conf edges", str(coverage.get("new_high_conf_edges", 0))
    )
    summary_table.add_row("Edge yield delta", str(coverage.get("edge_yield_delta", 0)))
    summary_table.add_row(
        "Edge recall proxy",
        str(coverage.get("edge_recall_proxy")),
    )
    summary_table.add_row(
        "Baseline pass rate",
        f"{float(baseline.get('acceptance_rate', 0.0)):.3f}",
    )
    summary_table.add_row(
        "KGGen pass rate",
        f"{float(kggen.get('acceptance_rate', 0.0)):.3f}",
    )
    summary_table.add_row(
        "KGGen parse errors",
        str(kggen.get("parse_errors", 0)),
    )
    console.print(summary_table)


@app.command("map-onvoc")
def map_onvoc(
    kggen_input: Path = typer.Option(
        ...,
        "--kggen-input",
        help="Path to KGGEN-adapted JSON/JSONL file or directory.",
    ),
    output_dir: Path = typer.Option(
        Path("data/br-kg/raw/gabriel/eval/kggen/onvoc"),
        "--output-dir",
        help="Directory to write ONVOC mapping artifacts.",
    ),
    min_score: float = typer.Option(
        0.82,
        "--min-score",
        min=0.0,
        max=1.0,
        help="Minimum ONVOC mapping score to emit MAPS_TO edges.",
    ),
    same_as_threshold: float = typer.Option(
        0.97,
        "--same-as-threshold",
        min=0.0,
        max=1.0,
        help="Minimum score for SAME_AS edges (and method-restricted).",
    ),
    candidate_top_k: int = typer.Option(
        40,
        "--candidate-top-k",
        min=1,
        help="Top-K lexical candidates before rerank.",
    ),
    embedding_enabled: bool = typer.Option(
        True,
        "--embedding-enabled/--no-embedding",
        help="Enable Gemini embedding rerank for lexical candidates.",
    ),
    embedding_backend: str = typer.Option(
        "gemini",
        "--embedding-backend",
        help="Embedding backend (gemini|none).",
    ),
    embedding_model: str = typer.Option(
        "gemini-embedding-001",
        "--embedding-model",
        help="Embedding model name used by the backend.",
    ),
    embedding_batch_size: int = typer.Option(
        64,
        "--embedding-batch-size",
        min=1,
        help="Embedding API batch size.",
    ),
    embedding_timeout_sec: float = typer.Option(
        8.0,
        "--embedding-timeout-sec",
        min=1.0,
        help="Soft embedding timeout warning threshold in seconds.",
    ),
    margin_min: float = typer.Option(
        0.04,
        "--margin-min",
        min=0.0,
        max=1.0,
        help="Minimum top1-top2 margin for non-ambiguous auto-mapping.",
    ),
    normalize_targets: bool = typer.Option(
        True,
        "--normalize-targets/--no-normalize-targets",
        help="Write ONVOC-normalized KGGEN records for accepted mappings.",
    ),
    crosswalk_path: Path | None = typer.Option(
        None,
        "--crosswalk-path",
        help="Optional override path for ONVOC crosswalk YAML.",
    ),
    tree_path: Path | None = typer.Option(
        None,
        "--tree-path",
        help="Optional override path for ONVOC tree YAML.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print full mapping payload as JSON.",
    ),
) -> None:
    """Map KGGEN concept targets to ONVOC (research-only, no graph writes)."""

    try:
        payload = map_kggen_to_onvoc(
            kggen_input=kggen_input,
            output_dir=output_dir,
            min_score=min_score,
            same_as_threshold=same_as_threshold,
            candidate_top_k=candidate_top_k,
            embedding_enabled=embedding_enabled,
            embedding_backend=embedding_backend,
            embedding_model=embedding_model,
            embedding_batch_size=embedding_batch_size,
            embedding_timeout_sec=embedding_timeout_sec,
            margin_min=margin_min,
            normalize_targets=normalize_targets,
            crosswalk_path=crosswalk_path,
            tree_path=tree_path,
        )
    except Exception as exc:
        console.print(f"[red]ONVOC mapping failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    if json_output:
        console.print_json(data=payload)
        return

    summary = payload.get("summary", {})
    candidate_stats = payload.get("candidate_stats", {})
    embedding = payload.get("embedding", {})
    artifacts = payload.get("artifacts", {})
    methods = payload.get("method_counts", {})
    method_summary = ", ".join(
        f"{method}={count}" for method, count in sorted(methods.items())
    )

    console.print("[green]ONVOC mapping complete[/green]")
    console.print(f"[green]Report:[/green] {artifacts.get('report_path')}")
    console.print(f"[green]Artifacts dir:[/green] {output_dir}")

    table = Table(title="KGGEN -> ONVOC Mapping")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")
    table.add_row("Concept records", str(summary.get("concept_records", 0)))
    table.add_row("MAPS_TO edges", str(summary.get("maps_to_edges", 0)))
    table.add_row("SAME_AS edges", str(summary.get("same_as_edges", 0)))
    table.add_row("Review items", str(summary.get("review_items", 0)))
    table.add_row(
        "Skipped non-concept",
        str(summary.get("skipped_non_concept_records", 0)),
    )
    table.add_row("Mapping rate", f"{float(summary.get('mapping_rate', 0.0)):.3f}")
    table.add_row("SAME_AS rate", f"{float(summary.get('same_as_rate', 0.0)):.3f}")
    table.add_row(
        "No candidate (lexical)",
        str(candidate_stats.get("no_candidate_after_lexical", 0)),
    )
    table.add_row(
        "No candidate (embedding)",
        str(candidate_stats.get("no_candidate_after_embedding", 0)),
    )
    table.add_row(
        "Avg lexical candidates",
        f"{float(candidate_stats.get('avg_candidates_per_record', 0.0)):.2f}",
    )
    table.add_row(
        "Embedding backend",
        str(
            embedding.get("backend_active")
            or embedding.get("backend_requested")
            or "none"
        ),
    )
    table.add_row(
        "Embedding cache hit rate",
        f"{float(embedding.get('cache_hit_rate', 0.0)):.3f}",
    )
    if method_summary:
        table.add_row("Methods", method_summary)
    console.print(table)
