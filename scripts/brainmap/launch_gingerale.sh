#!/bin/bash

# GingerALE Launcher Script
# GingerALE: perform meta-analyses on coordinate-based data

echo "=== BrainMap GingerALE ==="
echo "GingerALE performs coordinate-based meta-analyses using the"
echo "Activation Likelihood Estimation (ALE) method."
echo ""

# Check if Java is available - use multiple methods
JAVA_CMD=""
if command -v java &> /dev/null; then
    JAVA_CMD="java"
elif [ -f "/usr/bin/java" ]; then
    JAVA_CMD="/usr/bin/java"
elif [ -f "/usr/lib/jvm/java-11-openjdk-amd64/bin/java" ]; then
    JAVA_CMD="/usr/lib/jvm/java-11-openjdk-amd64/bin/java"
else
    echo "❌ Error: Java is not installed or not in PATH"
    echo "Please install Java to run BrainMap software"
    exit 1
fi

echo "✅ Found Java: $JAVA_CMD"
echo "Java version: $($JAVA_CMD -version 2>&1 | head -1)"

# Get the project root directory
PROJECT_ROOT="/data/ECoG-foundation-model/mnndl_temp/brain_researcher"
BRAINMAP_DIR="$PROJECT_ROOT/external/brainmap"

# Check if GingerALE.jar exists
if [ ! -f "$BRAINMAP_DIR/GingerALE.jar" ]; then
    echo "❌ Error: GingerALE.jar not found at $BRAINMAP_DIR/GingerALE.jar"
    echo "Please ensure BrainMap software is properly installed"
    exit 1
fi

# Launch GingerALE with proper memory settings
echo "🚀 Launching GingerALE..."
echo "JAR location: $BRAINMAP_DIR/GingerALE.jar"
$JAVA_CMD -Xmx4g -Xms1g -jar "$BRAINMAP_DIR/GingerALE.jar" 