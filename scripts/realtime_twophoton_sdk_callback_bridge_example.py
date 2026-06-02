#!/usr/bin/env python3
"""Example microscope-SDK callback bridge for realtime two-photon streaming.

This script simulates the common pattern:
1. BR workflow/tool listens on the raw_socket port.
2. A microscope SDK invokes a frame callback with a payload object/dict.
3. The bridge maps that payload into the realtime_twophoton wire protocol.
"""

from __future__ import annotations

import argparse
import time

import numpy as np

from brain_researcher.services.tools.realtime_twophoton import (
    MicroscopeFrameAdapter,
    MicroscopeFrameAdapterConfig,
    RawSocketPublisherConfig,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="raw_socket listener host")
    parser.add_argument("--port", type=int, default=7788, help="raw_socket listener port")
    parser.add_argument("--n-frames", type=int, default=20, help="number of synthetic frames")
    parser.add_argument("--height", type=int, default=64, help="frame height")
    parser.add_argument("--width", type=int, default=64, help="frame width")
    parser.add_argument(
        "--session-id",
        default="sdk_callback_example",
        help="session id sent in stream_start metadata",
    )
    parser.add_argument(
        "--source-name",
        default="vendor_sdk_example",
        help="source name sent in stream_start metadata",
    )
    parser.add_argument(
        "--sleep-s",
        type=float,
        default=0.01,
        help="delay between synthetic callback events",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    rng = np.random.default_rng(0)

    adapter = MicroscopeFrameAdapter(
        MicroscopeFrameAdapterConfig(
            publisher=RawSocketPublisherConfig(host=args.host, port=args.port),
            session_id=args.session_id,
            source_name=args.source_name,
            auto_timestamp=False,
        )
    )
    callback = adapter.make_field_callback(
        frame_field=("frame", "image"),
        timestamp_field=("timestamp_s", "timestamp"),
        frame_id_field=("frame_id", "index"),
        metadata_fields={"plane": "plane"},
        optional_metadata_fields={"channel": "channel"},
    )

    adapter.start_session({"bridge": "sdk_callback_example"})
    t0 = time.perf_counter()
    try:
        for frame_idx in range(args.n_frames):
            payload = {
                "image": rng.normal(size=(args.height, args.width)).astype(np.float32),
                "timestamp": t0 + frame_idx * args.sleep_s,
                "index": frame_idx,
                "plane": 0,
                "channel": "green",
            }
            callback(payload)
            time.sleep(args.sleep_s)
    finally:
        adapter.end_session({"status": "complete"})
        adapter.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
