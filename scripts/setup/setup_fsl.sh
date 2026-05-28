#!/bin/bash
# FSL Environment Setup Script (Containerized Version)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== FSL Environment Setup (Containerized) ===${NC}"
echo ""

# Set up Neurocommand environment for FSL
export NEUROCOMMAND_ROOT="/data/ECoG-foundation-model/mnndl_temp/brain_researcher/external/neurocommand"
export SINGULARITY_BINDPATH="${NEUROCOMMAND_ROOT},/data/ECoG-foundation-model/mnndl_temp/brain_researcher"

# Initialize Lmod
source /usr/share/lmod/lmod/init/bash

# Add Neurocommand modules to path
module use ${NEUROCOMMAND_ROOT}/local/containers/modules/

# Load FSL module
module load fsl/6.0.7.16

# Set FSL output type to compressed NIFTI
export FSLOUTPUTTYPE=NIFTI_GZ

echo -e "${GREEN}FSL environment set up successfully!${NC}"
echo "Using containerized FSL 6.0.7.16"
echo "FSLOUTPUTTYPE: $FSLOUTPUTTYPE"
echo ""
echo -e "${YELLOW}Available FSL commands:${NC}"
echo "  flirt -help    # Linear registration"
echo "  bet -help       # Brain extraction"
echo "  fslmaths -help  # Image arithmetic"
echo "  fslview -help   # GUI viewer (if display available)"
echo "  fsleyes -help   # Modern GUI viewer"
echo "  feat -help      # fMRI analysis"
echo "  melodic -help   # ICA analysis"
echo "  randomise -help # Statistical analysis"
echo ""
echo -e "${BLUE}Note: This uses the containerized FSL from Neurocommand${NC}"
echo "For local FSL installation, use the original setup script." 