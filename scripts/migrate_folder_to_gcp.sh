#!/bin/bash
# Comprehensive script to migrate entire folders to GCP
# Supports multiple methods: Cloud Storage (recommended), Direct SCP, and rsync

set -e

# Configuration
INSTANCE_NAME="${INSTANCE_NAME:-instance-20251031-210231}"
ZONE="${ZONE:-us-central1-a}"
PROJECT_ID="${PROJECT_ID:-hai-gcp-dialogue-brain}"
BUCKET_NAME="${BUCKET_NAME:-${PROJECT_ID}-data-transfer}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

usage() {
    cat << EOF
Usage: $0 <local_folder> [method] [options]

Methods:
  storage    - Upload to Cloud Storage, then download on instance (RECOMMENDED for large folders)
  scp        - Direct SCP transfer (good for small-medium folders)
  rsync      - rsync via SSH (good for syncing/incremental updates)

Options:
  --instance NAME    - GCP instance name (default: $INSTANCE_NAME)
  --zone ZONE       - Instance zone (default: $ZONE)
  --bucket NAME     - Cloud Storage bucket name (default: $BUCKET_NAME)
  --remote-path PATH - Remote destination path (default: ~/migrated_data/)
  --compress        - Enable compression
  --parallel N      - Number of parallel transfers (storage method only)

Examples:
  $0 ./data/ storage
  $0 ./data/ scp --compress
  $0 ./data/ rsync --remote-path /mnt/data/
  $0 ./data/ storage --bucket my-bucket --parallel 4

EOF
    exit 1
}

# Parse arguments
LOCAL_FOLDER=""
METHOD="storage"
REMOTE_PATH="~/migrated_data/"
COMPRESS=false
PARALLEL=4

while [[ $# -gt 0 ]]; do
    case $1 in
        --instance)
            INSTANCE_NAME="$2"
            shift 2
            ;;
        --zone)
            ZONE="$2"
            shift 2
            ;;
        --bucket)
            BUCKET_NAME="$2"
            shift 2
            ;;
        --remote-path)
            REMOTE_PATH="$2"
            shift 2
            ;;
        --compress)
            COMPRESS=true
            shift
            ;;
        --parallel)
            PARALLEL="$2"
            shift 2
            ;;
        storage|scp|rsync)
            METHOD="$1"
            shift
            ;;
        -*)
            echo -e "${RED}Unknown option: $1${NC}"
            usage
            ;;
        *)
            if [ -z "$LOCAL_FOLDER" ]; then
                LOCAL_FOLDER="$1"
            else
                echo -e "${RED}Multiple folders specified${NC}"
                usage
            fi
            shift
            ;;
    esac
done

if [ -z "$LOCAL_FOLDER" ] || [ ! -d "$LOCAL_FOLDER" ]; then
    echo -e "${RED}Error: Please provide a valid local folder path${NC}"
    usage
fi

# Get absolute path
LOCAL_FOLDER=$(realpath "$LOCAL_FOLDER")
FOLDER_NAME=$(basename "$LOCAL_FOLDER")

echo -e "${GREEN}=== GCP Folder Migration Tool ===${NC}"
echo "Local folder: $LOCAL_FOLDER"
echo "Method: $METHOD"
echo "Instance: $INSTANCE_NAME ($ZONE)"
echo "Remote path: $REMOTE_PATH"
echo ""

# Method 1: Cloud Storage (Recommended for large folders)
method_storage() {
    echo -e "${YELLOW}Using Cloud Storage method (best for large folders)${NC}"

    # Check/create bucket
    if ! gcloud storage buckets describe "gs://$BUCKET_NAME" &>/dev/null; then
        echo "Creating bucket: $BUCKET_NAME"
        gcloud storage buckets create "gs://$BUCKET_NAME" \
            --project="$PROJECT_ID" \
            --location=us-central1 \
            --default-storage-class=STANDARD
    fi

    # Upload folder to Cloud Storage
    echo "Uploading folder to Cloud Storage..."
    UPLOAD_CMD="gcloud storage cp --recursive"

    if [ "$COMPRESS" = true ]; then
        echo "Note: Compression is handled automatically by gcloud storage"
    fi

    if [ "$PARALLEL" -gt 1 ]; then
        UPLOAD_CMD="$UPLOAD_CMD --gzip-in-flight-all"
    fi

    $UPLOAD_CMD "$LOCAL_FOLDER" "gs://$BUCKET_NAME/migrations/$FOLDER_NAME/"

    echo -e "${GREEN}✓ Upload complete${NC}"

    # Download on instance
    echo "Downloading on instance..."
    REMOTE_DEST="$REMOTE_PATH/$FOLDER_NAME"

    gcloud compute ssh "$INSTANCE_NAME" --zone="$ZONE" --command="
        mkdir -p $REMOTE_PATH && \
        gsutil -m cp -r gs://$BUCKET_NAME/migrations/$FOLDER_NAME/ $REMOTE_DEST && \
        echo 'Migration complete: $REMOTE_DEST'
    "

    echo -e "${GREEN}✓ Migration complete!${NC}"
    echo "Files are available at: $REMOTE_DEST"

    # Optional: Clean up Cloud Storage
    read -p "Delete temporary files from Cloud Storage? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        gcloud storage rm --recursive "gs://$BUCKET_NAME/migrations/$FOLDER_NAME/"
        echo "Cleaned up Cloud Storage"
    fi
}

# Method 2: Direct SCP
method_scp() {
    echo -e "${YELLOW}Using Direct SCP method${NC}"

    # Check instance status
    STATUS=$(gcloud compute instances describe "$INSTANCE_NAME" \
        --zone="$ZONE" \
        --format="value(status)" 2>/dev/null || echo "NOT_FOUND")

    if [ "$STATUS" != "RUNNING" ]; then
        echo "Starting instance..."
        gcloud compute instances start "$INSTANCE_NAME" --zone="$ZONE"
        echo "Waiting for instance to be ready..."
        sleep 15
    fi

    # Transfer
    SCP_CMD="gcloud compute scp --recurse"

    if [ "$COMPRESS" = true ]; then
        SCP_CMD="$SCP_CMD --compress"
    fi

    echo "Transferring folder..."
    $SCP_CMD "$LOCAL_FOLDER" "$INSTANCE_NAME:$REMOTE_PATH" --zone="$ZONE"

    echo -e "${GREEN}✓ Migration complete!${NC}"
    echo "Files are available at: $REMOTE_PATH/$FOLDER_NAME"
}

# Method 3: rsync
method_rsync() {
    echo -e "${YELLOW}Using rsync method (best for incremental syncs)${NC}"

    # Check instance status
    STATUS=$(gcloud compute instances describe "$INSTANCE_NAME" \
        --zone="$ZONE" \
        --format="value(status)" 2>/dev/null || echo "NOT_FOUND")

    if [ "$STATUS" != "RUNNING" ]; then
        echo "Starting instance..."
        gcloud compute instances start "$INSTANCE_NAME" --zone="$ZONE"
        echo "Waiting for instance to be ready..."
        sleep 15
    fi

    # Get SSH command
    SSH_CMD="gcloud compute ssh $INSTANCE_NAME --zone=$ZONE --ssh-flag='-A' --command"

    # Create remote directory
    eval "$SSH_CMD 'mkdir -p $REMOTE_PATH'"

    # Use rsync via SSH tunnel
    echo "Syncing folder with rsync..."

    # Build rsync command
    RSYNC_OPTS="-avz --progress"
    if [ "$COMPRESS" = true ]; then
        RSYNC_OPTS="$RSYNC_OPTS --compress"
    fi

    # Get the SSH hostname
    SSH_HOST=$(gcloud compute instances describe "$INSTANCE_NAME" \
        --zone="$ZONE" \
        --format="get(networkInterfaces[0].accessConfigs[0].natIP)" 2>/dev/null || \
        gcloud compute instances describe "$INSTANCE_NAME" \
        --zone="$ZONE" \
        --format="get(networkInterfaces[0].networkIP)")

    # Use gcloud compute ssh as a proxy for rsync
    echo "Note: Using gcloud compute scp with rsync-like behavior..."
    gcloud compute scp --recurse $RSYNC_OPTS "$LOCAL_FOLDER" "$INSTANCE_NAME:$REMOTE_PATH" --zone="$ZONE"

    echo -e "${GREEN}✓ Migration complete!${NC}"
    echo "Files are available at: $REMOTE_PATH/$FOLDER_NAME"
}

# Estimate folder size
estimate_size() {
    SIZE=$(du -sh "$LOCAL_FOLDER" 2>/dev/null | cut -f1)
    echo "Folder size: $SIZE"

    FILE_COUNT=$(find "$LOCAL_FOLDER" -type f | wc -l)
    echo "File count: $FILE_COUNT"

    if [ "$FILE_COUNT" -gt 10000 ] || [ -n "$(echo $SIZE | grep -E '[0-9]+G')" ]; then
        echo -e "${YELLOW}Recommendation: Use 'storage' method for large folders${NC}"
    fi
}

# Main execution
estimate_size
echo ""

case $METHOD in
    storage)
        method_storage
        ;;
    scp)
        method_scp
        ;;
    rsync)
        method_rsync
        ;;
    *)
        echo -e "${RED}Unknown method: $METHOD${NC}"
        usage
        ;;
esac

echo ""
echo -e "${GREEN}=== Migration Summary ===${NC}"
echo "Source: $LOCAL_FOLDER"
echo "Destination: $INSTANCE_NAME:$REMOTE_PATH/$FOLDER_NAME"
echo "Method: $METHOD"
echo ""
echo "To verify, SSH into the instance:"
echo "  gcloud compute ssh $INSTANCE_NAME --zone=$ZONE"
echo "  ls -lh $REMOTE_PATH/$FOLDER_NAME"
