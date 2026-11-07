import math
import hashlib
import logging
from typing import List, Optional
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Embedding Service supporting local Ollama (bge-m3 / 1024-dim)
    with automatic batching and fallback for offline/test environments.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: float = 30.0,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.EMBEDDING_MODEL
        self.timeout = timeout_seconds
        self.dimension = 1024

    def _fallback_embedding(self, text: str) -> List[float]:
        """
        Deterministic unit vector generator (1024 dimensions) for test/offline environments
        when Ollama model is not yet pulled or temporarily unreachable.
        Uses token feature hashing so that overlapping vocabulary produces genuine cosine similarity.
        """
        import re

        floats = [0.0] * self.dimension

        # 1. Base smooth curve from full text hash to ensure dense vector
        seed = hashlib.sha256(text.encode("utf-8")).digest()
        for i in range(self.dimension):
            b = seed[i % len(seed)]
            floats[i] += 0.05 * math.sin(b + i * 0.1)

        # 2. Token-level feature hashing (bag-of-words + character n-grams)
        tokens = re.findall(r"\w+", text.lower(), re.UNICODE)
        for token in tokens:
            thash = hashlib.md5(token.encode("utf-8")).digest()
            idx = int.from_bytes(thash[:2], "big") % self.dimension
            sign = 1.0 if (thash[2] % 2 == 0) else -1.0
            floats[idx] += 1.0 * sign

            if len(token) > 3:
                for j in range(len(token) - 2):
                    ngram = token[j : j + 3]
                    nhash = hashlib.md5(ngram.encode("utf-8")).digest()
                    nidx = int.from_bytes(nhash[:2], "big") % self.dimension
                    nsign = 1.0 if (nhash[2] % 2 == 0) else -1.0
                    floats[nidx] += 0.3 * nsign

        # 3. L2 Normalize
        norm = math.sqrt(sum(x * x for x in floats)) or 1.0
        return [round(x / norm, 6) for x in floats]

    def embed_text(self, text: str) -> List[float]:
        """Generate embedding vector for a single string."""
        results = self.embed_batch([text])
        return results[0]

    def embed_batch(
        self,
        texts: List[str],
        batch_size: int = 16,
    ) -> List[List[float]]:
        """
        Generate embedding vectors for a list of strings in batches.
        Uses Ollama /api/embed if available, otherwise falls back gracefully.
        """
        if not texts:
            return []

        all_embeddings: List[List[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_embeddings = self._call_ollama_embed(batch)

            if batch_embeddings and len(batch_embeddings) == len(batch):
                all_embeddings.extend(batch_embeddings)
            else:
                # Fallback to local generator for each text in batch
                logger.warning(
                    f"Ollama embedding unavailable for batch {i//batch_size}. Using local vector generator."
                )
                for txt in batch:
                    all_embeddings.append(self._fallback_embedding(txt))

        return all_embeddings

    def _call_ollama_embed(self, texts: List[str]) -> Optional[List[List[float]]]:
        """Call Ollama /api/embed endpoint with retry / timeout."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                # 1. Try modern Ollama /api/embed endpoint
                res = client.post(
                    f"{self.base_url}/api/embed",
                    json={
                        "model": self.model,
                        "input": texts,
                    },
                )
                if res.status_code == 200:
                    data = res.json()
                    embeddings = data.get("embeddings")
                    if embeddings and isinstance(embeddings, list):
                        # Ensure dimensions match expected size
                        if len(embeddings[0]) == self.dimension:
                            return embeddings

                # 2. Try legacy single /api/embeddings if /api/embed returned 404
                if res.status_code == 404 and len(texts) == 1:
                    res_leg = client.post(
                        f"{self.base_url}/api/embeddings",
                        json={
                            "model": self.model,
                            "prompt": texts[0],
                        },
                    )
                    if res_leg.status_code == 200:
                        data = res_leg.json()
                        emb = data.get("embedding")
                        if emb and len(emb) == self.dimension:
                            return [emb]

        except Exception as e:
            logger.debug(f"Ollama call failed ({e}). Reverting to fallback.")
            return None

        return None


embedding_service = EmbeddingService()
