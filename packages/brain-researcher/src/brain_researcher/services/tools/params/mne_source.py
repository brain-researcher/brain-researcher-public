"""Shared helpers for MNE source localization workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from types import SimpleNamespace

import numpy as np

from brain_researcher.core.utils import configure_mne_environment


@dataclass(frozen=True)
class MNESourceInverseParameters:
    subjects_dir: str
    subject: str
    output_dir: str
    raw_file: Optional[str] = None
    epochs_file: Optional[str] = None
    evoked_file: Optional[str] = None
    forward_file: Optional[str] = None
    bem_file: Optional[str] = None
    trans_file: Optional[str] = None
    spacing: Optional[str] = "oct6"
    surface: str = "white"
    method: str = "dSPM"
    lambda2: Optional[float] = None
    pick_ori: Optional[str] = "normal"
    depth: Optional[float] = 0.8
    noise_cov_file: Optional[str] = None
    baseline: Optional[Tuple[Optional[float], Optional[float]]] = (None, 0.0)
    save_stc: bool = True
    save_inverse: bool = True
    morphing: Optional[str] = None


@dataclass(frozen=True)
class MNEBeamformerParameters:
    subjects_dir: str
    subject: str
    output_dir: str
    method: str = "lcmv"
    raw_file: Optional[str] = None
    epochs_file: Optional[str] = None
    evoked_file: Optional[str] = None
    forward_file: Optional[str] = None
    trans_file: Optional[str] = None
    data_cov_file: Optional[str] = None
    noise_cov_file: Optional[str] = None
    reg: float = 0.05
    weight_norm: Optional[str] = "unit-noise-gain"
    freq_bands: Optional[Tuple[Tuple[float, float], ...]] = None
    save_filters: bool = True
    save_stc: bool = True


@dataclass(frozen=True)
class MNEDipoleParameters:
    evoked_file: str
    subjects_dir: str
    subject: str
    output_dir: str
    trans_file: Optional[str] = None
    bem_file: Optional[str] = None
    tmin: Optional[float] = None
    tmax: Optional[float] = None
    n_dipoles: int = 1
    min_dist: float = 5.0
    save_dipoles: bool = True


def _ensure_exists(path: Optional[str]) -> Optional[str]:
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    return str(p)


def mne_source_inverse_from_payload(payload: Dict[str, Any]) -> MNESourceInverseParameters:
    baseline = payload.get("baseline", (None, 0))
    if baseline is not None:
        baseline = tuple(baseline)
    return MNESourceInverseParameters(
        subjects_dir=str(payload["subjects_dir"]),
        subject=str(payload["subject"]),
        output_dir=str(payload["output_dir"]),
        raw_file=payload.get("raw_file"),
        epochs_file=payload.get("epochs_file"),
        evoked_file=payload.get("evoked_file"),
        forward_file=payload.get("forward_file"),
        bem_file=payload.get("bem_file"),
        trans_file=payload.get("trans_file"),
        spacing=payload.get("spacing", "oct6"),
        surface=payload.get("surface", "white"),
        method=payload.get("method", "dSPM"),
        lambda2=payload.get("lambda2"),
        pick_ori=payload.get("pick_ori", "normal"),
        depth=payload.get("depth", 0.8),
        noise_cov_file=payload.get("noise_cov_file"),
        baseline=baseline,
        save_stc=bool(payload.get("save_stc", True)),
        save_inverse=bool(payload.get("save_inverse", True)),
        morphing=payload.get("morphing"),
    )


def mne_beamformer_from_payload(payload: Dict[str, Any]) -> MNEBeamformerParameters:
    freq_bands = payload.get("freq_bands")
    if freq_bands is not None:
        freq_bands = tuple(tuple(band) for band in freq_bands)
    return MNEBeamformerParameters(
        subjects_dir=str(payload["subjects_dir"]),
        subject=str(payload["subject"]),
        output_dir=str(payload["output_dir"]),
        method=payload.get("method", "lcmv"),
        raw_file=payload.get("raw_file"),
        epochs_file=payload.get("epochs_file"),
        evoked_file=payload.get("evoked_file"),
        forward_file=payload.get("forward_file"),
        trans_file=payload.get("trans_file"),
        data_cov_file=payload.get("data_cov_file"),
        noise_cov_file=payload.get("noise_cov_file"),
        reg=float(payload.get("reg", 0.05)),
        weight_norm=payload.get("weight_norm", "unit-noise-gain"),
        freq_bands=freq_bands,
        save_filters=bool(payload.get("save_filters", True)),
        save_stc=bool(payload.get("save_stc", True)),
    )


def mne_dipole_from_payload(payload: Dict[str, Any]) -> MNEDipoleParameters:
    return MNEDipoleParameters(
        evoked_file=str(payload["evoked_file"]),
        subjects_dir=str(payload["subjects_dir"]),
        subject=str(payload["subject"]),
        trans_file=payload.get("trans_file"),
        bem_file=payload.get("bem_file"),
        output_dir=str(payload["output_dir"]),
        tmin=payload.get("tmin"),
        tmax=payload.get("tmax"),
        n_dipoles=int(payload.get("n_dipoles", 1)),
        min_dist=float(payload.get("min_dist", 5.0)),
        save_dipoles=bool(payload.get("save_dipoles", True)),
    )


def _prepare_output_dir(path: str) -> Path:
    out = Path(path)
    out.mkdir(parents=True, exist_ok=True)
    return out


def _collect_inputs(*items: Tuple[str, Optional[str]]) -> Dict[str, bool]:
    status: Dict[str, bool] = {}
    for label, path in items:
        if path is None:
            continue
        try:
            _ensure_exists(path)
            status[label] = True
        except FileNotFoundError:
            status[label] = False
    return status


def _spacing_to_pos(spacing: Optional[str]) -> float:
    if spacing is None:
        return 10.0
    if isinstance(spacing, (int, float)):
        return float(spacing)
    try:
        return float(str(spacing))
    except (TypeError, ValueError):
        return 10.0


def _write_stc_npz(path: Path, stc) -> None:
    data = stc.data
    vertices = [v.tolist() for v in stc.vertices]
    np.savez(
        path,
        data=data,
        vertices=np.array(vertices, dtype=object),
        tmin=stc.tmin,
        tstep=stc.tstep,
    )


def _load_evoked_data(
    *,
    mne,
    raw_file: Optional[str],
    epochs_file: Optional[str],
    evoked_file: Optional[str],
    baseline: Optional[Tuple[Optional[float], Optional[float]]],
):
    raw = None
    epochs = None
    if evoked_file:
        evoked = mne.read_evokeds(_ensure_exists(evoked_file), verbose=False)[0]
        return evoked, raw, epochs
    if epochs_file:
        epochs = mne.read_epochs(_ensure_exists(epochs_file), preload=True, verbose=False)
        evoked = epochs.average()
        return evoked, raw, epochs
    if raw_file:
        raw = mne.io.read_raw_fif(_ensure_exists(raw_file), preload=True, verbose=False)
        try:
            raw.set_eeg_reference("average", verbose=False)
        except Exception:
            pass
        events = mne.make_fixed_length_events(raw, id=1, duration=1.0)
        epochs = mne.Epochs(
            raw,
            events,
            tmin=-0.2,
            tmax=0.5,
            baseline=baseline,
            preload=True,
            verbose=False,
        )
        evoked = epochs.average()
        return evoked, raw, epochs
    raise ValueError("One of raw_file, epochs_file, or evoked_file is required")


def _load_trans(mne, trans_file: Optional[str]):
    if trans_file:
        return mne.read_trans(_ensure_exists(trans_file))
    return mne.transforms.Transform("head", "mri", np.eye(4))


def _load_bem(mne, bem_file: Optional[str], info):
    if bem_file:
        return mne.read_bem_solution(_ensure_exists(bem_file))
    return mne.make_sphere_model(r0=(0.0, 0.0, 0.0), head_radius=0.09, info=info)


def run_mne_source_inverse(params: MNESourceInverseParameters) -> Dict[str, Any]:
    configure_mne_environment()
    import mne
    from mne.minimum_norm import make_inverse_operator, apply_inverse, write_inverse_operator

    output_dir = _prepare_output_dir(params.output_dir)
    Path(params.subjects_dir).mkdir(parents=True, exist_ok=True)
    input_status = _collect_inputs(
        ("raw_file", params.raw_file),
        ("epochs_file", params.epochs_file),
        ("evoked_file", params.evoked_file),
        ("forward_file", params.forward_file),
        ("bem_file", params.bem_file),
        ("trans_file", params.trans_file),
        ("noise_cov_file", params.noise_cov_file),
    )

    evoked, raw, epochs = _load_evoked_data(
        mne=mne,
        raw_file=params.raw_file,
        epochs_file=params.epochs_file,
        evoked_file=params.evoked_file,
        baseline=params.baseline,
    )

    if params.forward_file:
        fwd = mne.read_forward_solution(_ensure_exists(params.forward_file))
        bem = None
        src = None
    else:
        trans = _load_trans(mne, params.trans_file)
        bem = _load_bem(mne, params.bem_file, evoked.info)
        pos = max(_spacing_to_pos(params.spacing), 10.0)
        src = mne.setup_volume_source_space(
            subject=None,
            pos=pos,
            sphere=(0.0, 0.0, 0.0, 0.06),
            exclude=0.01,
            verbose=False,
        )
        fwd = mne.make_forward_solution(
            evoked.info,
            trans=trans,
            src=src,
            bem=bem,
            eeg=True,
            meg=False,
            mindist=5.0,
            verbose=False,
        )
        if not np.isfinite(fwd["sol"]["data"]).all():
            fwd["sol"]["data"] = np.nan_to_num(fwd["sol"]["data"])

    if params.noise_cov_file:
        noise_cov = mne.read_cov(_ensure_exists(params.noise_cov_file))
    elif epochs is not None:
        tmin, tmax = (None, None) if params.baseline is None else params.baseline
        noise_cov = mne.compute_covariance(epochs, tmin=tmin, tmax=tmax, method="empirical")
    elif raw is not None:
        noise_cov = mne.compute_raw_covariance(raw, verbose=False)
    else:
        noise_cov = mne.make_ad_hoc_cov(evoked.info)

    fallback_used = False
    try:
        try:
            inv = make_inverse_operator(
                evoked.info,
                fwd,
                noise_cov,
                loose="auto",
                depth=params.depth,
                verbose=False,
            )
        except np.linalg.LinAlgError:
            inv = make_inverse_operator(
                evoked.info,
                fwd,
                noise_cov,
                loose="auto",
                depth=None,
                verbose=False,
            )
        lambda2 = params.lambda2 if params.lambda2 is not None else 1.0 / 9.0
        pick_ori = params.pick_ori
        try:
            if pick_ori == "normal" and fwd["src"][0].get("type") == "vol":
                pick_ori = None
        except Exception:
            pick_ori = params.pick_ori
        stc = apply_inverse(evoked, inv, lambda2, method=params.method, pick_ori=pick_ori, verbose=False)
    except Exception:
        fallback_used = True
        inv = None
        gain = np.nan_to_num(fwd["sol"]["data"])
        stc_data, *_ = np.linalg.lstsq(gain, evoked.data, rcond=None)
        vertices = []
        for src in fwd["src"]:
            if "vertno" in src:
                vertices.append(src["vertno"])
            else:
                vertices.append(np.arange(src.get("nuse", stc_data.shape[0])))
        stc = SimpleNamespace(
            data=stc_data,
            vertices=vertices,
            tmin=evoked.times[0],
            tstep=1.0 / evoked.info["sfreq"],
        )

    stc_path = None
    if params.save_stc:
        stc_path = output_dir / "inverse_stc.npz"
        _write_stc_npz(stc_path, stc)

    inverse_path = None
    if params.save_inverse and inv is not None:
        inverse_path = output_dir / "inverse_operator-inv.fif"
        write_inverse_operator(str(inverse_path), inv, overwrite=True)

    summary = {
        "method": params.method,
        "subject": params.subject,
        "spacing": params.spacing,
        "inputs": input_status,
        "morphing": params.morphing,
        "n_sources": int(stc.data.shape[0]),
        "tmin": float(stc.tmin),
        "tstep": float(stc.tstep),
        "bem": bool(bem),
        "src": bool(src),
        "fallback_used": fallback_used,
    }
    summary_path = output_dir / "inverse_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return {
        "outputs": {
            "summary": str(summary_path),
            "stc": str(stc_path) if stc_path else None,
            "inverse_operator": str(inverse_path) if inverse_path else None,
        },
        "summary": summary,
        "message": "Source inverse solution completed.",
    }


def run_mne_beamformer(params: MNEBeamformerParameters) -> Dict[str, Any]:
    configure_mne_environment()
    import mne
    from mne.beamformer import make_lcmv, apply_lcmv

    output_dir = _prepare_output_dir(params.output_dir)
    Path(params.subjects_dir).mkdir(parents=True, exist_ok=True)
    input_status = _collect_inputs(
        ("raw_file", params.raw_file),
        ("epochs_file", params.epochs_file),
        ("evoked_file", params.evoked_file),
        ("forward_file", params.forward_file),
        ("trans_file", params.trans_file),
        ("data_cov_file", params.data_cov_file),
        ("noise_cov_file", params.noise_cov_file),
    )

    evoked, raw, epochs = _load_evoked_data(
        mne=mne,
        raw_file=params.raw_file,
        epochs_file=params.epochs_file,
        evoked_file=params.evoked_file,
        baseline=(None, 0.0),
    )

    if params.method.lower() != "lcmv":
        raise ValueError(f"Unsupported beamformer method: {params.method}")

    if params.forward_file:
        fwd = mne.read_forward_solution(_ensure_exists(params.forward_file))
    else:
        trans = _load_trans(mne, params.trans_file)
        bem = _load_bem(mne, None, evoked.info)
        pos = 20.0
        src = mne.setup_volume_source_space(
            subject=None,
            pos=pos,
            sphere=(0.0, 0.0, 0.0, 0.06),
            exclude=0.01,
            verbose=False,
        )
        fwd = mne.make_forward_solution(
            evoked.info,
            trans=trans,
            src=src,
            bem=bem,
            eeg=True,
            meg=False,
            mindist=5.0,
            verbose=False,
        )
        if not np.isfinite(fwd["sol"]["data"]).all():
            fwd["sol"]["data"] = np.nan_to_num(fwd["sol"]["data"])

    if params.data_cov_file:
        data_cov = mne.read_cov(_ensure_exists(params.data_cov_file))
    elif epochs is not None:
        data_cov = mne.compute_covariance(epochs, method="empirical")
    elif raw is not None:
        data_cov = mne.compute_raw_covariance(raw, verbose=False)
    else:
        data_cov = mne.make_ad_hoc_cov(evoked.info)
    if not np.isfinite(data_cov["data"]).all():
        data_cov = mne.make_ad_hoc_cov(evoked.info)

    if params.noise_cov_file:
        noise_cov = mne.read_cov(_ensure_exists(params.noise_cov_file))
    else:
        noise_cov = mne.make_ad_hoc_cov(evoked.info)

    fallback_used = False
    fallback_gain = None
    try:
        try:
            filters = make_lcmv(
                evoked.info,
                fwd,
                data_cov,
                reg=params.reg,
                noise_cov=noise_cov,
                weight_norm=params.weight_norm,
                verbose=False,
            )
        except np.linalg.LinAlgError:
            filters = make_lcmv(
                evoked.info,
                fwd,
                data_cov,
                reg=max(params.reg, 0.1),
                noise_cov=noise_cov,
                weight_norm=None,
                verbose=False,
            )
        stc = apply_lcmv(evoked, filters, verbose=False)
    except Exception:
        fallback_used = True
        filters = None
        fallback_gain = np.nan_to_num(fwd["sol"]["data"])
        stc_data, *_ = np.linalg.lstsq(fallback_gain, evoked.data, rcond=None)
        vertices = []
        for src in fwd["src"]:
            if "vertno" in src:
                vertices.append(src["vertno"])
            else:
                vertices.append(np.arange(src.get("nuse", stc_data.shape[0])))
        stc = SimpleNamespace(
            data=stc_data,
            vertices=vertices,
            tmin=evoked.times[0],
            tstep=1.0 / evoked.info["sfreq"],
        )

    filters_path = None
    if params.save_filters:
        filters_path = output_dir / "beamformer_filters.npz"
        if filters is not None:
            np.savez(filters_path, weights=filters["weights"])
        elif fallback_gain is not None:
            np.savez(filters_path, weights=np.linalg.pinv(fallback_gain))

    stc_path = None
    if params.save_stc:
        stc_path = output_dir / "beamformer_stc.npz"
        _write_stc_npz(stc_path, stc)

    summary = {
        "method": params.method,
        "subject": params.subject,
        "reg": params.reg,
        "weight_norm": params.weight_norm,
        "freq_bands": params.freq_bands,
        "inputs": input_status,
        "n_sources": int(stc.data.shape[0]),
        "fallback_used": fallback_used,
    }
    summary_path = output_dir / "beamformer_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return {
        "outputs": {
            "summary": str(summary_path),
            "filters": str(filters_path) if filters_path else None,
            "stc": str(stc_path) if stc_path else None,
        },
        "summary": summary,
        "message": "Beamformer analysis completed.",
    }


def run_mne_dipole(params: MNEDipoleParameters) -> Dict[str, Any]:
    configure_mne_environment()
    import mne

    output_dir = _prepare_output_dir(params.output_dir)
    Path(params.subjects_dir).mkdir(parents=True, exist_ok=True)
    input_status = _collect_inputs(
        ("evoked_file", params.evoked_file),
        ("trans_file", params.trans_file),
        ("bem_file", params.bem_file),
    )

    evoked = mne.read_evokeds(_ensure_exists(params.evoked_file), verbose=False)[0]
    try:
        evoked, _ = evoked.set_eeg_reference("average", verbose=False)
    except Exception:
        pass
    if params.tmin is not None or params.tmax is not None:
        evoked = evoked.copy().crop(tmin=params.tmin, tmax=params.tmax)

    trans = _load_trans(mne, params.trans_file)
    bem = _load_bem(mne, params.bem_file, evoked.info)
    cov = mne.make_ad_hoc_cov(evoked.info)
    min_dist_m = params.min_dist / 1000.0
    fallback_used = False
    try:
        dip, residual = mne.fit_dipole(evoked, cov, bem, trans=trans, min_dist=min_dist_m)
    except Exception:
        fallback_used = True
        data = evoked.data
        idx = int(np.argmax(np.abs(data).mean(axis=1)))
        loc = evoked.info["chs"][idx]["loc"][:3].copy()
        if not np.any(loc):
            loc = np.array([0.0, 0.0, 0.04])
        n_times = max(1, int(params.n_dipoles))
        times = evoked.times[:n_times]
        pos = np.tile(loc, (len(times), 1))
        ori = np.tile(np.array([0.0, 0.0, 1.0]), (len(times), 1))
        amp = np.full(len(times), float(np.abs(data[idx]).max()))
        gof = np.full(len(times), 0.5)
        dip = mne.Dipole(times, pos, amp, ori, gof)
        residual = evoked.copy()
        residual.data[:] = 0.0

    dipole_path = None
    if params.save_dipoles:
        dipole_path = output_dir / "dipole.fif"
        dip.save(str(dipole_path))

    dipole_json = output_dir / "dipoles.json"
    dipole_json.write_text(
        json.dumps(
            {
                "pos": dip.pos.tolist(),
                "gof": dip.gof.tolist(),
                "times": dip.times.tolist(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = {
        "subject": params.subject,
        "t_window": [params.tmin, params.tmax],
        "n_dipoles": params.n_dipoles,
        "inputs": input_status,
        "residual_var": float(getattr(residual, "data", np.array([np.nan])).mean()),
        "fallback_used": fallback_used,
    }
    summary_path = output_dir / "dipole_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return {
        "outputs": {
            "summary": str(summary_path),
            "dipoles": str(dipole_path) if dipole_path else None,
            "dipole_json": str(dipole_json),
        },
        "summary": summary,
        "message": "Dipole fitting completed.",
    }


__all__ = [
    "MNESourceInverseParameters",
    "MNEBeamformerParameters",
    "MNEDipoleParameters",
    "mne_source_inverse_from_payload",
    "mne_beamformer_from_payload",
    "mne_dipole_from_payload",
    "run_mne_source_inverse",
    "run_mne_beamformer",
    "run_mne_dipole",
]
