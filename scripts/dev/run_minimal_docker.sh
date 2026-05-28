#!/bin/bash
# Minimal Docker test - tests basic Docker functionality without full project

echo "====================================="
echo "Minimal Docker Test"
echo "====================================="
echo ""

# 1. Build minimal image
echo "1. Building minimal Docker image..."
docker build -f Dockerfile.simple -t brain-researcher-minimal . || exit 1

# 2. Test container runs
echo ""
echo "2. Testing container runs..."
docker run --rm brain-researcher-minimal

# 3. Test Python works
echo ""
echo "3. Testing Python in container..."
docker run --rm brain-researcher-minimal python --version

# 4. Test pip list
echo ""
echo "4. Checking installed packages..."
docker run --rm brain-researcher-minimal pip list | grep -E "(pip|setuptools|wheel)" | head -5

# 5. Interactive Python test
echo ""
echo "5. Testing Python imports..."
docker run --rm brain-researcher-minimal python -c "print('Python works in container!')"

echo ""
echo "====================================="
echo "Minimal test complete!"
echo ""
echo "If this works, the issue is with missing project files."
echo "If this fails, Docker itself has issues."
echo "====================================="
