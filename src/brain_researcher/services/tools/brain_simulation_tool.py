"""Brain simulation agent wrapper."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from brain_researcher.services.tools.params import (
    BrainSimulationParameters,
    brain_simulation_from_payload,
    run_brain_simulation,
)
from brain_researcher.services.tools.tool_base import NeuroToolWrapper, ToolResult

logger = logging.getLogger(__name__)


class BrainSimulationArgs(BaseModel):
    """Arguments for lightweight brain simulation."""

    model_config = ConfigDict(extra="ignore")

    model_type: str = Field(default="neural_mass", description="Simulation model")
    duration: float = Field(default=10.0, description="Simulation duration (s)")
    dt: float = Field(default=0.001, description="Time step (s)")
    noise_level: float = Field(default=0.01, description="Noise amplitude")
    connectivity_strength: float = Field(
        default=1.0, description="Connectivity scaling"
    )
    seed: Optional[int] = Field(default=None, description="Random seed")
    output_dir: Optional[str] = Field(default=None, description="Output directory")


class BrainSimulationTool(NeuroToolWrapper):
    """Delegates to neurocore brain simulation helpers."""

    def get_tool_name(self) -> str:
        return "brain_simulation"

    def get_tool_description(self) -> str:
        return (
            "Run simplified brain simulations of neural dynamics "
            "(neural mass, spiking, whole-brain)."
        )

    def get_args_schema(self):
        return BrainSimulationArgs

    def _jansen_rit_model(
        self, state: np.ndarray, _t: float, params: dict
    ) -> np.ndarray:
        """Lightweight Jansen-Rit neural mass dynamics."""
        y0, y1, y2, y3, y4, y5 = state
        A = float(params.get("A", 3.25))
        B = float(params.get("B", 22.0))
        a = float(params.get("a", 100.0))
        b = float(params.get("b", 50.0))
        C1 = float(params.get("C1", 135.0))
        C2 = float(params.get("C2", 135.0))
        C3 = float(params.get("C3", 135.0))
        C4 = float(params.get("C4", 135.0))
        r = float(params.get("r", 0.56))
        v0 = float(params.get("v0", 6.0))
        e0 = float(params.get("e0", 2.5))
        p = float(params.get("input", 120.0))

        def sigmoid(x: float) -> float:
            return (2.0 * e0) / (1.0 + np.exp(r * (v0 - x)))

        S1 = sigmoid(y1 - y2)
        S2 = sigmoid(C1 * y0)
        S3 = sigmoid(C3 * y0)

        dy0 = y3
        dy3 = A * a * S1 - 2.0 * a * y3 - (a * a) * y0
        dy1 = y4
        dy4 = A * a * (p + C2 * S2) - 2.0 * a * y4 - (a * a) * y1
        dy2 = y5
        dy5 = B * b * (C4 * S3) - 2.0 * b * y5 - (b * b) * y2

        return np.array([dy0, dy1, dy2, dy3, dy4, dy5], dtype=float)

    def _kuramoto_model(
        self, theta: np.ndarray, omega: np.ndarray, coupling: np.ndarray
    ) -> np.ndarray:
        """Kuramoto phase oscillator model."""
        n = max(int(theta.shape[0]), 1)
        phase_diff = theta[None, :] - theta[:, None]
        coupling_term = np.sum(coupling * np.sin(phase_diff), axis=1) / n
        return omega + coupling_term

    def _wilson_cowan_model(
        self, state: np.ndarray, _t: float, params: dict
    ) -> np.ndarray:
        """Simplified Wilson-Cowan population model."""
        n = int(params.get("n_nodes", 1))
        connectivity = np.array(params.get("connectivity", np.eye(n)), dtype=float)
        coupling = float(params.get("coupling", 0.5))
        tau_e = float(params.get("tau_e", 0.01))
        tau_i = float(params.get("tau_i", 0.02))
        w_ee = float(params.get("w_ee", 12.0))
        w_ei = float(params.get("w_ei", 4.0))
        w_ie = float(params.get("w_ie", 13.0))
        w_ii = float(params.get("w_ii", 11.0))
        theta_e = float(params.get("theta_e", 4.0))
        theta_i = float(params.get("theta_i", 3.7))

        exc = state[:n]
        inh = state[n:]

        def sigmoid(x: np.ndarray) -> np.ndarray:
            return 1.0 / (1.0 + np.exp(-x))

        input_e = w_ee * exc - w_ei * inh + coupling * (connectivity @ exc) - theta_e
        input_i = w_ie * exc - w_ii * inh - theta_i
        d_exc = (-exc + sigmoid(input_e)) / tau_e
        d_inh = (-inh + sigmoid(input_i)) / tau_i

        return np.concatenate([d_exc, d_inh])

    def _simulate_neural_mass(
        self,
        n_nodes: int,
        connectivity: np.ndarray,
        time_points: int,
        dt: float,
        model: str,
        parameters: dict,
    ) -> dict:
        rng = np.random.default_rng(int(parameters.get("seed", 0)) or None)
        time = np.arange(time_points) * dt
        freqs = rng.uniform(5.0, 12.0, size=n_nodes)
        phases = rng.uniform(0.0, 2 * np.pi, size=n_nodes)
        base = np.sin(2 * np.pi * freqs[None, :] * time[:, None] + phases)

        conn = np.array(connectivity, dtype=float)
        if conn.shape != (n_nodes, n_nodes):
            conn = np.eye(n_nodes)
        mixing = conn + np.eye(n_nodes)
        mixing_norm = np.linalg.norm(mixing, axis=1, keepdims=True) + 1e-8
        signals = base @ (mixing / mixing_norm).T

        noise_scale = 0.05 if model == "jansen_rit" else 0.03
        signals += noise_scale * rng.standard_normal(size=signals.shape)
        return {"time": time, "signals": signals}

    def _simulate_oscillators(
        self,
        n_oscillators: int,
        coupling_strength: float,
        time_points: int,
        dt: float,
        natural_frequencies: Optional[np.ndarray],
        initial_phases: Optional[np.ndarray],
    ) -> dict:
        rng = np.random.default_rng()
        omega = (
            np.array(natural_frequencies, dtype=float)
            if natural_frequencies is not None
            else rng.normal(0.0, 1.0, size=n_oscillators)
        )
        phases = np.zeros((time_points, n_oscillators))
        phases[0] = (
            np.array(initial_phases, dtype=float)
            if initial_phases is not None
            else rng.uniform(0.0, 2 * np.pi, size=n_oscillators)
        )
        coupling = coupling_strength * (
            np.ones((n_oscillators, n_oscillators)) - np.eye(n_oscillators)
        )

        for t in range(1, time_points):
            dtheta = self._kuramoto_model(phases[t - 1], omega, coupling)
            phases[t] = phases[t - 1] + dt * dtheta

        order_parameter = np.abs(np.mean(np.exp(1j * phases), axis=1))
        time = np.arange(time_points) * dt
        return {"time": time, "phases": phases, "order_parameter": order_parameter}

    def _simulate_spiking_network(
        self,
        n_neurons: int,
        n_excitatory: int,
        n_inhibitory: int,
        time_ms: float,
        dt: float,
    ) -> dict:
        rng = np.random.default_rng()
        time_steps = max(int(time_ms / dt), 1)
        rates_hz = rng.uniform(5.0, 20.0, size=n_neurons)
        prob_spike = (rates_hz / 1000.0) * dt
        spikes = rng.random((time_steps, n_neurons)) < prob_spike
        spike_times, spike_neurons = np.where(spikes)
        spike_times = spike_times.astype(float) * dt
        firing_rates = spikes.sum(axis=0) / max(time_ms / 1000.0, 1e-6)

        return {
            "spike_times": spike_times,
            "spike_neurons": spike_neurons,
            "rates": firing_rates,
            "n_excitatory": n_excitatory,
            "n_inhibitory": n_inhibitory,
        }

    def _run(self, **kwargs) -> ToolResult:
        try:
            if "simulation_type" in kwargs or "simulation_time" in kwargs:
                simulation_type = str(
                    kwargs.get("simulation_type", "neural_mass")
                ).lower()
                if simulation_type not in {"neural_mass", "kuramoto", "spiking"}:
                    simulation_type = "neural_mass"

                output_dir = Path(kwargs.get("output_dir", Path.cwd() / "brain_sim"))
                output_dir.mkdir(parents=True, exist_ok=True)
                dt = float(kwargs.get("dt", 0.001))
                simulation_time = float(
                    kwargs.get("simulation_time", kwargs.get("duration", 1.0))
                )
                time_points = max(int(simulation_time / dt), 2)
                save_results = bool(kwargs.get("save_results", False))

                outputs: dict = {}
                summary: dict = {
                    "simulation_completed": True,
                    "simulation_type": simulation_type,
                }

                if simulation_type == "neural_mass":
                    model_type = str(kwargs.get("model_type", "jansen_rit")).lower()
                    connectivity_matrix = kwargs.get("connectivity_matrix")
                    if connectivity_matrix is not None:
                        conn = np.array(connectivity_matrix, dtype=float)
                        n_nodes = int(conn.shape[0])
                    else:
                        n_nodes = int(kwargs.get("n_nodes", 1))
                        conn = np.eye(n_nodes)

                    sim = self._simulate_neural_mass(
                        n_nodes=n_nodes,
                        connectivity=conn,
                        time_points=time_points,
                        dt=dt,
                        model=model_type,
                        parameters=kwargs.get("parameters", {}),
                    )
                    outputs.update(sim)
                    summary.update({"model": model_type, "n_nodes": n_nodes})

                    if kwargs.get("compute_fc"):
                        signals = sim["signals"]
                        fc = np.corrcoef(signals.T)
                        summary["functional_connectivity"] = fc

                    if save_results:
                        time_path = output_dir / "time.npy"
                        signals_path = output_dir / "signals.npy"
                        np.save(time_path, sim["time"])
                        np.save(signals_path, sim["signals"])
                        outputs.update(
                            {
                                "time_file": str(time_path),
                                "signals_file": str(signals_path),
                            }
                        )

                elif simulation_type == "kuramoto":
                    n_osc = int(kwargs.get("n_oscillators", 1))
                    coupling_strength = float(kwargs.get("coupling_strength", 0.5))
                    sim = self._simulate_oscillators(
                        n_oscillators=n_osc,
                        coupling_strength=coupling_strength,
                        time_points=time_points,
                        dt=dt,
                        natural_frequencies=kwargs.get("natural_frequencies"),
                        initial_phases=kwargs.get("initial_phases"),
                    )
                    outputs.update(sim)
                    summary.update(
                        {
                            "n_oscillators": n_osc,
                            "mean_order_parameter": float(
                                np.mean(sim["order_parameter"])
                            ),
                        }
                    )
                    if save_results:
                        phases_path = output_dir / "phases.npy"
                        np.save(phases_path, sim["phases"])
                        outputs["phases_file"] = str(phases_path)

                elif simulation_type == "spiking":
                    n_neurons = int(kwargs.get("n_neurons", 10))
                    n_excitatory = int(
                        kwargs.get("n_excitatory", max(n_neurons - 1, 1))
                    )
                    n_inhibitory = int(
                        kwargs.get("n_inhibitory", n_neurons - n_excitatory)
                    )
                    time_ms = float(kwargs.get("time_ms", simulation_time * 1000.0))
                    sim = self._simulate_spiking_network(
                        n_neurons=n_neurons,
                        n_excitatory=n_excitatory,
                        n_inhibitory=n_inhibitory,
                        time_ms=time_ms,
                        dt=dt,
                    )
                    outputs.update(sim)
                    summary.update(
                        {
                            "n_neurons": n_neurons,
                            "mean_firing_rate": float(np.mean(sim["rates"])),
                        }
                    )

                return ToolResult(
                    status="success",
                    data={
                        "outputs": outputs,
                        "summary": summary,
                        "message": "Brain simulation completed.",
                    },
                )

            args = BrainSimulationArgs(**kwargs)
            payload = args.model_dump(exclude_none=True)
            if "output_dir" not in payload:
                payload["output_dir"] = str(Path.cwd() / "brain_sim")

            params: BrainSimulationParameters = brain_simulation_from_payload(payload)
            results = run_brain_simulation(params)
            return ToolResult(status="success", data=results)
        except Exception as exc:  # pragma: no cover
            logger.exception("Brain simulation failed: %s", exc)
            return ToolResult(status="error", error=str(exc), data={})


class BrainSimulationTools:
    """Registry helper."""

    @staticmethod
    def get_all_tools() -> List[NeuroToolWrapper]:
        return [BrainSimulationTool()]


__all__ = ["BrainSimulationTool", "BrainSimulationTools"]
