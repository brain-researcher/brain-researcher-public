"""
One-time generator of Level-0 topic labels for every Cognitive-Atlas concept.
Requires:
  - sentence-transformers
Save output to data/vocab/ca_topics_level0.json
"""

import json
import os
import pathlib
import time

import numpy as np
import torch
import wikipedia
from Bio import Entrez
from cognitiveatlas.api import get_concept
from nimare.dataset import Dataset
from sentence_transformers import SentenceTransformer, util

# PubMed API credentials
Entrez.email = os.getenv("NCBI_ENTREZ_EMAIL") or os.getenv(
    "ENTREZ_EMAIL", "brain-researcher@example.com"
)
_entrez_api_key = os.getenv("NCBI_ENTREZ_API_KEY") or os.getenv("ENTREZ_API_KEY")
if _entrez_api_key:
    Entrez.api_key = _entrez_api_key

# Parameters
N_TOPICS = 13
TOPIC_THRESHOLD = 0.3
OUTPUT_PATH = pathlib.Path("data/vocab/ca_topics_level0_bert.json")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
NEUROSYNTH_PATH = os.path.join(
    PROJECT_ROOT, "data", "neurosynth_nimare", "neurosynth_dataset_v7.pkl"
)

MAX_PUBMED = 5
MAX_NS_ABSTRACTS = 5

# Set device for GPU acceleration
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Using device: {device}")

# 1. Load CA concepts
concepts = get_concept().json

# 2. Load Neurosynth dataset
ds = Dataset.load(NEUROSYNTH_PATH)

# 3. Build rich corpus for each concept
print("\nBuilding corpus...")
print(f"Total concepts to process: {len(concepts)}")
corpus = []
for i, c in enumerate(concepts, 1):
    print(f"\nProcessing concept {i}/{len(concepts)}: {c['name']}")
    texts = []

    # 1. CA definition & name
    texts.append(c.get("definition_text") or c["name"])
    print("  - Added definition")

    # 2. Wikipedia summary
    try:
        print("  - Fetching Wikipedia summary...")
        wiki_summary = wikipedia.summary(c["name"], sentences=2, auto_suggest=False)
        texts.append(wiki_summary)
        print("  - Added Wikipedia summary")
    except Exception as e:
        print(f"  - Wikipedia fetch failed: {str(e)}")

    # 3. Neurosynth abstracts
    try:
        print("  - Fetching Neurosynth abstracts...")
        labels = ds.get_labels()
        target = c["name"].lower().replace(" ", "_")
        matches = [l for l in labels if target in l.lower()]
        print(matches)
        if matches:
            studies = ds.get_studies_by_label(matches[0])
            abstracts = [s["abstract"] for s in studies if s.get("abstract")]
            texts += abstracts[:MAX_NS_ABSTRACTS]
            print(f"  - Added {len(abstracts[:MAX_NS_ABSTRACTS])} Neurosynth abstracts")
            import pdb

            pdb.set_trace()
        else:
            print(f"No matching label for {c['name']}")
    except Exception as e:
        print(f"  - Neurosynth fetch failed: {str(e)}")

    # 4. PubMed abstracts
    try:
        print("  - Fetching PubMed abstracts...")
        handle = Entrez.esearch(db="pubmed", term=c["name"], retmax=MAX_PUBMED)
        ids = Entrez.read(handle)["IdList"]
        if ids:
            handle = Entrez.efetch(
                db="pubmed", id=",".join(ids), rettype="abstract", retmode="text"
            )
            texts.append(handle.read())
            print(f"  - Added {len(ids)} PubMed abstracts")
        time.sleep(0.5)  # polite API usage
    except Exception as e:
        print(f"  - PubMed fetch failed: {str(e)}")

    # Merge all texts
    full_text = " ".join(texts)
    corpus.append(full_text)
    print(f"  - Total text length: {len(full_text)} characters")

# 4. Initialize sentence transformer model on GPU
model = SentenceTransformer("all-MiniLM-L6-v2", device=device)  # or "all-mpnet-base-v2"


def embed_construct(abstracts):
    """Embed a construct by averaging SBERT embeddings of all sentences in its abstracts."""
    all_sentences = []
    for abs_ in abstracts:
        all_sentences.extend([s.strip() for s in abs_.split(". ") if s.strip()])

    if not all_sentences:
        return np.zeros(model.get_sentence_embedding_dimension())

    embeddings = model.encode(
        all_sentences,
        batch_size=256,
        show_progress_bar=True,
        normalize_embeddings=True,
        device=device,
    )
    return np.mean(embeddings, axis=0)


# construct_vecs = {cid: embed_construct(abs_list) for cid, abs_list in corpus.items()}
construct_vecs = {i: embed_construct(text) for i, text in enumerate(corpus)}

# 3. Prepare topic seeds
topic_seeds = {
    "Attention": ["selective attention", "attentional control", "vigilance"],
    "Memory": ["episodic recall", "working memory maintenance", "encoding retrieval"],
    "Motor & Action": [
        "motor execution",
        "movement planning",
        "finger tapping",
        "action observation",
    ],
    "Emotion / Affective": [
        "emotion regulation",
        "affective response",
        "mood induction",
    ],
    "Reward / Decision Making": [
        "reward expectation",
        "dopaminergic value",
        "monetary incentive",
        "decision making",
    ],
    "Executive Control": ["cognitive control", "task switching", "inhibition"],
    "Language": ["semantic processing", "speech comprehension", "reading"],
    "Social / Theory of Mind": ["theory of mind", "social cognition", "empathy"],
    "Numerical / Calculation": [
        "numerical calculation",
        "arithmetic",
        "number processing",
    ],
    "Interoception / Pain": [
        "pain perception",
        "bodily awareness",
        "visceral sensation",
        "interoception",
    ],
    "Visual Perception": ["visual perception", "object recognition", "face processing"],
    "Auditory": ["auditory perception", "sound localization", "speech discrimination"],
    "Reasoning": ["logical reasoning", "problem solving", "deductive inference"],
}

topic_vecs = {
    name: np.mean(model.encode(seeds, normalize_embeddings=True, device=device), axis=0)
    for name, seeds in topic_seeds.items()
}

topic_matrix = np.stack(list(topic_vecs.values()))  # shape: (13, emb_dim)
topic_matrix_tensor = torch.tensor(topic_matrix, device=device)  # Move to GPU


# 4. Similarity & assignment
def compute_similarities_batch(construct_vecs, topic_matrix, batch_size=100):
    """Compute similarities in batches to save memory."""
    total_batches = (len(construct_vecs) + batch_size - 1) // batch_size
    print("\nStarting similarity computation...")
    print(f"Total concepts: {len(construct_vecs)}")
    print(f"Batch size: {batch_size}")
    print(f"Total batches: {total_batches}\n")

    assignments = {}
    for i in range(0, len(construct_vecs), batch_size):
        batch_num = i // batch_size + 1
        print(f"Processing batch {batch_num}/{total_batches}")

        batch_cids = list(construct_vecs.keys())[i : i + batch_size]
        batch_vecs = torch.tensor(
            [construct_vecs[cid] for cid in batch_cids], device=device
        )
        batch_sims = util.cos_sim(batch_vecs, topic_matrix_tensor).cpu().numpy()

        for j, cid in enumerate(batch_cids):
            best_idx = batch_sims[j].argmax()
            best_sim = batch_sims[j][best_idx]
            if best_sim < 0.25:
                assignments[cid] = {"domain": "Other", "score": 0.0}
            else:
                assignments[cid] = {
                    "domain": list(topic_vecs)[best_idx],
                    "score": float(best_sim),
                }

        if batch_num % 10 == 0:
            print(f"Completed {batch_num}/{total_batches} batches")

    print(f"\nFinished processing all {total_batches} batches")
    return assignments


assignments = compute_similarities_batch(construct_vecs, topic_matrix_tensor)

# 6. Assign topics to concepts
vocab = []
for c, w in assignments.items():
    domain = w["domain"]
    synonyms = [c["alias"]] if c.get("alias") else []
    vocab.append(
        {
            "id": c["id"],
            "name": c["name"],
            "synonyms": synonyms,
            "level0": domain,
            "topic_weights": w["score"],
        }
    )

# 7. Save to JSON
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH.write_text(json.dumps(vocab, indent=2))
print(f"Wrote {len(vocab)} concepts with Level-0 topics to {OUTPUT_PATH}")
