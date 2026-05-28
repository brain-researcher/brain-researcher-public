#!/bin/bash

# Creates wrapper scripts for containerized tools
# Usage: create_tool_wrappers.sh <tool> <version> <date>

TOOL=$1
VERSION=$2
DATE=$3

PROJECT_ROOT="$(dirname $(dirname $(readlink -f $0)))"
CONTAINER_NAME="${TOOL}_${VERSION}_${DATE}"
CONTAINER_DIR="${PROJECT_ROOT}/external/neurocommand/neurocommand-repo/local/containers/${CONTAINER_NAME}"
CONTAINER_PATH="${CONTAINER_DIR}/${CONTAINER_NAME}.simg"
BIN_DIR="${PROJECT_ROOT}/bin"

mkdir -p "${BIN_DIR}"

# Check if container exists
if [ ! -f "${CONTAINER_PATH}" ]; then
    # Try to find any .simg or .sif file in the container directory
    CONTAINER_PATH=$(find "${CONTAINER_DIR}" -name "*.simg" -o -name "*.sif" 2>/dev/null | head -1)
fi

if [ -z "${CONTAINER_PATH}" ] || [ ! -f "${CONTAINER_PATH}" ]; then
    echo "Container not found: ${CONTAINER_PATH}"
    exit 1
fi

# Tool-specific wrapper creation
case "$TOOL" in
    fsl)
        # Create wrappers for common FSL commands
        FSL_COMMANDS="bet flirt fnirt fslmaths fslmerge fslsplit fslstats fsleyes fsl feat melodic"
        for cmd in $FSL_COMMANDS; do
            cat > "${BIN_DIR}/${cmd}" << EOF
#!/bin/bash
exec apptainer exec "${CONTAINER_PATH}" ${cmd} "\$@"
EOF
            chmod +x "${BIN_DIR}/${cmd}"
        done
        
        # Create general fsl wrapper
        cat > "${BIN_DIR}/fsl" << EOF
#!/bin/bash
if [ -z "\$1" ]; then
    apptainer exec "${CONTAINER_PATH}" fsl
else
    apptainer exec "${CONTAINER_PATH}" "\$@"
fi
EOF
        chmod +x "${BIN_DIR}/fsl"
        ;;
        
    afni)
        # Create wrappers for common AFNI commands  
        AFNI_COMMANDS="3dinfo 3dcalc 3dvolreg 3dANOVA 3dDeconvolve 3dREMLfit afni suma"
        for cmd in $AFNI_COMMANDS; do
            cat > "${BIN_DIR}/${cmd}" << EOF
#!/bin/bash
exec apptainer exec "${CONTAINER_PATH}" ${cmd} "\$@"
EOF
            chmod +x "${BIN_DIR}/${cmd}"
        done
        
        # Create general afni wrapper
        cat > "${BIN_DIR}/afni_wrapper" << EOF
#!/bin/bash
exec apptainer exec "${CONTAINER_PATH}" "\$@"
EOF
        chmod +x "${BIN_DIR}/afni_wrapper"
        ;;
        
    freesurfer)
        # Create wrappers for common FreeSurfer commands
        FS_COMMANDS="recon-all mri_convert mris_convert freeview tkmedit tksurfer"
        for cmd in $FS_COMMANDS; do
            cat > "${BIN_DIR}/${cmd}" << EOF
#!/bin/bash
export FREESURFER_HOME=/opt/freesurfer
exec apptainer exec "${CONTAINER_PATH}" ${cmd} "\$@"
EOF
            chmod +x "${BIN_DIR}/${cmd}"
        done
        ;;
        
    fmriprep)
        # Create fmriprep wrapper
        cat > "${BIN_DIR}/fmriprep" << EOF
#!/bin/bash
exec apptainer run "${CONTAINER_PATH}" "\$@"
EOF
        chmod +x "${BIN_DIR}/fmriprep"
        ;;
        
    mriqc)
        # Create mriqc wrapper
        cat > "${BIN_DIR}/mriqc" << EOF
#!/bin/bash
exec apptainer run "${CONTAINER_PATH}" "\$@"
EOF
        chmod +x "${BIN_DIR}/mriqc"
        ;;
        
    *)
        # Generic wrapper for unknown tools
        cat > "${BIN_DIR}/${TOOL}" << EOF
#!/bin/bash
exec apptainer exec "${CONTAINER_PATH}" "\$@"
EOF
        chmod +x "${BIN_DIR}/${TOOL}"
        ;;
esac

echo "Wrapper scripts created for ${TOOL} in ${BIN_DIR}"
