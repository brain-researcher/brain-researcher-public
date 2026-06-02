FROM docker.io/zjc062/agent:20260324221455-agent-psych101-workflow-parity

# Keep the patch image minimal: only bake in the agent tool-surface changes
# needed for public behavior-to-fMRI retrieval exposure.
COPY src/brain_researcher/services/tools/br_kg_tools.py /app/src/brain_researcher/services/tools/br_kg_tools.py
COPY configs/catalog/chat_tools.yaml /app/configs/catalog/chat_tools.yaml
