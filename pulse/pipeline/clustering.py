import numpy as np
import logging
from typing import List, Dict, Any, Tuple
from pulse.ingestion.models import Review

logger = logging.getLogger(__name__)

# Try to import UMAP and HDBSCAN, fallback if unavailable
try:
    import umap
    HAS_UMAP = True
except ImportError:
    logger.warning("umap-learn not installed. Fallback to basic clustering will be used if needed.")
    HAS_UMAP = False

try:
    from sklearn.cluster import HDBSCAN
    HAS_HDBSCAN = True
except ImportError:
    try:
        import hdbscan
        HAS_HDBSCAN = True
    except ImportError:
        logger.warning("hdbscan/sklearn HDBSCAN not installed. Fallback to basic clustering will be used if needed.")
        HAS_HDBSCAN = False

def calculate_medoid(embeddings: np.ndarray, indices: List[int]) -> int:
    """Finds the index of the review closest to the centroid of the cluster (medoid)."""
    if len(indices) == 1:
        return indices[0]
        
    cluster_embeddings = embeddings[indices]
    centroid = np.mean(cluster_embeddings, axis=0)
    
    # Calculate distance of each point to the centroid
    distances = np.linalg.norm(cluster_embeddings - centroid, axis=1)
    min_idx = np.argmin(distances)
    return indices[min_idx]

def get_representative_reviews(
    reviews: List[Review],
    embeddings: np.ndarray,
    indices: List[int],
    max_samples: int = 8
) -> List[Review]:
    """
    Selects 5-8 representative reviews for a cluster.
    Includes the medoid and a diverse set of reviews.
    """
    if len(indices) <= max_samples:
        return [reviews[idx] for idx in indices]

    medoid_idx = calculate_medoid(embeddings, indices)
    selected_indices = [medoid_idx]
    
    # Get remaining indices
    remaining = [idx for idx in indices if idx != medoid_idx]
    
    # Sort remaining by length of text to prioritize detailed reviews
    remaining.sort(key=lambda idx: len(reviews[idx].text), reverse=True)
    
    # Greedily select reviews to fill the sample list
    for idx in remaining:
        if len(selected_indices) >= max_samples:
            break
        selected_indices.append(idx)
        
    return [reviews[idx] for idx in selected_indices]

def run_clustering(
    reviews: List[Review],
    embeddings_list: List[List[float]],
    config: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Runs dimensionality reduction (UMAP) and clustering (HDBSCAN) on review embeddings.
    Groups reviews into clusters, ranks them by priority score, and handles edge fallbacks.
    
    Returns a list of cluster dicts:
    [
      {
        "cluster_id": int,
        "score": float,
        "reviews": List[Review],
        "samples": List[Review],
        "avg_rating": float,
        "size": int
      }
    ]
    """
    embeddings = np.array(embeddings_list)
    num_reviews = len(reviews)
    
    # ML Floor: check minimum review counts
    if num_reviews < 20:
        raise ValueError(f"Normalized review count {num_reviews} is below the ML floor of 20. Aborting.")

    cluster_config = config.get("clustering", {})
    umap_cfg = cluster_config.get("umap", {})
    hdb_cfg = cluster_config.get("hdbscan", {})

    labels = np.zeros(num_reviews, dtype=int) - 1 # Default all to noise (-1)
    
    # Run UMAP and HDBSCAN if libraries are available
    if HAS_UMAP and HAS_HDBSCAN:
        try:
            # 1. Dimensionality Reduction using UMAP
            n_comp = umap_cfg.get("n_components", 5)
            # Ensure n_neighbors is smaller than data size
            n_neigh = min(umap_cfg.get("n_neighbors", 15), num_reviews - 1)
            
            reducer = umap.UMAP(
                n_neighbors=n_neigh,
                n_components=n_comp,
                metric=umap_cfg.get("metric", "cosine"),
                random_state=umap_cfg.get("random_state", 42)
            )
            reduced_embeddings = reducer.fit_transform(embeddings)

            # 2. Density Clustering using HDBSCAN
            min_size = hdb_cfg.get("min_cluster_size", 5)
            min_samp = hdb_cfg.get("min_samples", 3)
            
            try:
                # Try sklearn HDBSCAN
                from sklearn.cluster import HDBSCAN as SKHDBSCAN
                clusterer = SKHDBSCAN(
                    min_cluster_size=min_size,
                    min_samples=min_samp
                )
                labels = clusterer.fit_predict(reduced_embeddings)
            except Exception:
                # Try hdbscan package
                import hdbscan as raw_hdbscan
                clusterer = raw_hdbscan.HDBSCAN(
                    min_cluster_size=min_size,
                    min_samples=min_samp
                )
                labels = clusterer.fit_predict(reduced_embeddings)
                
        except Exception as e:
            logger.warning(f"Clustering algorithm failed: {e}. Falling back to rule-based fallback.")
            labels = np.zeros(num_reviews, dtype=int) - 1
    else:
        logger.info("UMAP or HDBSCAN missing. Falling back to rule-based fallback.")

    # 3. Handle Edge Cases and Fallbacks
    unique_labels = set(labels)
    
    # Fallback Case 1: All noise (-1) or only one cluster (and all others noise)
    if (len(unique_labels) == 1 and -1 in unique_labels) or (len(unique_labels) == 2 and -1 in unique_labels and len(reviews) > 30):
        logger.info("All noise detected or insufficient clusters. Lowering min_cluster_size for fallback.")
        # Try to cluster based on ratings as a fallback
        labels = np.array([r.rating for r in reviews]) # Group directly by star ratings (1,2,3,4,5)
        unique_labels = set(labels)

    # 4. Group Reviews by Cluster Label
    raw_clusters_map: Dict[int, List[int]] = {}
    for idx, label in enumerate(labels):
        if label not in raw_clusters_map:
            raw_clusters_map[label] = []
        raw_clusters_map[label].append(idx)

    # Split mixed-sentiment clusters to isolate praise from complaints
    final_clusters: List[Tuple[int, List[int]]] = []
    next_subcluster_id = 10000  # Start ID for split sub-clusters to avoid collision

    for label, indices in raw_clusters_map.items():
        # Keep noise cluster (-1) as is for now
        if label == -1 and len(raw_clusters_map) > 1:
            final_clusters.append((label, indices))
            continue

        cluster_reviews = [reviews[idx] for idx in indices]
        ratings = [r.rating for r in cluster_reviews]
        
        should_split = False
        if len(ratings) > 1:
            std_rating = np.std(ratings)
            has_pos = any(r >= 4 for r in ratings)
            has_neg = any(r <= 2 for r in ratings)
            if std_rating > 1.0 and has_pos and has_neg:
                should_split = True

        if should_split:
            pos_indices = [idx for idx in indices if reviews[idx].rating >= 4]
            neg_indices = [idx for idx in indices if reviews[idx].rating <= 3]
            
            logger.info(
                f"Splitting mixed-sentiment cluster {label} (size {len(indices)}, std_rating {np.std(ratings):.2f}) "
                f"into positive (size {len(pos_indices)}) and negative/neutral (size {len(neg_indices)}) sub-clusters."
            )
            
            if pos_indices:
                final_clusters.append((next_subcluster_id, pos_indices))
                next_subcluster_id += 1
            if neg_indices:
                final_clusters.append((next_subcluster_id, neg_indices))
                next_subcluster_id += 1
        else:
            final_clusters.append((label, indices))

    # 5. Build, Score, and Rank Clusters
    ranked_clusters: List[Dict[str, Any]] = []
    max_samples = config.get("summarization", {}).get("max_samples_per_cluster", 8)

    for label, indices in final_clusters:
        # Exclude noise cluster (-1) from main theme generation unless there is nothing else
        if label == -1 and len(raw_clusters_map) > 1:
            continue
            
        cluster_reviews = [reviews[idx] for idx in indices]
        ratings = [r.rating for r in cluster_reviews]
        avg_rating = sum(ratings) / len(ratings)
        size = len(cluster_reviews)
        
        # Rank Score: size * (6 - average_rating)
        # Prioritizes large clusters with low-star ratings (complaints/bugs)
        score = size * (6.0 - avg_rating)
        
        samples = get_representative_reviews(reviews, embeddings, indices, max_samples)

        ranked_clusters.append({
            "cluster_id": int(label),
            "score": score,
            "reviews": cluster_reviews,
            "samples": samples,
            "avg_rating": avg_rating,
            "size": size
        })

    # Sort descending by priority score
    ranked_clusters.sort(key=lambda c: c["score"], reverse=True)
    logger.info(f"Generated and ranked {len(ranked_clusters)} clusters (excluding noise).")
    
    return ranked_clusters
