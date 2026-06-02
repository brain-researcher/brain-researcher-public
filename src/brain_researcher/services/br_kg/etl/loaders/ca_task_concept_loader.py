import csv
from pathlib import Path

DEFAULT_PATH = Path("data/ca_task_concept_weights.tsv")


def load_task_concept_weights(
    tsv_path: Path = DEFAULT_PATH,
) -> dict[str, dict[str, float]]:
    """Load Cognitive Atlas task→concept weights from TSV.

    Parameters
    ----------
    tsv_path : Path
        Path to TSV file with columns ``task``, ``concept`` and ``weight``.

    Returns
    -------
    Dict[str, Dict[str, float]]
        Mapping from lowercased task label to a mapping of lowercased concept
        name to weight.
    """
    weights: dict[str, dict[str, float]] = {}
    if not Path(tsv_path).exists():
        return weights

    with open(tsv_path, newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            task = row.get("task", "").lower()
            concept = row.get("concept", "").lower()
            try:
                w = float(row.get("weight", 0))
            except ValueError:
                w = 0.0
            if task and concept:
                weights.setdefault(task, {})[concept] = w
    return weights
