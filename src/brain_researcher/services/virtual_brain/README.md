# Virtual Brain (VB) Platform

The VB service turns BR-KG task → region evidence into reproducible
simulation priors and lightweight `Simulation` spine nodes.  It currently
offers:

* Wilson–Cowan regional simulations with Balloon/Windkessel down-stream
  projections.
* Prior generation (`/vb/suggest_params`) by reading `ACTIVATES` edges.
* Forward simulation (`/vb/simulate`) with optional persistence and artefact
  exports.
* Coarse parameter fitting (`/vb/fit`) powered by a small random search loop.
* Reporting and sensitivity analysis (`/vb/report`, `/vb/whatif`).

The service expects an `SCMatrix` node whose `weights_uri` and optional
`delays_uri` resolve to `.npy`/`.npz`/`.csv` files, plus an optional
`TargetFC` node for quick QC metrics.  Artefacts are written under
`data/virtual_brain/cache` by default and referenced via `Simulation` nodes.

See `tests/unit/virtual_brain/` for usage examples and the API contract.
