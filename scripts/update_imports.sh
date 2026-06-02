#!/bin/bash
# Script to update imports from old to new locations

echo "Updating imports across the codebase..."

# Update utils imports
find . -name "*.py" -type f -exec sed -i 's/from utils\./from brain_researcher.core.utils./g' {} +
find . -name "*.py" -type f -exec sed -i 's/import utils/import brain_researcher.core.utils as utils/g' {} +

# Update knowledge imports
find . -name "*.py" -type f -exec sed -i 's/from knowledge\./from brain_researcher.core.kg./g' {} +
find . -name "*.py" -type f -exec sed -i 's/import knowledge/import brain_researcher.core.kg as knowledge/g' {} +

# Update data_ingestion imports
find . -name "*.py" -type f -exec sed -i 's/from data_ingestion\./from brain_researcher.core.ingestion./g' {} +
find . -name "*.py" -type f -exec sed -i 's/import data_ingestion/import brain_researcher.core.ingestion as data_ingestion/g' {} +

# Update tools imports
find . -name "*.py" -type f -exec sed -i 's/from tools\./from brain_researcher.core.analysis./g' {} +
find . -name "*.py" -type f -exec sed -i 's/import tools/import brain_researcher.core.analysis as tools/g' {} +

# Update models imports
find . -name "*.py" -type f -exec sed -i 's/from models\./from brain_researcher.models./g' {} +
find . -name "*.py" -type f -exec sed -i 's/import models/import brain_researcher.models as models/g' {} +

# Update semantics imports
find . -name "*.py" -type f -exec sed -i 's/from semantics\./from brain_researcher.semantics./g' {} +
find . -name "*.py" -type f -exec sed -i 's/import semantics/import brain_researcher.semantics as semantics/g' {} +

echo "Import updates completed!"
