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

main() {
    if [[ "${SKIP_OPENNEURO_MOUNTS:-0}" == "1" ]]; then
        echo -e "${YELLOW}Skipping OpenNeuro mounts (SKIP_OPENNEURO_MOUNTS=1)${NC}"
        return 0
    fi

    if ! command -v s3fs >/dev/null 2>&1; then
        echo -e "${YELLOW}s3fs not found; cannot mount OpenNeuro buckets.${NC}"
        return 1
    fi

    local openneuro_root="${OPENNEURO_MOUNT_ROOT:-/app/data/openneuro}"
    local deriv_root="${OPENNEURO_DERIV_ROOT:-/app/data/OpenNeuroDerivatives}"
    local openneuro_url="${OPENNEURO_S3_URL:-https://s3.amazonaws.com}"
    local deriv_url="${OPENNEURO_DERIV_S3_URL:-https://s3-us-west-2.amazonaws.com}"
    local deriv_endpoint="${OPENNEURO_DERIV_ENDPOINT:-us-west-2}"

    mkdir -p "$openneuro_root" \
        "$deriv_root/fmriprep" \
        "$deriv_root/mriqc" \
        "$deriv_root/fitlins" \
        "$deriv_root/xcpd"

    local failed=0

    if ! is_mounted "$openneuro_root"; then
        echo -e "${BLUE}Mounting OpenNeuro bucket to ${openneuro_root}...${NC}"
        if s3fs openneuro.org "$openneuro_root" \
            -o url="$openneuro_url" \
            -o use_path_request_style \
            -o public_bucket=1 \
            -o ro; then
            echo -e "${GREEN}✓ OpenNeuro mount ready${NC}"
        else
            echo -e "${YELLOW}Warning: failed to mount OpenNeuro bucket.${NC}"
            failed=1
        fi
    else
        echo -e "${GREEN}✓ OpenNeuro mount already present${NC}"
    fi

    local deriv_paths=(fmriprep mriqc fitlins xcpd)
    for sub in "${deriv_paths[@]}"; do
        local target="$deriv_root/$sub"
        if ! is_mounted "$target"; then
            echo -e "${BLUE}Mounting OpenNeuro derivatives $sub to ${target}...${NC}"
            if s3fs "openneuro-derivatives:/$sub" "$target" \
                -o url="$deriv_url" \
                -o endpoint="$deriv_endpoint" \
                -o use_path_request_style \
                -o public_bucket=1 \
                -o ro; then
                echo -e "${GREEN}✓ ${sub} mount ready${NC}"
            else
                echo -e "${YELLOW}Warning: failed to mount OpenNeuro derivatives: $sub.${NC}"
                failed=1
            fi
        else
            echo -e "${GREEN}✓ ${sub} mount already present${NC}"
        fi
    done

    return $failed
}

main "$@"
