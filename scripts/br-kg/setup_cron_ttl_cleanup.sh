#!/bin/bash
# Interactive helper to schedule ttl_edge_cleanup.py via cron.

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$( cd "${SCRIPT_DIR}/../.." && pwd )"
PYTHON_BIN=$(which python3)
LOG_DIR="${ROOT_DIR}/logs/ttl_cleanup"
mkdir -p "$LOG_DIR"

DEFAULT_URI="bolt://localhost:7687"
DEFAULT_USER="neo4j"
DEFAULT_PASSWORD="password"
DEFAULT_DATABASE="neo4j"
DEFAULT_ATLAS="yeo17"
DEFAULT_EDGE_SOURCE="neurosynth"

cleanup_cron_line() {
    local minute=$1
    local hour=$2
    local frequency=$3

    local schedule
    case $frequency in
        "hourly") schedule="${minute} * * * *" ;;
        "daily") schedule="${minute} ${hour} * * *" ;;
        "weekly") schedule="${minute} ${hour} * * 0" ;;
        *) echo "Invalid frequency"; exit 1 ;;
    esac

    echo "${schedule} ${PYTHON_BIN} ${SCRIPT_DIR}/ttl_edge_cleanup.py --neo4j-uri ${DEFAULT_URI} --neo4j-user ${DEFAULT_USER} --neo4j-password ${DEFAULT_PASSWORD} --neo4j-database ${DEFAULT_DATABASE} --atlas ${DEFAULT_ATLAS} --edge-source ${DEFAULT_EDGE_SOURCE} >> ${LOG_DIR}/cron.log 2>&1"
}

read -p "Select frequency (h=hourly, d=daily, w=weekly) [d]: " freq
case $freq in
    h|H) FREQUENCY="hourly" ;;
    w|W) FREQUENCY="weekly" ;;
    ""|d|D) FREQUENCY="daily" ;;
    *) echo "Unknown choice"; exit 1 ;;
 esac

if [ "$FREQUENCY" = "hourly" ]; then
    read -p "Minute (0-59) [5]: " minute
    minute=${minute:-5}
    hour=0
else
    read -p "Hour (0-23) [3]: " hour
    hour=${hour:-3}
    read -p "Minute (0-59) [15]: " minute
    minute=${minute:-15}
fi

CRON_LINE=$(cleanup_cron_line "$minute" "$hour" "$FREQUENCY")

if crontab -l 2>/dev/null | grep -q "ttl_edge_cleanup.py"; then
    crontab -l | grep -v "ttl_edge_cleanup.py" | crontab -
fi

(crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -

echo "TTL cleanup job installed:"
echo "$CRON_LINE"

echo "Logs: $LOG_DIR"
