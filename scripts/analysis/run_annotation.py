import os
import sys

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, project_root)

from brain_researcher.core.analysis.contrast_annotation import annotate_dataset

results = annotate_dataset(
    contrasts_json="llm_cogitive_function/data/contrast_paper_information_openeuro_dict.json",
    vocab_json="data/vocab/ca_topics_level0.json",
    n_passes=5,
    model="deepseek-reasoner",
    temperature=0.7,
    parallel=True,
    max_workers=8,
)

print("Annotation finished! Example result:")
print(results[0] if results else "No results.")
