"""Replay-first real-time two-photon closed-loop tooling."""

from __future__ import annotations

import logging

from brain_researcher.services.tools.realtime_twophoton_runtime import (
    RealtimeTwoPhotonRunner,
)
from brain_researcher.services.tools.realtime_twophoton_schemas import (
    RealtimeTwoPhotonArgs,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class RealtimeTwoPhotonTool(NeuroToolWrapper):
    """Replay-first real-time two-photon processing and closed-loop control."""

    def __init__(self):
        super().__init__()
        self._dependency_state = self._detect_dependencies()

    def get_tool_name(self) -> str:
        return "realtime_twophoton"

    def get_tool_description(self) -> str:
        return (
            "Replay-first or raw-socket real-time two-photon processing with rigid "
            "motion correction, fixed-ROI trace extraction, coarse place-bin decoding, "
            "and optional UDP/WebSocket closed-loop control."
        )

    def get_args_schema(self):
        return RealtimeTwoPhotonArgs

    def _run(self, **kwargs) -> ToolResult:
        args = RealtimeTwoPhotonArgs(**kwargs)
        try:
            summary, outputs = RealtimeTwoPhotonRunner(args).run()
        except Exception as exc:
            logger.error("Real-time two-photon pipeline failed: %s", exc)
            return ToolResult(
                status="error",
                error=str(exc),
                metadata={"dependency_state": self._dependency_state},
            )

        return ToolResult(
            status="success",
            data={"summary": summary},
            metadata={
                "output_files": outputs,
                "dependency_state": self._dependency_state,
            },
        )

    @staticmethod
    def _detect_dependencies() -> dict[str, bool]:
        try:
            import cv2  # noqa: F401

            cv2_available = True
        except ImportError:
            cv2_available = False
        try:
            import sklearn  # noqa: F401

            sklearn_available = True
        except ImportError:
            sklearn_available = False
        try:
            import joblib  # noqa: F401

            joblib_available = True
        except ImportError:
            joblib_available = False
        try:
            import caiman  # noqa: F401

            caiman_available = True
        except ImportError:
            caiman_available = False
        try:
            import websockets.sync.client  # noqa: F401

            websockets_available = True
        except ImportError:
            websockets_available = False
        return {
            "cv2": cv2_available,
            "sklearn": sklearn_available,
            "joblib": joblib_available,
            "caiman": caiman_available,
            "websockets": websockets_available,
        }


class RealtimeTwoPhotonTools:
    """Collection of replay-first real-time two-photon tools."""

    @staticmethod
    def get_all_tools() -> list[NeuroToolWrapper]:
        return [RealtimeTwoPhotonTool()]
