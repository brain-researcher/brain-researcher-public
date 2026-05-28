import base64
from io import BytesIO
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

PRUNED = Path("pruned_candidates.csv")
SCORED = Path("scored_candidates.csv")
OUT = Path("qa_ensemble.html")


def main():
    if not PRUNED.exists():
        print("No pruned_candidates.csv found")
        return
    df = pd.read_csv(PRUNED)
    full = pd.read_csv(SCORED) if SCORED.exists() else df

    # Histogram
    fig, ax = plt.subplots()
    df["overall_confidence"].hist(bins=20, ax=ax)
    ax.set_xlabel("overall_confidence")
    buf = BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    img = base64.b64encode(buf.getvalue()).decode("utf-8")

    kept_pct = len(df) / len(full) * 100 if len(full) else 0
    low = df[(df["overall_confidence"] >= 0.5) & (df["overall_confidence"] < 0.55)]
    low_pct = len(low) / len(df) * 100 if len(df) else 0
    sample = df.sample(n=min(50, len(df)), random_state=42)

    html = f"""
    <html><body>
    <h1>Ensemble QA Report</h1>
    <p>{kept_pct:.1f}% candidates retained.</p>
    <p>{low_pct:.2f}% low-confidence edges (0.5–0.55).</p>
    <img src='data:image/png;base64,{img}' />
    {sample.to_html(index=False)}
    </body></html>
    """
    with open(OUT, "w") as f:
        f.write(html)


if __name__ == "__main__":
    main()
