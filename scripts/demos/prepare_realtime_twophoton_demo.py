#!/usr/bin/env python3
"""Prepare a synthetic demo bundle for realtime two-photon workflows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from brain_researcher.services.tools.realtime_twophoton_calibration import (
    build_coarse_place_calibration_bundle_from_replay,
)
from brain_researcher.services.tools.realtime_twophoton_runtime import (
    build_simulated_bundle,
    save_replay_bundle,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        default="outputs/out/realtime_twophoton_demo",
        help="Directory where demo replay/calibration/params files will be written.",
    )
    parser.add_argument("--n-frames", type=int, default=64)
    parser.add_argument("--frame-height", type=int, default=32)
    parser.add_argument("--frame-width", type=int, default=32)
    parser.add_argument("--n-rois", type=int, default=12)
    parser.add_argument("--n-state-bins", type=int, default=8)
    parser.add_argument("--frame-rate-hz", type=float, default=20.0)
    parser.add_argument("--noise", type=float, default=0.04)
    parser.add_argument("--decode-window-frames", type=int, default=4)
    return parser


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    args = build_arg_parser().parse_args()
    root = Path(args.output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    bundle = build_simulated_bundle(
        n_frames=args.n_frames,
        frame_shape=(args.frame_height, args.frame_width),
        n_rois=args.n_rois,
        n_state_bins=args.n_state_bins,
        noise=args.noise,
        frame_rate_hz=args.frame_rate_hz,
    )
    replay_path = save_replay_bundle(bundle, root / "replay_bundle.npz")
    calibration = build_coarse_place_calibration_bundle_from_replay(
        replay_source=replay_path,
        output_dir=root / "calibration_bundle",
        decode_window_frames=args.decode_window_frames,
        expected_state_bins=args.n_state_bins,
    )

    file_replay_params = {
        "data_source": "file_replay",
        "input_file": str(replay_path),
        "mode": "shadow",
        "reference_template": calibration.reference_template,
        "roi_manifest": calibration.roi_manifest,
        "decoder_path": calibration.decoder_bundle,
        "calibration_meta": calibration.calibration_meta,
        "output_dir": str(root / "workflow_output_file_replay"),
        "frame_rate_hz": args.frame_rate_hz,
        "controller_backend": "none",
    }
    raw_socket_params = {
        "data_source": "raw_socket",
        "mode": "shadow",
        "reference_template": calibration.reference_template,
        "roi_manifest": calibration.roi_manifest,
        "decoder_path": calibration.decoder_bundle,
        "calibration_meta": calibration.calibration_meta,
        "output_dir": str(root / "workflow_output_raw_socket"),
        "stream_host": "127.0.0.1",
        "stream_port": 7788,
        "stream_timeout_s": 5.0,
        "frame_rate_hz": args.frame_rate_hz,
        "controller_backend": "none",
    }
    file_replay_params_path = root / "params.file_replay.json"
    raw_socket_params_path = root / "params.raw_socket.json"
    _write_json(file_replay_params_path, file_replay_params)
    _write_json(raw_socket_params_path, raw_socket_params)

    print(
        json.dumps(
            {
                "output_root": str(root),
                "replay_bundle": str(replay_path),
                "calibration_bundle": calibration.to_dict(),
                "params_files": {
                    "file_replay": str(file_replay_params_path),
                    "raw_socket": str(raw_socket_params_path),
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
