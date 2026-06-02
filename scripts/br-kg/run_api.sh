#!/bin/bash

# Start the BR-KG Graph API

echo "Starting BR-KG Graph API..."

if [ -z "$NEO4J_URI" ]; then
    export NEO4J_URI="bolt://localhost:7687"
    echo "NEO4J_URI not set; defaulting to $NEO4J_URI"
fi

if [ -z "$NEO4J_USER" ]; then
    export NEO4J_USER="neo4j"
fi

if [ -z "$NEO4J_PASSWORD" ]; then
    echo "NEO4J_PASSWORD is not set. Please export it before starting the API."
    exit 1
fi

echo "Connecting to Neo4j at $NEO4J_URI as $NEO4J_USER"

# Change to project root directory
cd "$(dirname "$0")/../../.."

# Start the Flask API using module path
python -m services.br-kg.app
