import json
import pathlib

import numpy as np

# ---------- CONFIG ----------
ANNOT_DIR = pathlib.Path(
    "llm_cogitive_function/data/processed"
)  # Annotation files directory
VOCAB = pathlib.Path("data/vocab/ca_topics_level0.json")  # Master vocab
VEC_ROOT = pathlib.Path("llm_cogitive_function/data/vectors")  # Output directory
CONF_THRESHOLD = 0.0  # Confidence threshold
# ----------------------------

# 1) Load master vocab, build id->name mapping and id set
with open(VOCAB) as f:
    vocab_list = json.load(f)
vocab_ids = set([c["id"] for c in vocab_list])
id2col = {c["id"]: i for i, c in enumerate(vocab_list)}
D = len(vocab_list)

# 2) Batch process all annotation files
for ann_path in ANNOT_DIR.glob("*_annotations.json"):
    dataset_name = ann_path.stem.replace("_annotations", "")
    outdir = VEC_ROOT / dataset_name
    print(f"Processing {ann_path} → {outdir}")

    with open(ann_path) as f:
        contrasts = json.load(f)

    rows, labels = [], []
    unknown_ids = set()
    for block in contrasts:
        vec = np.zeros(D, dtype=np.float32)
        for c in block["constructs"]:
            cid = c["id"]
            if c["confidence"] < CONF_THRESHOLD:
                continue
            if cid in vocab_ids:
                vec[id2col[cid]] = c["confidence"]  # Use 1.0 for binary
            else:
                unknown_ids.add(cid)
        rows.append(vec)
        labels.append(block["contrast_name"])

    X = np.stack(rows)
    outdir.mkdir(parents=True, exist_ok=True)
    np.save(outdir / "X.npy", X)
    with open(outdir / "index.json", "w") as f:
        json.dump(labels, f, indent=2)

    # Record all illegal ids
    if unknown_ids:
        with open(outdir / "unknown_ids.txt", "w") as f:
            for uid in sorted(unknown_ids):
                f.write(uid + "\n")
        print(
            f"  [Warning] {len(unknown_ids)} unknown ids found, saved to {outdir/'unknown_ids.txt'}"
        )
    else:
        print("  All ids valid.")

print("All datasets processed.")
