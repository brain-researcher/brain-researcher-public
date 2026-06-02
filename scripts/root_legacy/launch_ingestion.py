#!/usr/bin/env python3
"""
Launch Data Ingestion and Build Knowledge Graph

This script provides a comprehensive pipeline for ingesting all neuroimaging data
sources and building the BR-KG knowledge graph.

Usage:
    python launch_ingestion.py                  # Load all sources with config
    python launch_ingestion.py --quick          # Quick test with limited data
    python launch_ingestion.py --sources ca pm  # Load specific sources
    python launch_ingestion.py --docker         # Start services with Docker first

Author: Brain Researcher Team
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data_ingestion_launch.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

from brain_researcher.services.br_kg.graph.graph_factory import create_graph_client
from brain_researcher.services.br_kg.etl.load_all import MasterDataLoader


class DataIngestionLauncher:
    """Orchestrates the complete data ingestion pipeline."""

    def __init__(
        self,
        config_path: str = "configs/br-kg/data_config.json",
        docker: bool = False,
    ):
        """
        Initialize the launcher.

        Args:
            config_path: Path to configuration file
            docker: Whether to use Docker services
        """
        self.config_path = config_path
        self.docker = docker
        self.config = self._load_config()
        self.start_time = datetime.now()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file and normalise legacy layouts."""
        path = Path(self.config_path)
        if not path.exists():
            logger.warning("Config file %s not found, using defaults", self.config_path)
            return {"sources": {}, "create_links": True}

        try:
            with path.open(encoding="utf-8") as handle:
                raw_config = json.load(handle)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse config %s: %s", self.config_path, exc)
            raise

        if not isinstance(raw_config, dict):
            raise TypeError(
                f"Ingestion config must be a JSON object; got {type(raw_config).__name__}"
            )

        config: Dict[str, Any] = dict(raw_config)

        if isinstance(config.get("sources"), dict):
            sources = dict(config["sources"])
        else:
            sources = {}
            for key in list(config.keys()):
                if key in MasterDataLoader.SOURCE_DEFAULT_MODES and isinstance(config[key], dict):
                    sources[key] = config.pop(key)
            if not sources:
                for key in list(config.keys()):
                    if isinstance(config[key], dict):
                        sources[key] = config.pop(key)
        config["sources"] = sources
        config.setdefault("create_links", True)
        return config

    def _iter_local_resource_paths(self):
        """Yield (source, key, raw_value, resolved_path) for local resource hints."""
        path_keywords = ("path", "dir", "cache", "base", "workspace", "manifest", "download")
        sources = self.config.get("sources", {})
        for source_name, cfg in sources.items():
            if not isinstance(cfg, dict):
                continue
            for key, value in cfg.items():
                key_lower = str(key).lower()
                if not any(keyword in key_lower for keyword in path_keywords):
                    continue
                values: List[str] = []
                if isinstance(value, str):
                    values = [value]
                elif isinstance(value, (list, tuple)):
                    values = [item for item in value if isinstance(item, str)]
                else:
                    continue
                for raw in values:
                    if not raw or "://" in raw or raw.startswith("s3://") or raw.startswith("gs://"):
                        continue
                    expanded = os.path.expandvars(os.path.expanduser(raw))
                    candidate = Path(expanded)
                    resolved = candidate if candidate.is_absolute() else (project_root / candidate).resolve()
                    yield source_name, key, raw, resolved

    def check_environment(self) -> bool:
        """Check if the environment is properly set up."""
        logger.info("Checking environment...")

        all_passed = True

        def report(label: str, passed: bool, *, fatal: bool = True) -> None:
            nonlocal all_passed
            status = "✅" if passed else ("❌" if fatal else "⚠️")
            logger.info("  %s %s", status, label)
            if not passed and fatal:
                all_passed = False

        report("Python version ≥ 3.8", sys.version_info >= (3, 8))

        # Required Python packages
        for package in ("brain_researcher", "numpy", "sklearn", "requests"):
            try:
                __import__(package.replace("-", "_"))
                report(f"Package {package}", True)
            except ImportError:
                report(f"Package {package}", False)

        config_exists = Path(self.config_path).exists()
        report(f"Config file {self.config_path}", config_exists)

        # Ensure cache directory exists for ingestion helpers
        cache_dir = project_root / "data/br-kg/cache"
        if not cache_dir.exists():
            cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info("  ✅ Created %s", cache_dir)
        else:
            report("data/br-kg/cache directory", True, fatal=False)

        evidence_dir = project_root / "data/br-kg/raw/evidence"
        needs_evidence = any(
            isinstance(cfg, dict) and isinstance(cfg.get("data_path"), str)
            for cfg in self.config.get("sources", {}).values()
        )
        if needs_evidence:
            report("data/br-kg/raw/evidence directory", evidence_dir.exists(), fatal=False)

        neo4j_configured = bool(os.getenv("NEO4J_URI") and os.getenv("NEO4J_PASSWORD"))
        report("Neo4j backend configured", neo4j_configured, fatal=not neo4j_configured)
        if not neo4j_configured:
            logger.error("  ❌ Neo4j is required. Set NEO4J_URI/NEO4J_PASSWORD.")

        missing_resources = []
        for source, key, raw_value, resolved in self._iter_local_resource_paths():
            if not resolved.exists():
                missing_resources.append((source, key, raw_value, resolved))

        for source, key, raw_value, resolved in missing_resources:
            logger.warning(
                "  ⚠️  %s.%s path not found (%s → %s)",
                source,
                key,
                raw_value,
                resolved,
            )

        return all_passed

    def start_docker_services(self) -> bool:
        """Start Docker services if requested."""
        if not self.docker:
            return True

        logger.info("Starting Docker services...")

        try:
            # Check if Docker is installed
            subprocess.run(["docker", "--version"], check=True, capture_output=True)

            # Start services
            cmd = ["docker-compose", "up", "-d", "br_kg", "orchestrator", "redis"]
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                logger.info("  ✅ Docker services started")
                # Wait for services to be ready
                logger.info("  ⏳ Waiting for services to be ready...")
                time.sleep(10)
                return True
            else:
                logger.error(f"  ❌ Failed to start Docker services: {result.stderr}")
                return False

        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("  ⚠️  Docker not available, continuing without services")
            return True

    def ensure_neo4j_config(self) -> None:
        """Fail fast if Neo4j connection details are missing."""
        uri = os.getenv("NEO4J_URI")
        password = os.getenv("NEO4J_PASSWORD")
        user = os.getenv("NEO4J_USER", "neo4j")
        database = os.getenv("NEO4J_DATABASE", "(default)")

        if not uri or not password:
            raise RuntimeError(
                "Neo4j is now mandatory. Set NEO4J_URI and NEO4J_PASSWORD "
                "before running ingestion."
            )

        logger.info(
            "  ✅ Using Neo4j backend (uri=%s, user=%s, database=%s)",
            uri,
            user,
            database,
        )

    def run_ingestion(self, sources: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Run the data ingestion pipeline.

        Args:
            sources: Specific sources to load (None = all)

        Returns:
            Ingestion results
        """
        logger.info("Starting data ingestion pipeline...")

        # Ensure Neo4j is configured
        self.ensure_neo4j_config()

        # Initialize loader
        loader = MasterDataLoader(
            db_factory=create_graph_client,
            db_path=None,
        )

        try:
            # Run ingestion
            results = loader.load_all(sources=sources, config=self.config)

            # Print summary
            self._print_summary(results)

            return results

        finally:
            loader.close()

    def _print_summary(self, results: Dict[str, Any]):
        """Print a formatted summary of results."""
        print("\n" + "="*80)
        print("📊 DATA INGESTION SUMMARY")
        print("="*80)

        stats = results.get("statistics", {})

        results_payload = results.get("results", {})
        if not isinstance(results_payload, dict):
            results_payload = {}
        ingested_sources = stats.get("sources_loaded", [])
        if ingested_sources:
            print("\n✅ Sources Successfully Loaded:")
            for source in ingested_sources:
                entry = results_payload.get(source, {})
                if not isinstance(entry, dict):
                    print(f"  • {source} (mode: unknown)")
                    continue
                mode = entry.get("mode", "unknown")
                result_block = entry.get("result", {})
                print(f"  • {source} (mode: {mode})")
                if isinstance(result_block, dict):
                    for key, value in result_block.items():
                        if key == "error":
                            continue
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            print(f"      - {key}: {value:,}")
                        else:
                            print(f"      - {key}: {value}")
                elif result_block:
                    print(f"      - result: {result_block}")
        else:
            print("\n⚠️  No batch sources were loaded.")

        on_demand_entries = [
            (name, payload)
            for name, payload in results_payload.items()
            if isinstance(payload, dict) and payload.get("mode") == "on_demand"
        ]
        if on_demand_entries:
            print("\n🛰️ On-demand Sources:")
            for source, payload in sorted(on_demand_entries):
                registered = payload.get("registered")
                if registered is True:
                    status = "registered"
                    indicator = "✅"
                elif registered is False:
                    status = "registration failed"
                    indicator = "❌"
                else:
                    status = payload.get("warning", "configured")
                    indicator = "⚠️"
                print(f"  • {source}: {indicator} {status}")
                if payload.get("warning"):
                    print(f"      - note: {payload['warning']}")

        # Errors
        if stats.get("errors"):
            print("\n❌ Errors Encountered:")
            for error in stats["errors"]:
                print(f"  • {error}")

        # Overall statistics
        print("\n📈 Overall Statistics:")
        print(f"  • Total Entities: {stats.get('total_entities', 0):,}")
        print(f"  • Total Relationships: {stats.get('total_relationships', 0):,}")
        print(f"  • Duration: {stats.get('duration', 'N/A')}")

        # Special focus on BrainMap if loaded
        if "brainmap" in stats.get("sources_loaded", []):
            brainmap_stats = results.get("results", {}).get("brainmap", {})
            print("\n🧠 BrainMap Specific:")
            print(f"  • Experiments: {brainmap_stats.get('experiments', 0):,}")
            print(f"  • Contrasts: {brainmap_stats.get('contrasts', 0):,}")
            print(f"  • Coordinates: {brainmap_stats.get('coordinates', 0):,}")
            print(f"  • Coordinate Clusters: {brainmap_stats.get('clusters', 0):,}")
            print(f"  • Linked Papers: {brainmap_stats.get('papers', 0):,}")

        print("\n" + "="*80)

    def quick_test(self):
        """Run a quick test with limited data."""
        logger.info("Running quick test with limited data...")

        # Save original config and use test config
        original_config = self.config
        available_sources = original_config.get("sources", {})
        quick_sources = [
            source
            for source in (
                "cognitive_atlas",
                "pubmed",
                "neuroquery",
                "nimare",
                "neuroscout",
                "allen_hba",
            )
            if source in available_sources
        ]

        if not quick_sources:
            logger.warning("No quick-test sources found in configuration; skipping.")
            return {"results": {}, "statistics": {}}

        test_config: Dict[str, Any] = {"sources": {}, "create_links": False}
        for source in quick_sources:
            cfg = dict(available_sources.get(source, {}))
            if source == "pubmed":
                max_results = int(cfg.get("max_results", 25) or 25)
                cfg["max_results"] = min(max_results, 25)
            if source in {"neurovault", "openneuro"} and "limit" in cfg:
                cfg["limit"] = min(int(cfg["limit"] or 5), 5)
            if source in {"neuroquery", "nimare", "neuroscout", "allen_hba"}:
                cfg["mode"] = "on_demand"
            test_config["sources"][source] = cfg

        try:
            self.config = test_config
            results = self.run_ingestion(sources=quick_sources)
        finally:
            self.config = original_config

        return results

    def generate_report(self, results: Dict[str, Any]):
        """Generate a detailed HTML report."""
        report_path = Path(f"ingestion_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Data Ingestion Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                h1 {{ color: #2c3e50; }}
                h2 {{ color: #34495e; }}
                .success {{ color: #27ae60; }}
                .warning {{ color: #f39c12; }}
                .error {{ color: #e74c3c; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
                .stats {{ background-color: #ecf0f1; padding: 10px; margin: 10px 0; }}
            </style>
        </head>
        <body>
            <h1>🧠 Brain Researcher Data Ingestion Report</h1>
            <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

            <div class="stats">
                <h2>Summary</h2>
                <p>Total Entities: {results.get('statistics', {}).get('total_entities', 0):,}</p>
                <p>Total Relationships: {results.get('statistics', {}).get('total_relationships', 0):,}</p>
                <p>Duration: {results.get('statistics', {}).get('duration', 'N/A')}</p>
            </div>

            <h2>Sources Loaded</h2>
            <table>
                <tr><th>Source</th><th>Status</th><th>Details</th></tr>
        """

        payload = results.get("results", {})
        if not isinstance(payload, dict):
            payload = {}

        for source, entry in sorted(payload.items()):
            if not isinstance(entry, dict):
                details = json.dumps(entry, indent=2, default=str)
                html_content += f"""
                <tr>
                    <td>{source}</td>
                    <td class="warning">⚠️ Non-dict payload</td>
                    <td><pre>{details}</pre></td>
                </tr>
                """
                continue

            mode = entry.get("mode", "unknown")
            registered = entry.get("registered")
            result_block = entry.get("result")
            entry_error = entry.get("error")
            block_error = result_block.get("error") if isinstance(result_block, dict) else None

            if registered is False:
                status_label = "❌ Registration failed"
                status_class = "error"
            elif entry_error or block_error:
                status_label = "❌ Error"
                status_class = "error"
            elif mode == "on_demand":
                if registered is True:
                    status_label = "✅ Registered"
                    status_class = "success"
                else:
                    status_label = "⚠️ Configured"
                    status_class = "warning"
            else:
                status_label = "✅ Success"
                status_class = "success"

            details_payload = result_block if isinstance(result_block, dict) else entry
            details = json.dumps(details_payload, indent=2, default=str) if details_payload else "N/A"
            prefix = f"mode: {mode}"
            if entry.get("warning"):
                prefix += f" | warning: {entry['warning']}"
            details = f"{prefix}\n{details}"

            html_content += f"""
                <tr>
                    <td>{source}</td>
                    <td class="{status_class}">{status_label}</td>
                    <td><pre>{details}</pre></td>
                </tr>
            """

        html_content += """
            </table>
        </body>
        </html>
        """

        report_path.write_text(html_content)
        logger.info(f"  📄 Report generated: {report_path}")
        return report_path


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Launch comprehensive data ingestion for Brain Researcher"
    )
    parser.add_argument(
        "--config",
        default="configs/br-kg/data_config.json",
        help="Path to configuration file"
    )
    all_sources = sorted(MasterDataLoader.SOURCE_DEFAULT_MODES.keys())

    parser.add_argument(
        "--sources",
        nargs="+",
        choices=all_sources,
        help="Specific sources to load"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run quick test with limited data"
    )
    parser.add_argument(
        "--docker",
        action="store_true",
        help="Start Docker services before ingestion"
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate HTML report after ingestion"
    )

    args = parser.parse_args()

    # Create launcher
    launcher = DataIngestionLauncher(
        config_path=args.config,
        docker=args.docker
    )

    # Check environment
    if not launcher.check_environment():
        logger.error("Environment check failed. Please fix the issues above.")
        sys.exit(1)

    # Start Docker services if requested
    if args.docker:
        if not launcher.start_docker_services():
            logger.error("Failed to start Docker services")
            sys.exit(1)

    # Run ingestion
    try:
        if args.quick:
            results = launcher.quick_test()
        else:
            results = launcher.run_ingestion(sources=args.sources)

        # Generate report if requested
        if args.report:
            launcher.generate_report(results)

        logger.info("✅ Data ingestion completed successfully!")

    except KeyboardInterrupt:
        logger.warning("Ingestion interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
