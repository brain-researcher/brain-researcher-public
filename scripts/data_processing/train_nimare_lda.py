import pathlib

from nimare.dataset import Dataset
from nimare.extract import download_neurosynth
from sklearn.decomposition import LatentDirichletAllocation
from sklearn.feature_extraction.text import CountVectorizer

# Download Neurosynth data (if not already present)
dset_file = download_neurosynth(path="data/neurosynth")
dset = Dataset(dset_file)


# import pdb; pdb.set_trace()

# Fit 12-topic LDA model
vectorizer = CountVectorizer()
X = vectorizer.fit_transform(dset.texts)
lda = LatentDirichletAllocation(n_components=12)
lda.fit(X)

# Save model
out_f = pathlib.Path("data/nimare_topics/neurosynth_12topics_lda.pkl")
out_f.parent.mkdir(parents=True, exist_ok=True)
lda.save(out_f)
print(f"Saved LDA model to {out_f}")
