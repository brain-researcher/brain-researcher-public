"""FastAPI wiring for the Virtual Brain service."""

from __future__ import annotations

import logging
from typing import Mapping, Optional

from fastapi import Depends, FastAPI, HTTPException, status

from brain_researcher.core.ingestion.graph_factory import (
    GraphDatabaseProtocol,
    GraphFactory,
)
from brain_researcher.services.br_kg.graph.graph_database import (
    BRKGGraphDB,  # type: ignore
)
from brain_researcher.services.br_kg.graph.graph_factory import create_graph_client

from .config import VirtualBrainConfig
from .models import (
    FitRequest,
    FitResponse,
    SimulateRequest,
    SimulateResponse,
    SimulationReport,
    SuggestParamsRequest,
    SuggestParamsResponse,
    WhatIfRequest,
    WhatIfResponse,
)
from .simulator import VirtualBrainSimulator

logger = logging.getLogger(__name__)


def _default_db_factory() -> GraphDatabaseProtocol:
    try:
        return create_graph_client()
    except RuntimeError:
        logger.info("Falling back to in-memory BRKGGraphDB for VB service")
        return BRKGGraphDB(":memory:")


def create_app(
    config_mapping: Optional[Mapping[str, object]] = None,
    *,
    db: Optional[GraphDatabaseProtocol] = None,
    db_factory: Optional[GraphFactory] = None,
) -> FastAPI:
    """Initialise the FastAPI app bound to a VirtualBrainSimulator instance."""

    vb_config = (
        VirtualBrainConfig.from_mapping(config_mapping)
        if config_mapping is not None
        else VirtualBrainConfig.from_env()
    )
    graph_db = db if db is not None else (db_factory or _default_db_factory)()

    simulator = VirtualBrainSimulator(graph_db, vb_config)

    app = FastAPI(
        title="Virtual Brain Platform",
        version="0.1.0",
        description="Assistive search + reproducible simulation service backed by BR-KG.",
    )

    @app.on_event("shutdown")
    async def _shutdown_simulator() -> None:
        simulator.close()

    def get_simulator() -> VirtualBrainSimulator:
        return simulator

    @app.post(
        "/vb/suggest_params",
        response_model=SuggestParamsResponse,
        summary="Derive simulation priors from BR-KG evidence.",
    )
    async def suggest_params(
        request: SuggestParamsRequest,
        sim: VirtualBrainSimulator = Depends(get_simulator),
    ) -> SuggestParamsResponse:
        try:
            return sim.suggest_params(request)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc

    @app.post(
        "/vb/simulate",
        response_model=SimulateResponse,
        summary="Run a Wilson–Cowan simulation given priors and parameters.",
    )
    async def simulate(
        request: SimulateRequest, sim: VirtualBrainSimulator = Depends(get_simulator)
    ) -> SimulateResponse:
        try:
            return sim.simulate(request)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

    @app.post(
        "/vb/fit",
        response_model=FitResponse,
        summary="Optimise parameters to match empirical targets.",
    )
    async def fit(
        request: FitRequest, sim: VirtualBrainSimulator = Depends(get_simulator)
    ) -> FitResponse:
        try:
            return sim.fit(request)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

    @app.get(
        "/vb/report/{simulation_id}",
        response_model=SimulationReport,
        summary="Fetch persisted simulation metadata and artefact pointers.",
    )
    async def report(
        simulation_id: str, sim: VirtualBrainSimulator = Depends(get_simulator)
    ) -> SimulationReport:
        return sim.report(simulation_id)

    @app.post(
        "/vb/whatif",
        response_model=WhatIfResponse,
        summary="Perform sensitivity analysis around a persisted simulation.",
    )
    async def whatif(
        request: WhatIfRequest, sim: VirtualBrainSimulator = Depends(get_simulator)
    ) -> WhatIfResponse:
        try:
            return sim.whatif(request)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
            ) from exc

    return app
