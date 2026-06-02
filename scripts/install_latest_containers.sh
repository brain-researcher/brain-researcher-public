#!/bin/bash
# Install Latest Versions of Popular Neuroimaging Containers

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Installing Latest Neuroimaging Containers ===${NC}"
echo ""

# Change to neurocommand directory
cd ${BR_HOME:-/app/brain_researcher}/external/neurocommand

# Function to get the latest version of a tool
get_latest_version() {
    local tool=$1
    bash containers.sh $tool | grep "| $tool |" | tail -1 | awk -F'|' '{print $2, $3, $4}' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

# Function to install a container
install_container() {
    local tool=$1
    local version=$2
    local date=$3
    local description=$4

    echo -e "${YELLOW}Installing $tool $version ($date)...${NC}"
    echo "Description: $description"

    ./local/fetch_containers.sh $tool $version $date

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ $tool $version installed successfully${NC}"
    else
        echo -e "${RED}✗ Failed to install $tool $version${NC}"
    fi
    echo ""
}

# List of popular tools to install
declare -a tools=(
    "freesurfer"
    "ants"
    "mrtrix3"
    "fmriprep"
    "mriqc"
    "itksnap"
    "slicer"
    "spm12"
    "cat12"
    "workbench"
    "afni"
    "fsl"
)

echo -e "${BLUE}Finding latest versions...${NC}"
echo ""

# Install latest version of each tool
for tool in "${tools[@]}"; do
    echo -e "${BLUE}Checking latest version of $tool...${NC}"

    # Get the latest version
    latest_info=$(get_latest_version $tool)

    if [ -n "$latest_info" ]; then
        # Parse the version info
        version=$(echo "$latest_info" | awk '{print $2}')
        date=$(echo "$latest_info" | awk '{print $3}')

        echo -e "${GREEN}Latest $tool: $version ($date)${NC}"

        # Install the container
        install_container $tool $version $date "Latest version of $tool"
    else
        echo -e "${RED}Could not find latest version for $tool${NC}"
    fi
done

echo -e "${GREEN}=== Installation Complete ===${NC}"
echo ""
echo -e "${BLUE}To use the installed containers:${NC}"
echo "1. Set up environment: source scripts/setup_neurocommand.sh"
echo "2. Load modules:"
echo "   module avail                    # See all available modules"
echo "   module load freesurfer/8.0.0   # Load FreeSurfer"
echo "   module load ants/2.4.1         # Load ANTs"
echo "   module load mrtrix3/3.0.4      # Load MRtrix3"
echo ""
echo "3. Or use the launch menu: ./launch.sh (option 8)"
echo ""
echo -e "${YELLOW}Note: Each container is ~2-8GB, so monitor your disk space!${NC}"