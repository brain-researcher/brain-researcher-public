#!/bin/bash

# Change to br-kg directory
cd "$(dirname "$0")/.."

# Increase system limits
echo "Setting up system limits..."
sudo sysctl -w vm.max_map_count=262144
sudo sysctl -w fs.file-max=65536
sudo sysctl -w vm.swappiness=10

# Create limits configuration file
sudo tee /etc/security/limits.d/br-kg.conf << EOF
*               soft    nofile          65536
*               hard    nofile          65536
*               soft    nproc           65536
*               hard    nproc           65536
*               soft    memlock         unlimited
*               hard    memlock         unlimited
EOF

# Set up large temporary directory for database operations
echo "Setting up temporary directory..."
mkdir -p /tmp/br-kg_temp
chmod 777 /tmp/br-kg_temp
export TMPDIR=/tmp/br-kg_temp

# Configure Python environment
echo "Configuring Python environment..."
# Install python3-full if not already installed
if ! dpkg -l | grep -q python3-full; then
    sudo apt-get update
    sudo apt-get install -y python3-full
fi

# Create and activate virtual environment
echo "Creating virtual environment..."
python3 -m venv br_kg_env
source br_kg_env/bin/activate

# Install required packages in virtual environment
echo "Installing required packages..."
pip install --upgrade pip
pip install psutil memory_profiler

# Create directories for database files
echo "Setting up database directories..."
mkdir -p data/br-kg/{db,index,cache,logs}
chmod -R 777 data/br-kg

echo "System configuration completed."
echo "To activate the environment, use: source br_kg_env/bin/activate"
