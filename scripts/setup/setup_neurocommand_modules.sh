#!/bin/sh
# Neurodesk Module Setup - Official Linux/HPC Approach
# 
# Architecture:
#   - Host: Uses module system to manage local + CVMFS tools
#   - Containers: Run silently with bound modules.sh override
#   - Priority: Local modules first, CVMFS fallback
#
# Key fixes applied:
#   ✓ Silent containers (no modules.sh errors)
#   ✓ Working directory fix (project path bound)
#   ✓ Unified bind paths (no conflicts)
#   ✓ Module system integration (standard commands)

# Set paths
PROJECT_ROOT="$HOME/projects/brain_researcher"
LOCAL_MODULES="${PROJECT_ROOT}/external/neurocommand/neurocommand-repo/local/containers/modules"

# Create modules.sh override for silent containers (if not exists)
if [ ! -f "$HOME/nd_overrides/modules.sh" ]; then
    mkdir -p "$HOME/nd_overrides"
    cat > "$HOME/nd_overrides/modules.sh" <<'EOF'
# Silent module loader - only source if exists
[ -r /etc/profile.d/lmod.sh ] && . /etc/profile.d/lmod.sh || :
[ -r /usr/share/modules/init/sh ] && . /usr/share/modules/init/sh || :
true
EOF
fi

# Initialize Lmod on host (try common locations)
for lmod_init in \
    "/usr/share/lmod/lmod/init/bash" \
    "/usr/share/lmod/8.6.19/init/bash" \
    "/etc/profile.d/lmod.sh"; do
    if [ -f "$lmod_init" ]; then
        . "$lmod_init" 2>/dev/null && break
    fi
done

# Ensure conda python stays ahead of module-provided interpreters
restore_conda_path() {
    if [ -n "${CONDA_PREFIX:-}" ] && [ -d "${CONDA_PREFIX}/bin" ]; then
        conda_bin="${CONDA_PREFIX}/bin"
        new_path="$conda_bin"
        old_ifs=$IFS
        IFS=':'
        for path_segment in $PATH; do
            if [ "$path_segment" = "$conda_bin" ] || [ -z "$path_segment" ]; then
                continue
            fi
            new_path="${new_path}:$path_segment"
        done
        IFS=$old_ifs
        PATH="$new_path"
        export PATH
        unset conda_bin new_path old_ifs path_segment
    fi
}

restore_conda_path

# Configure module paths (host side)
# 1. Local modules first (priority for high-frequency tools)
if [ -d "${LOCAL_MODULES}" ]; then
    module use "${LOCAL_MODULES}" 2>/dev/null
fi

# 2. CVMFS modules (long-tail tools, auto-cached)
for cvmfs_module_path in \
    "/cvmfs/neurodesk.ardc.edu.au/neurodesk-modules/functional_imaging" \
    "/cvmfs/neurodesk.ardc.edu.au/neurodesk-modules/structural_imaging" \
    "/cvmfs/neurodesk.ardc.edu.au/neurodesk-modules/diffusion_imaging" \
    "/cvmfs/neurodesk.ardc.edu.au/neurodesk-modules/bids_apps"; do
    if [ -d "$cvmfs_module_path" ]; then
        module use "$cvmfs_module_path" 2>/dev/null
    fi
done

# Preload essential neuroimaging modules so ToolRegistry discovery works out of the box
for mod_name in \
    fsl/6.0.7.18 \
    freesurfer/8.1.0 \
    ants/2.6.0 \
    afni/25.2.03 \
    connectomeworkbench/1.5.0 \
    mrtrix3/3.0.4; do
    if ! command -v module >/dev/null 2>&1; then
        echo "⚠️  Lmod not initialised; cannot load $mod_name" >&2
        continue
    fi

    if ! eval "$($LMOD_CMD bash load "$mod_name" 2>/dev/null)"; then
        echo "⚠️  Optional module $mod_name not available; skipping preload" >&2
    else
        echo "Loaded $mod_name"
    fi
done

restore_conda_path

# Normalise common environment variables expected by tool discovery
if command -v fslmaths >/dev/null 2>&1; then
    export FSLDIR="${FSLDIR:-$(dirname "$(command -v fslmaths)")}"
    export APPTAINERENV_FSLDIR="$FSLDIR"
fi

if command -v recon-all >/dev/null 2>&1; then
    export FREESURFER_HOME="${FREESURFER_HOME:-$(dirname "$(command -v recon-all)")}" 
    export APPTAINERENV_FREESURFER_HOME="$FREESURFER_HOME"
fi

if command -v antsRegistration >/dev/null 2>&1; then
    export ANTSPATH="${ANTSPATH:-$(dirname "$(command -v antsRegistration)")}"
    export APPTAINERENV_ANTSPATH="$ANTSPATH"
fi

# Set unified bind paths with modules.sh override
export APPTAINER_BINDPATH="${PROJECT_ROOT}:${PROJECT_ROOT},${HOME}:${HOME},/tmp:/tmp"

# Add CVMFS if available
if [ -d "/cvmfs" ]; then
    export APPTAINER_BINDPATH="${APPTAINER_BINDPATH},/cvmfs:/cvmfs"
fi

# Bind the silent modules.sh override (KEY FIX)
export APPTAINER_BINDPATH="${APPTAINER_BINDPATH},${HOME}/nd_overrides/modules.sh:/etc/profile.d/modules.sh"

# Keep both variables unified
export SINGULARITY_BINDPATH="${APPTAINER_BINDPATH}"

# Essential environment variables for containers
export FS_LICENSE="${HOME}/.freesurfer_license.txt"
export TEMPLATEFLOW_HOME="${HOME}/.cache/templateflow"
export APPTAINERENV_FS_LICENSE="${FS_LICENSE}"
export APPTAINERENV_TEMPLATEFLOW_HOME="${TEMPLATEFLOW_HOME}"
export NUMBA_CACHE_DIR="${NUMBA_CACHE_DIR:-/tmp/numba_cache}"
mkdir -p "${NUMBA_CACHE_DIR}" 2>/dev/null
chmod 777 "${NUMBA_CACHE_DIR}" 2>/dev/null || true

# Create templateflow directory if needed
mkdir -p "${TEMPLATEFLOW_HOME}" 2>/dev/null

# Cache configuration (use optimized NVMe locations)
# Use NVMe for performance-critical caches unless SCRATCH is explicitly set
if [ -n "$SCRATCH" ]; then
    export APPTAINER_CACHEDIR="${SCRATCH}/.apptainer-cache"
    export SINGULARITY_CACHEDIR="${SCRATCH}/.singularity-cache"
    mkdir -p "${APPTAINER_CACHEDIR}" 2>/dev/null
else
    # Use NVMe locations for optimal performance
    export APPTAINER_CACHEDIR="/var/tmp/.apptainer-cache"
    export APPTAINER_TMPDIR="/var/tmp/.apptainer-tmp"
    export SINGULARITY_CACHEDIR="/var/tmp/.apptainer-cache"
    export SINGULARITY_TMPDIR="/var/tmp/.apptainer-tmp"
    # Directories should already exist from system setup
fi

# Add CVMFS progress notification for module loads
export LMOD_PAGER=cat  # Disable pager for module commands

# Save original module function and create wrapper
if command -v module >/dev/null 2>&1; then
    # Create alias to wrap module load with progress indication
    alias module='neurodesk_module_wrapper'
    
    neurodesk_module_wrapper() {
        cmd="$1"
        shift
        wrapped_module_name=""
        
        if [ "$cmd" = "load" ]; then
            wrapped_module_name="$1"
            
            # Check if it's a CVMFS module (not local)
            if ! /usr/share/lmod/lmod/libexec/lmod bash avail "$wrapped_module_name" 2>&1 | grep -q "local/containers"; then
                echo "📋 Module $wrapped_module_name configured (CVMFS)"
                echo "ℹ  Note: First command execution will download container (~1-2 min)"
            else
                echo "⚡ Loading $wrapped_module_name (local)"
            fi
        fi
        
        # Call original lmod command directly
        eval "$($LMOD_CMD bash "$cmd" "$@")" && eval $(${LMOD_SETTARG_CMD:-:} -s sh)
        wrapped_exit_code=$?
        
        if [ "$cmd" = "load" ] && [ "$wrapped_exit_code" -eq 0 ]; then
            echo "✅ $wrapped_module_name ready"
        fi
        
        return "$wrapped_exit_code"
    }
fi

# Auto-cleanup CVMFS cache if needed (monthly check)
cleanup_cache_if_needed() {
    cache_marker="$HOME/.neurodesk_cache_check"
    current_month=$(date +%Y-%m)
    
    # Check if we've cleaned this month
    if [ -f "$cache_marker" ]; then
        cleanup_last_cleanup=$(cat "$cache_marker" 2>/dev/null)
        if [ "$cleanup_last_cleanup" = "$current_month" ]; then
            return 0  # Already cleaned this month
        fi
    fi
    
    # Check cache size and clean if needed
    if command -v cvmfs_config >/dev/null 2>&1; then
        cleanup_cache_usage=$(cvmfs_config stat neurodesk.ardc.edu.au 2>/dev/null | grep "Cache Usage" | sed 's/.*: *\([0-9]*\)k.*/\1/')
        
        # Clean if cache is > 2GB (2048000k)
        if [ -n "$cleanup_cache_usage" ] && [ "$cleanup_cache_usage" -gt 2048000 ]; then
            echo "🧹 CVMFS cache large (${cleanup_cache_usage}k) - cleaning old files..."
            
            # Simple cleanup: reload CVMFS to trigger auto-cleanup
            cvmfs_config reload neurodesk.ardc.edu.au >/dev/null 2>&1
            
            echo "✅ Cache cleanup completed"
        fi
    fi
    
    # Mark as cleaned this month
    echo "$current_month" > "$cache_marker"
    unset cache_marker current_month cleanup_last_cleanup cleanup_cache_usage
}

# Silent by default with cache info and auto-cleanup
if [ "${NEURODESK_QUIET:-0}" != "1" ]; then
    echo "✓ Neurodesk modules ready (use 'module avail' to list tools)"
    
    # Show cache size if available
    if command -v cvmfs_config >/dev/null 2>&1; then
        cache_info=$(cvmfs_config stat neurodesk.ardc.edu.au 2>/dev/null | grep "Cache Usage" | cut -d: -f2)
        if [ -n "$cache_info" ]; then
            echo "📊 CVMFS cache:$cache_info"
        fi
        
        # Run cleanup check in background to avoid slowing startup
        cleanup_cache_if_needed &
    fi
fi
