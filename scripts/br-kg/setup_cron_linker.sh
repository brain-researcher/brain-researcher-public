#!/bin/bash
# Setup script for scheduled cross-source linking cron job

# Get the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BR_KG_DIR="$(dirname "$SCRIPT_DIR")"

# Default values
DB_PATH="${BR_KG_DIR}/data/br-kg/db/br-kg_full.db"
LOG_DIR="${BR_KG_DIR}/logs/scheduled"
REPORT_DIR="${BR_KG_DIR}/reports/scheduled_linking"
PYTHON_BIN=$(which python3)

# Function to add cron job
setup_cron() {
    local frequency=$1
    local hour=$2
    local minute=$3

    # Create the cron command
    CRON_CMD="${PYTHON_BIN} ${SCRIPT_DIR}/scheduled_cross_linker.py --database ${DB_PATH} --log-dir ${LOG_DIR} --report-dir ${REPORT_DIR}"

    # Create cron schedule based on frequency
    case $frequency in
        "daily")
            CRON_SCHEDULE="${minute} ${hour} * * *"
            ;;
        "weekly")
            CRON_SCHEDULE="${minute} ${hour} * * 0"
            ;;
        "hourly")
            CRON_SCHEDULE="${minute} * * * *"
            ;;
        *)
            echo "Invalid frequency. Use: daily, weekly, or hourly"
            exit 1
            ;;
    esac

    # Full cron line
    CRON_LINE="${CRON_SCHEDULE} ${CRON_CMD} >> ${LOG_DIR}/cron.log 2>&1"

    # Check if cron job already exists
    crontab -l 2>/dev/null | grep -q "scheduled_cross_linker.py"
    if [ $? -eq 0 ]; then
        echo "Warning: A scheduled_cross_linker cron job already exists:"
        crontab -l | grep "scheduled_cross_linker.py"
        read -p "Do you want to replace it? (y/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Aborting."
            exit 1
        fi
        # Remove existing job
        crontab -l | grep -v "scheduled_cross_linker.py" | crontab -
    fi

    # Add new cron job
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -

    echo "Cron job successfully added:"
    echo "$CRON_LINE"
    echo
    echo "The cross-source linker will run $frequency at ${hour}:${minute}"
}

# Interactive setup
echo "BR-KG Cross-Source Linker Cron Setup"
echo "======================================"
echo
echo "Current configuration:"
echo "  Database: $DB_PATH"
echo "  Log directory: $LOG_DIR"
echo "  Report directory: $REPORT_DIR"
echo "  Python: $PYTHON_BIN"
echo

# Check if database exists
if [ ! -f "$DB_PATH" ]; then
    echo "Warning: Database not found at $DB_PATH"
    read -p "Continue anyway? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Create directories if they don't exist
mkdir -p "$LOG_DIR"
mkdir -p "$REPORT_DIR"

# Get frequency
echo "How often should the linker run?"
echo "1) Daily"
echo "2) Weekly (Sundays)"
echo "3) Hourly"
read -p "Select frequency (1-3): " freq_choice

case $freq_choice in
    1) FREQUENCY="daily" ;;
    2) FREQUENCY="weekly" ;;
    3) FREQUENCY="hourly" ;;
    *) echo "Invalid choice"; exit 1 ;;
esac

# Get time for daily/weekly
if [ "$FREQUENCY" != "hourly" ]; then
    read -p "Enter hour (0-23) [default: 2]: " HOUR
    HOUR=${HOUR:-2}
    if ! [[ "$HOUR" =~ ^[0-9]+$ ]] || [ "$HOUR" -lt 0 ] || [ "$HOUR" -gt 23 ]; then
        echo "Invalid hour. Must be 0-23"
        exit 1
    fi
else
    HOUR=0
fi

read -p "Enter minute (0-59) [default: 0]: " MINUTE
MINUTE=${MINUTE:-0}
if ! [[ "$MINUTE" =~ ^[0-9]+$ ]] || [ "$MINUTE" -lt 0 ] || [ "$MINUTE" -gt 59 ]; then
    echo "Invalid minute. Must be 0-59"
    exit 1
fi

# Confirm and setup
echo
echo "Summary:"
echo "--------"
echo "Frequency: $FREQUENCY"
if [ "$FREQUENCY" != "hourly" ]; then
    echo "Time: ${HOUR}:$(printf %02d $MINUTE)"
else
    echo "Time: :$(printf %02d $MINUTE) every hour"
fi
echo

read -p "Proceed with setup? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    setup_cron "$FREQUENCY" "$HOUR" "$MINUTE"
    echo
    echo "Setup complete!"
    echo
    echo "To view your cron jobs: crontab -l"
    echo "To remove this job: crontab -l | grep -v scheduled_cross_linker.py | crontab -"
    echo "To test the job manually: $PYTHON_BIN ${SCRIPT_DIR}/scheduled_cross_linker.py --dry-run"
else
    echo "Setup cancelled."
fi
