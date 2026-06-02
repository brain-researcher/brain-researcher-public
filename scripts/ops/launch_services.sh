#!/bin/bash
# Main Launch Script for Brain Researcher Services
# This script sets up the environment and can launch various services

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Brain Researcher Services Launcher ===${NC}"
echo ""

# Set up FSL environment
echo -e "${YELLOW}Setting up FSL environment...${NC}"
source "$(dirname "$0")/setup_fsl.sh"

# Set up other environment variables
export BRAIN_RESEARCHER_ROOT="/data/ECoG-foundation-model/mnndl_temp/brain_researcher"
export PYTHONPATH="${BRAIN_RESEARCHER_ROOT}/src:${PYTHONPATH}"

echo -e "${GREEN}Environment setup complete!${NC}"
echo ""

# Function to show available services
show_services() {
    echo -e "${BLUE}Available Services:${NC}"
    echo "1. FSL - Neuroimaging tools"
    echo "2. Brain Researcher API"
    echo "3. Interactive Python"
    echo "4. Jupyter Notebook"
    echo "5. Custom command"
    echo "6. Neurodesk Containers"
    echo "7. Install Neuroimaging Tools"
    echo "8. Neurocommand (Containerized)"
    echo ""
}

# Function to launch FSL
launch_fsl() {
    echo -e "${GREEN}Launching FSL...${NC}"
    echo "FSL is now available. You can use commands like:"
    echo "  flirt -help"
    echo "  bet -help"
    echo "  fslmaths -help"
    echo ""
    echo "Type 'exit' to return to main menu"
    bash
}

# Function to launch Brain Researcher API
launch_api() {
    echo -e "${GREEN}Launching Brain Researcher API...${NC}"
    cd "$BRAIN_RESEARCHER_ROOT"
    python launch.py
}

# Function to launch interactive Python
launch_python() {
    echo -e "${GREEN}Launching Interactive Python...${NC}"
    cd "$BRAIN_RESEARCHER_ROOT"
    python
}

# Function to launch Jupyter
launch_jupyter() {
    echo -e "${GREEN}Launching Jupyter Notebook...${NC}"
    cd "$BRAIN_RESEARCHER_ROOT"
    jupyter notebook --ip=0.0.0.0 --port=8888 --no-browser --allow-root
}

# Function to run custom command
run_custom() {
    echo -e "${YELLOW}Enter your custom command:${NC}"
    read -r custom_cmd
    echo -e "${GREEN}Running: $custom_cmd${NC}"
    eval "$custom_cmd"
}

# Function to launch Neurodesk containers
launch_neurodesk() {
    echo -e "${GREEN}=== Neurodesk Containers ===${NC}"
    echo "Available containers:"
    echo "1. AFNI"
    echo "2. FreeSurfer"
    echo "3. ANTs"
    echo "4. MRtrix3"
    echo "5. fMRIPrep"
    echo "6. MRIQC"
    echo "7. Back to main menu"
    echo ""
    echo -e "${YELLOW}Select container (1-7):${NC}"
    read -r container_choice

    case $container_choice in
        1)
            docker run --rm -it -v $(pwd):/data neurodesk/afni:latest
            ;;
        2)
            docker run --rm -it -v $(pwd):/data neurodesk/freesurfer:latest
            ;;
        3)
            docker run --rm -it -v $(pwd):/data neurodesk/ants:latest
            ;;
        4)
            docker run --rm -it -v $(pwd):/data neurodesk/mrtrix3:latest
            ;;
        5)
            docker run --rm -it -v $(pwd):/data neurodesk/fmriprep:latest
            ;;
        6)
            docker run --rm -it -v $(pwd):/data neurodesk/mriqc:latest
            ;;
        7)
            return
            ;;
        *)
            echo -e "${RED}Invalid choice.${NC}"
            ;;
    esac
}

# Function to install neuroimaging tools
install_tools() {
    echo -e "${GREEN}Launching Neuroimaging Tools Installer...${NC}"
    "$(dirname "$0")/install_neuroimaging_tools.sh"
}

# Function to launch Neurocommand
launch_neurocommand() {
    echo -e "${GREEN}=== Neurocommand (Containerized) ===${NC}"
    echo "Setting up Neurocommand environment..."

    # Source Neurocommand setup
    source "$(dirname "$0")/setup_neurocommand.sh"

    echo ""
    echo -e "${BLUE}Neurocommand is now available!${NC}"
    echo "Available commands:"
    echo "  module avail          # List all available modules"
    echo "  module load fsl/6.0.7.16    # Load FSL module"
    echo "  module load afni/23.0.07    # Load AFNI module"
    echo "  flirt -help           # Use FSL tools"
    echo "  3dinfo -help          # Use AFNI tools"
    echo ""
    echo "Type 'exit' to return to main menu"
    bash
}

# Main menu
while true; do
    show_services
    echo -e "${YELLOW}Select a service (1-8) or 'q' to quit:${NC}"
    read -r choice

    case $choice in
        1)
            launch_fsl
            ;;
        2)
            launch_api
            ;;
        3)
            launch_python
            ;;
        4)
            launch_jupyter
            ;;
        5)
            run_custom
            ;;
        6)
            launch_neurodesk
            ;;
        7)
            install_tools
            ;;
        8)
            launch_neurocommand
            ;;
        q|Q)
            echo -e "${GREEN}Goodbye!${NC}"
            exit 0
            ;;
        *)
            echo -e "${RED}Invalid choice. Please try again.${NC}"
            ;;
    esac

    echo ""
    echo -e "${YELLOW}Press Enter to continue...${NC}"
    read -r
done
