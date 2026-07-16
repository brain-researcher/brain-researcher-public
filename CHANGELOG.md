# Changelog

All notable changes to Brain Researcher are documented in this file. The
project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-07-16

### Added

- Clean-clone CI for the supported Python 3.11 package, contracts,
  reproducibility packs, documentation, Web UI, services, and static
  deployment contracts.
- Manifest-backed public reproducibility packs with explicit provenance,
  environment, checksum, and scientific-comparison boundaries.
- A machine-readable software release manifest and a clean-clone release gate.

### Changed

- Made the repository entrypoints goal-based and classified public surfaces as
  stable, supported local, experimental, deployment-specific, or historical.
- Unified the supported Python package version, Helm chart version, preview
  image tag, and expected Git tag for the v0.2.0 release.
- Clarified that static artifact integrity, public rerunnability, governed
  reruns, and full scientific reproduction are distinct claims.

### Fixed

- Removed ambiguous working-directory assumptions and stale commands from the
  active setup and reproducibility documentation.
- Made public configuration and reproducibility checks fail closed on missing,
  malformed, or indeterminate evidence.
- Bound runtime version references to the tracked MCP contract epoch for both
  source-checkout and installed-package execution.

## [0.1.0] - 2026-05-28

- Historical Python package-version baseline and public service-stack snapshot.
  No remote `v0.1.0` semantic release tag was published for this baseline.

[0.2.0]: https://github.com/brain-researcher/brain-researcher-public/releases/tag/v0.2.0
[0.1.0]: https://github.com/brain-researcher/brain-researcher-public/commit/9e86e308c3adfb5e13bc513f9ac69307cd1cd5a4
