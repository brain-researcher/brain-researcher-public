#!/bin/bash

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

is_mounted() {
    local target="$1"
    if command -v findmnt >/dev/null 2>&1; then
        findmnt -rno TARGET "$target" >/dev/null 2>&1
        return $?
    fi
    if command -v mountpoint >/dev/null 2>&1; then
        mountpoint -q "$target"
        return $?
    fi
    mount | grep -q " on ${target} " 2>/dev/null
}

mount_one() {
    local alias="$1"
    local bucket="$2"
    local url="$3"
    local endpoint="$4"
    local prefix="$5"
    local root="$6"

    local target="${root}/${alias}"
    mkdir -p "$target"

    if is_mounted "$target"; then
        echo -e "${GREEN}✓ ${alias} already mounted (${target})${NC}"
        return 0
    fi

    local source="${bucket}"
    local extra_opts=()
    if [[ -n "$prefix" ]]; then
        source="${bucket}:${prefix}"
    fi
    if [[ -n "$endpoint" ]]; then
        extra_opts+=(-o "endpoint=${endpoint}")
    fi

    echo -e "${BLUE}Mounting ${source} -> ${target}${NC}"
    if s3fs "$source" "$target" \
        -o "url=${url}" \
        -o use_path_request_style \
        -o public_bucket=1 \
        -o ro \
        "${extra_opts[@]}"; then
        echo -e "${GREEN}✓ Mounted ${alias}${NC}"
        return 0
    fi

    echo -e "${YELLOW}Warning: failed to mount ${alias}${NC}"
    return 1
}

main() {
    if [[ "${SKIP_PUBLIC_BUCKET_MOUNTS:-0}" == "1" ]]; then
        echo -e "${YELLOW}Skipping public bucket mounts (SKIP_PUBLIC_BUCKET_MOUNTS=1)${NC}"
        return 0
    fi

    if ! command -v s3fs >/dev/null 2>&1; then
        echo -e "${YELLOW}s3fs not found; cannot mount public S3 buckets.${NC}"
        return 1
    fi

    local root="${PUBLIC_BUCKET_MOUNT_ROOT:-/app/data/public_s3}"
    mkdir -p "$root"

    # alias|bucket|url|endpoint|prefix
    local p1_specs=(
        "natural-scenes-dataset|natural-scenes-dataset|https://s3.amazonaws.com||"
        "dandiarchive|dandiarchive|https://s3.amazonaws.com||"
        "ibl-brain-wide-map-public|ibl-brain-wide-map-public|https://s3.amazonaws.com||"
        "allen-mouse-brain-atlas|allen-mouse-brain-atlas|https://s3.amazonaws.com||"
        "openbluebrain|openbluebrain|https://s3.amazonaws.com||"
        "brainminds-marmoset-connectivity|brainminds-marmoset-connectivity|https://s3.amazonaws.com||"
        "hcp-openaccess|hcp-openaccess|https://s3.amazonaws.com||"
    )
    local p2_specs=(
        "mimic-iii-physionet|mimic-iii-physionet|https://s3.amazonaws.com||"
        "physionet-open-mimic-iv-demo|physionet-open|https://s3.amazonaws.com||/mimic-iv-demo"
        "physionet-open-mimic-iv-ecg|physionet-open|https://s3.amazonaws.com||/mimic-iv-ecg"
    )

    local failed=0
    local spec alias bucket url endpoint prefix

    for spec in "${p1_specs[@]}"; do
        IFS='|' read -r alias bucket url endpoint prefix <<< "$spec"
        if ! mount_one "$alias" "$bucket" "$url" "$endpoint" "$prefix" "$root"; then
            failed=1
        fi
    done

    if [[ "${PUBLIC_BUCKET_INCLUDE_P2:-1}" == "1" ]]; then
        for spec in "${p2_specs[@]}"; do
            IFS='|' read -r alias bucket url endpoint prefix <<< "$spec"
            if ! mount_one "$alias" "$bucket" "$url" "$endpoint" "$prefix" "$root"; then
                failed=1
            fi
        done
    fi

    if [[ "$failed" -ne 0 ]]; then
        echo -e "${YELLOW}Some bucket mounts failed. Re-run this script after verifying network and bucket accessibility.${NC}"
    fi
    return "$failed"
}

main "$@"
