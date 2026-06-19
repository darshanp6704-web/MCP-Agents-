import os
import json
import hashlib
import logging
from typing import List
from openai import OpenAI

logger = logging.getLogger(__name__)

def get_embedding_cache_dir() -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cache_dir = os.path.join(base_dir, "data", "cache", "embeddings")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir

def get_cache_key(text: str, rating: int) -> str:
    """Computes a unique sha256 hash for caching an embedding."""
    input_str = f"{rating}:{text}"
    return hashlib.sha256(input_str.encode("utf-8")).hexdigest()

def load_cached_embedding(key: str) -> List[float]:
    cache_path = os.path.join(get_embedding_cache_dir(), f"{key}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def save_cached_embedding(key: str, embedding: List[float]) -> None:
    cache_path = os.path.join(get_embedding_cache_dir(), f"{key}.json")
    try:
        with open(cache_path, "w") as f:
            json.dump(embedding, f)
    except Exception as e:
        logger.warning(f"Failed to cache embedding for key {key}: {e}")

def get_embeddings(
    texts: List[str],
    ratings: List[int],
    provider: str = "openai",
    model: str = "text-embedding-3-small",
    batch_size: int = 64
) -> List[List[float]]:
    """
    Fetches embeddings for a list of texts and ratings using either OpenAI or local sentence-transformers.
    Uses file-based caching based on sha256(scrubbed_text + rating) to minimize API/local model usage.
    """
    if not texts:
        return []
        
    embeddings: List[List[float]] = [None] * len(texts)
    to_embed_indices: List[int] = []
    to_embed_texts: List[str] = []
    cache_keys = [get_cache_key(t, r) for t, r in zip(texts, ratings)]

    # 1. Check cache first
    for i, key in enumerate(cache_keys):
        cached = load_cached_embedding(key)
        if cached is not None:
            embeddings[i] = cached
        else:
            to_embed_indices.append(i)
            to_embed_texts.append(texts[i])

    if to_embed_texts:
        logger.info(f"Embedding cache miss: Fetching {len(to_embed_texts)} of {len(texts)} embeddings using provider '{provider}' and model '{model}'.")
        
        if provider == "openai":
            client = OpenAI()  # Automatically picks up OPENAI_API_KEY from environment
            # Batch requests
            for batch_start in range(0, len(to_embed_texts), batch_size):
                batch_end = min(batch_start + batch_size, len(to_embed_texts))
                batch_slice = to_embed_texts[batch_start:batch_end]
                indices_slice = to_embed_indices[batch_start:batch_end]
                keys_slice = cache_keys[batch_start:batch_end]

                try:
                    response = client.embeddings.create(
                        input=batch_slice,
                        model=model
                    )
                    for res, idx, key in zip(response.data, indices_slice, keys_slice):
                        vector = res.embedding
                        embeddings[idx] = vector
                        save_cached_embedding(key, vector)
                except Exception as e:
                    logger.error(f"Error fetching embeddings from OpenAI: {e}")
                    raise e
        elif provider == "local" or "bge" in model.lower():
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as ie:
                logger.error("sentence-transformers package is not installed. Please run: pip install sentence-transformers")
                raise ie

            logger.info(f"Loading local SentenceTransformer model '{model}'...")
            encoder = SentenceTransformer(model)

            # Batch requests
            for batch_start in range(0, len(to_embed_texts), batch_size):
                batch_end = min(batch_start + batch_size, len(to_embed_texts))
                batch_slice = to_embed_texts[batch_start:batch_end]
                indices_slice = to_embed_indices[batch_start:batch_end]
                keys_slice = cache_keys[batch_start:batch_end]

                try:
                    vectors = encoder.encode(batch_slice, normalize_embeddings=True)
                    for vector, idx, key in zip(vectors, indices_slice, keys_slice):
                        vector_list = vector.tolist()
                        embeddings[idx] = vector_list
                        save_cached_embedding(key, vector_list)
                except Exception as e:
                    logger.error(f"Error generating local embeddings: {e}")
                    raise e
        else:
            raise ValueError(f"Unknown embedding provider: {provider}")
    else:
        logger.info(f"All {len(texts)} embeddings loaded successfully from cache.")

    return embeddings
