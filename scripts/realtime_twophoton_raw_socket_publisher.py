#!/usr/bin/env python3
"""Publish two-photon frames to the realtime_twophoton raw_socket runtime."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from brain_researcher.services.tools.realtime_twophoton_publisher import (
    publish_frames_to_raw_socket,
    publish_replay_bundle_to_raw_socket,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Publish frame stacks or replay bundles to the realtime_twophoton "
            "raw_socket listener."
        )
    )
    parser.add_argument("--host", default="127.0.0.1", help="Listener host")
    parser.add_argument("--port", type=int, default=7788, help="Listener TCP port")
    parser.add_argument(
        "--replay",
        type=Path,
        default=None,
        help="Path to a replay .npz bundle containing frames and optional timestamps_s",
    )
    parser.add_argument(
        "--frames",
        type=Path,
        default=None,
        help="Path to a .npy file with shape [n_frames, height, width]",
    )
    parser.add_argument(
        "--timestamps",
        type=Path,
        default=None,
        help="Optional .npy timestamps file aligned to --frames",
    )
    parser.add_argument(
        "--connect-timeout-s",
        type=float,
        default=5.0,
        help="Maximum time to wait for the listener to accept a connection",
    )
    parser.add_argument(
        "--write-timeout-s",
        type=float,
        default=5.0,
        help="Socket write timeout after connection is established",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if bool(args.replay) == bool(args.frames):
        parser.error("Provide exactly one of --replay or --frames")

    if args.replay:
        sent = publish_replay_bundle_to_raw_socket(
            args.replay,
            host=args.host,
            port=args.port,
            connect_timeout_s=args.connect_timeout_s,
            write_timeout_s=args.write_timeout_s,
        )
    else:
        frames = np.load(args.frames).astype(np.float32)
        timestamps = (
            np.load(args.timestamps).astype(np.float32) if args.timestamps else None
        )
        sent = publish_frames_to_raw_socket(
            frames,
            host=args.host,
            port=args.port,
            timestamps_s=timestamps,
            connect_timeout_s=args.connect_timeout_s,
            write_timeout_s=args.write_timeout_s,
        )

    print(
        f"Published {sent} frame(s) to raw_socket listener at "
        f"{args.host}:{int(args.port)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
