"""
Virtual Brain (VB) simulation service package.

The package exposes a lightweight API surface for:
* deriving simulation priors from BR-KG evidence
* running Wilson–Cowan style regional simulations
* persisting Simulation spine metadata back into the graph
"""

from __future__ import annotations

from .api import create_app

__all__ = ["create_app"]
