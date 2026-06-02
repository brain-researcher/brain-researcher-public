# BR-KG Scripts

This directory contains utility scripts for managing the BR-KG database and API.

## Scripts Overview

### Database Management

#### `init_database.py`
Initializes the BR-KG database with proper schema and optionally loads data from various sources.
This script now requires Neo4j and will error if the legacy SQLite backend is requested.

```bash
# Initialize with sample data (dry run)
python scripts/init_database.py --dry-run

# Initialize and load full database
python scripts/init_database.py --full

# Clean existing database and start fresh
python scripts/init_database.py --clean --full

# Resume loading from where it left off
python scripts/init_database.py --resume
```

#### `optimize_db.py`
Optimizes the database by creating indexes and analyzing query patterns.
Deprecated for Neo4j; use `br db init` or `scripts/br-kg/setup_neo4j_schema.py` instead.

```bash
python scripts/optimize_db.py
```

#### `setup_large_db.sh`
Configures system settings for handling large databases.

```bash
./scripts/br-kg/setup_large_db.sh
```

### API Management

#### `run_api.sh`
Starts the Flask Graph API server.

```bash
# Start with default database
./scripts/br-kg/run_api.sh
```

## Usage Notes

All scripts should be run from the main `br-kg` directory, not from within the `scripts` folder. The scripts automatically handle path resolution.

Example:
```bash
cd /path/to/br-kg
python scripts/init_database.py --dry-run
./scripts/br-kg/run_api.sh
```
