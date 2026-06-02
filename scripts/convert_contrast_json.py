import json

with open("llm_cogitive_function/data/contrast_paper_information_openeuro.json") as f:
    data = json.load(f)

out = {}
for task in data:
    task_name = task["task_name"]
    excerpt = task.get("paper_excerpt", "")
    out[task_name] = {}
    for c in task["contrast_list"]:
        contrast_name = c["contrast_name"]
        out[task_name][contrast_name] = {
            "task_name": task_name,
            "contrast": c["expression"],
            "excerpt": excerpt,
        }

with open(
    "llm_cogitive_function/data/contrast_paper_information_openeuro_dict.json", "w"
) as f:
    json.dump(out, f, indent=2)
