"""Python test shim for Niivue helpers used by unit tests.

The real Niivue integration lives in the Web UI (TypeScript). The Python unit
tests exercise a small runtime-oriented surface area with a mocked Niivue
instance (frame control detection, screenshot export, and state serialization).
This module provides that minimal API for the Python test suite.
"""

from __future__ import annotations

from typing import Any


class NiivueManager:
    def __init__(self, nv: Any):
        self._nv = nv
        self._animating = False

    def detectFrameControlMethod(self) -> str | None:
        if callable(getattr(self._nv, "setFrame4D", None)):
            return "setFrame4D"
        if callable(getattr(self._nv, "setFrame", None)):
            return "setFrame"
        return None

    def setFrame(self, frame: int) -> None:
        """Set the current frame using Niivue APIs when available.

        The unit tests use mocked Niivue objects; if the API surface is missing
        we update the first volume's `frame4D` field as a best-effort fallback.
        """

        method = self.detectFrameControlMethod()
        if method == "setFrame4D":
            self._nv.setFrame4D(frame)
            return
        if method == "setFrame":
            self._nv.setFrame(frame)
            return

        vols = getattr(self._nv, "volumes", []) or []
        if vols:
            setattr(vols[0], "frame4D", int(frame))
            return
        raise AttributeError("Niivue instance has no frame control method")

    def getCurrentFrame(self) -> int:
        vols = getattr(self._nv, "volumes", []) or []
        if not vols:
            return 0
        return int(getattr(vols[0], "frame4D", 0) or 0)

    def getMaxFrames(self) -> int:
        vols = getattr(self._nv, "volumes", []) or []
        if not vols:
            return 0
        return int(getattr(vols[0], "nFrame4D", 1) or 1)

    def isAnimating(self) -> bool:
        return self._animating

    def startAnimation(self) -> None:
        self._animating = True

    def stopAnimation(self) -> None:
        self._animating = False

    def exportScreenshot(self, fmt: str = "png") -> str:
        fmt_l = (fmt or "png").lower()
        if fmt_l in {"jpeg", "jpg"}:
            return "data:image/jpeg;base64,test"
        return "data:image/png;base64,test"

    def getVisualizationState(self) -> dict[str, Any]:
        vols = getattr(self._nv, "volumes", []) or []
        volumes: list[dict[str, Any]] = []
        for v in vols:
            volumes.append(
                {
                    "url": getattr(v, "url", None),
                    "opacity": getattr(v, "opacity", None),
                    "colormap": getattr(v, "colormap", None),
                    "cal_min": getattr(v, "cal_min", None),
                    "cal_max": getattr(v, "cal_max", None),
                    "frame4D": getattr(v, "frame4D", None),
                }
            )

        scene = getattr(self._nv, "scene", None)
        clip_plane = getattr(scene, "clipPlane", None) if scene is not None else None
        return {"volumes": volumes, "clipPlane": clip_plane}

    def setVisualizationState(self, state: dict[str, Any]) -> None:
        if not state:
            return
        clip_plane = state.get("clipPlane")
        if clip_plane is not None and hasattr(self._nv, "setClipPlane"):
            self._nv.setClipPlane(clip_plane)


def createNiivueManager(nv: Any) -> NiivueManager:
    return NiivueManager(nv)

