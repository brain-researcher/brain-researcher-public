"""Stable public namespace for the Brain Researcher shared utilities.

OSS-facing re-export layer. Internal callers keep using the original paths
(`brain_researcher.services.shared.*`, `brain_researcher.core.*`,
`brain_researcher.cli.utils.*`); external consumers (skills, adapters,
and downstream `brain-researcher-agent-kit` code) should depend only on
`brain_researcher.br.*`.

Submodules:
- br.retry — RetryConfig, TimeoutConfig, load_retry_config, load_timeout_config
- br.provenance — write_provenance
- br.artifact — save_artifact_manifest, compute_file_sha256, fill_artifact_checksums,
                ArtifactContractSpec, artifact_contract_for_profile,
                required_artifacts_for_profile, optional_artifacts_for_profile,
                infer_artifact_profile
- br.http — get_orchestrator_url, format_http_error, api_get_sync, api_post_sync
- br.redaction — scrub_text, scrub_data
"""

from brain_researcher.br import artifact, http, provenance, redaction, retry

__all__ = ["artifact", "http", "provenance", "redaction", "retry"]
