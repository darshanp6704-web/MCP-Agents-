import unittest
import sys
import os
from unittest.mock import patch

# Adjust path to import pulse module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pulse.pipeline.scrubber import scrub_pii
from pulse.pipeline.quote_validator import is_quote_in_review, normalize_whitespace_and_punctuation

class TestPulsePipeline(unittest.TestCase):
    def test_pii_scrubbing(self):
        # 1. Emails
        self.assertEqual(scrub_pii("Contact me at user@example.com"), "Contact me at [EMAIL]")
        
        # 2. Phones
        self.assertEqual(scrub_pii("Call +919876543210 immediately"), "Call [PHONE] immediately")
        self.assertEqual(scrub_pii("Number is 98765 43210"), "Number is [PHONE]")
        
        # 3. PAN / Aadhaar IDs
        self.assertEqual(scrub_pii("Aadhaar 1234-5678-9012 text"), "Aadhaar [ID] text")
        self.assertEqual(scrub_pii("PAN ABCDE1234F"), "PAN [ID]")
        self.assertEqual(scrub_pii("Card 4111222233334444 details"), "Card [ID] details")
        
        # 4. URLs
        self.assertEqual(scrub_pii("Go to https://google.com/token?q=123"), "Go to [URL]")

        # 5. Financial references (must keep)
        self.assertIn("10k", scrub_pii("I lost 10k rupees in the trade"))
        self.assertIn("lakh", scrub_pii("I invested 1 lakh last monday"))
        self.assertIn("$500", scrub_pii("It charges $500 fee"))

    def test_quote_validation(self):
        review = "This Groww app is awesome! The biometric login works super fast."
        
        # Direct match
        self.assertTrue(is_quote_in_review("biometric login works", review))
        
        # Case insensitive and punctuation ignore
        self.assertTrue(is_quote_in_review("BIOMETRIC LOGIN works...", review))
        
        # Ellipsis split matching
        self.assertTrue(is_quote_in_review("Groww app... biometric login works", review))
        
        # Sequence mismatch (should fail)
        self.assertFalse(is_quote_in_review("biometric login... Groww app", review))
        
        # Hallucination (should fail)
        self.assertFalse(is_quote_in_review("payment options are great", review))

    def test_normalizer(self):
        from pulse.ingestion.models import RawReview
        from pulse.ingestion.normalizer import normalize_review
        from datetime import datetime

        # 1. Normal English review with >= 8 words (Keep)
        raw_ok = RawReview(
            text="This is a very good and extremely clean application interface indeed.",
            rating=5,
            published_at=datetime.utcnow()
        )
        self.assertIsNotNone(normalize_review(raw_ok))

        # 2. Too short (Discard)
        raw_short = RawReview(
            text="This is a good app.",
            rating=5,
            published_at=datetime.utcnow()
        )
        self.assertIsNone(normalize_review(raw_short))

        # 3. Contains emojis (Discard)
        raw_emoji = RawReview(
            text="This is a very good and clean app interface indeed. 😊👍",
            rating=5,
            published_at=datetime.utcnow()
        )
        self.assertIsNone(normalize_review(raw_emoji))

        # 4. Regional language script check (Discard)
        raw_hindi = RawReview(
            text="यह बहुत अच्छा और साफ ऐप इंटरफ़ेस है।",
            rating=5,
            published_at=datetime.utcnow()
        )
        self.assertIsNone(normalize_review(raw_hindi))

    def test_local_embeddings(self):
        from pulse.pipeline.embeddings import get_embeddings
        texts = ["This is a test of local embeddings.", "Another short sentence here."]
        ratings = [5, 4]
        
        vectors = get_embeddings(texts, ratings, provider="local", model="BAAI/bge-small-en-v1.5")
        
        self.assertEqual(len(vectors), 2)
        self.assertEqual(len(vectors[0]), 384)
        self.assertEqual(len(vectors[1]), 384)

    def test_sentiment_cluster_splitting(self):
        from pulse.pipeline.clustering import run_clustering
        from pulse.ingestion.models import Review
        import numpy as np
        
        reviews = []
        for i in range(10):
            reviews.append(Review(text=f"Love the app interface and trade option {i}", rating=5, review_id=f"pos_{i}", published_at=None))
        for i in range(10):
            reviews.append(Review(text=f"Login failed completely crash bad support {i}", rating=1, review_id=f"neg_{i}", published_at=None))
            
        embeddings = [[0.1] * 384 for _ in range(20)]
        config = {
            "clustering": {
                "umap": {"n_neighbors": 5, "n_components": 2},
                "hdbscan": {"min_cluster_size": 2, "min_samples": 1}
            },
            "summarization": {
                "max_samples_per_cluster": 5
            }
        }
        
        with patch("pulse.pipeline.clustering.HAS_UMAP", True), \
             patch("pulse.pipeline.clustering.HAS_HDBSCAN", True), \
             patch("pulse.pipeline.clustering.umap.UMAP"), \
             patch("sklearn.cluster.HDBSCAN") as mock_hdbscan:
             
            mock_hdbscan.return_value.fit_predict.return_value = np.zeros(20, dtype=int)
            
            clusters = run_clustering(reviews, embeddings, config)
            
            self.assertEqual(len(clusters), 2)
            
            sub1 = clusters[0]
            sub2 = clusters[1]
            
            self.assertEqual(sub1["size"], 10)
            self.assertEqual(sub2["size"], 10)
            self.assertAlmostEqual(sub1["avg_rating"], 1.0)
            self.assertAlmostEqual(sub2["avg_rating"], 5.0)

    def test_groq_daily_safeguards(self):
        from pulse.pipeline.summarizer import summarize_cluster
        
        with patch("pulse.pipeline.summarizer.get_groq_client"), \
             patch("pulse.ledger.store.get_daily_llm_usage") as mock_usage:
            # 1. Daily Requests limit exceeded
            mock_usage.return_value = (5000, 1000)
            
            config = {
                "summarization": {
                    "max_tokens_per_day": 100000,
                    "max_requests_per_day": 1000,
                    "max_output_tokens_per_theme": 800
                }
            }
            
            with self.assertRaises(RuntimeError) as ctx:
                summarize_cluster(
                    cluster_id=0,
                    avg_rating=3.0,
                    size=10,
                    samples=[],
                    config=config
                )
            self.assertIn("daily request limit reached", str(ctx.exception))
            
            # 2. Daily Tokens limit exceeded
            mock_usage.return_value = (99500, 10)
            
            with self.assertRaises(RuntimeError) as ctx:
                summarize_cluster(
                    cluster_id=0,
                    avg_rating=3.0,
                    size=10,
                    samples=[],
                    config=config
                )
            self.assertIn("daily token limit exceeded", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
