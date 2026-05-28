"""
NICLIP Service Client

Client library for interacting with the NICLIP Prediction Service API.
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)


class NICLIPClient:
    """Client for NICLIP Prediction Service API"""

    def __init__(self, base_url: str = "http://localhost:8001", timeout: int = 30):
        """
        Initialize NICLIP client.

        Args:
            base_url: Base URL of NICLIP service
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def health_check(self) -> dict:
        """Check service health"""
        response = self.session.get(f"{self.base_url}/health", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def predict_cognitive_processes(
        self, nifti_path: str | Path, top_k: int = 10, use_bayes: bool = True
    ) -> pd.DataFrame:
        """
        Predict cognitive processes from brain image.

        Args:
            nifti_path: Path to NIfTI file
            top_k: Number of top predictions
            use_bayes: Use Bayesian inference

        Returns:
            DataFrame with predictions
        """
        data = {"nifti_path": str(nifti_path), "top_k": top_k, "use_bayes": use_bayes}

        response = self.session.post(
            f"{self.base_url}/predict", json=data, timeout=self.timeout
        )
        response.raise_for_status()

        result = response.json()
        return pd.DataFrame(result["predictions"])

    def compute_similarity(self, nifti_path: str | Path, text: str) -> float:
        """
        Compute similarity between brain image and text.

        Args:
            nifti_path: Path to NIfTI file
            text: Text to compare

        Returns:
            Cosine similarity score
        """
        data = {"nifti_path": str(nifti_path), "text": text}

        response = self.session.post(
            f"{self.base_url}/similarity", json=data, timeout=self.timeout
        )
        response.raise_for_status()

        return response.json()["similarity"]

    def encode_text(self, text: str | list[str]) -> np.ndarray:
        """
        Encode text into embeddings.

        Args:
            text: Text or list of texts

        Returns:
            Embeddings array
        """
        data = {"text": text}

        response = self.session.post(
            f"{self.base_url}/encode", json=data, timeout=self.timeout
        )
        response.raise_for_status()

        result = response.json()
        return np.array(result["embeddings"])

    def search_similar_concepts(
        self, query: str, vocabulary_type: str = "cogatlas_task-names", top_k: int = 5
    ) -> list[dict[str, str | float]]:
        """
        Search for similar cognitive concepts.

        Args:
            query: Query term
            vocabulary_type: Vocabulary to search
            top_k: Number of results

        Returns:
            List of similar items with scores
        """
        data = {"query": query, "vocabulary_type": vocabulary_type, "top_k": top_k}

        response = self.session.post(
            f"{self.base_url}/search", json=data, timeout=self.timeout
        )
        response.raise_for_status()

        result = response.json()
        return result["similar_items"]

    def analyze_uploaded_file(
        self, file_path: str | Path, top_k: int = 10, use_bayes: bool = True
    ) -> dict:
        """
        Analyze an uploaded NIfTI file.

        Args:
            file_path: Path to NIfTI file to upload
            top_k: Number of top predictions
            use_bayes: Use Bayesian inference

        Returns:
            Analysis results
        """
        file_path = Path(file_path)

        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, "application/octet-stream")}
            params = {"top_k": top_k, "use_bayes": use_bayes}

            response = self.session.post(
                f"{self.base_url}/analyze",
                files=files,
                params=params,
                timeout=self.timeout,
            )

        response.raise_for_status()
        return response.json()

    def get_model_info(self) -> dict:
        """Get current model information"""
        response = self.session.get(f"{self.base_url}/model", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def update_model_config(
        self,
        model_path: str | None = None,
        model_name: str = "BrainGPT-7B-v0.2",
        section: str = "abstract",
        device: str | None = None,
    ) -> dict:
        """
        Update model configuration.

        Args:
            model_path: Path to model checkpoint
            model_name: Model name
            section: Section to use
            device: Device (cuda, cpu, mps)

        Returns:
            Update status
        """
        data = {
            "model_path": model_path,
            "model_name": model_name,
            "section": section,
            "device": device,
        }

        response = self.session.post(
            f"{self.base_url}/model", json=data, timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def list_vocabularies(self) -> list[dict]:
        """List available vocabularies"""
        response = self.session.get(
            f"{self.base_url}/vocabularies", timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()["vocabularies"]

    def close(self):
        """Close the session"""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Example usage
if __name__ == "__main__":
    # Initialize client
    client = NICLIPClient()

    try:
        # Check health
        health = client.health_check()
        print(f"Service status: {health['status']}")

        # Get model info
        model_info = client.get_model_info()
        print(f"Model: {model_info['model_name']}")
        print(f"Vocabulary size: {model_info['vocabulary_size']}")

        # Search for similar concepts
        similar = client.search_similar_concepts("working memory", top_k=3)
        print("\nSimilar concepts to 'working memory':")
        for item in similar:
            print(f"  - {item['item']} (similarity: {item['similarity']:.3f})")

        # Encode text
        embedding = client.encode_text("motor cortex")
        print(f"\nText embedding shape: {embedding.shape}")

    finally:
        client.close()
