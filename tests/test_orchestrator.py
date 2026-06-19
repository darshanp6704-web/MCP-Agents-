import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import sqlite3
import yaml
from datetime import datetime, timedelta

# Adjust path to import pulse module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pulse.ingestion.models import Review, RawReview
from pulse.agent.orchestrator import run_weekly_review_pulse
from pulse.ledger.store import check_completed_run, init_db, get_db_path

class TestOrchestrator(unittest.TestCase):
    @patch("pulse.agent.orchestrator.fetch_play_store_reviews")
    @patch("pulse.agent.orchestrator.load_from_cache")
    @patch("pulse.agent.orchestrator.get_embeddings")
    @patch("pulse.agent.orchestrator.summarize_cluster")
    @patch("pulse.agent.orchestrator.McpClient")
    def test_end_to_end_dry_run(self, mock_mcp, mock_summarize, mock_embed, mock_cache, mock_fetch):
        mock_cache.return_value = None
        # 1. Mock Play Store ingestion to return 30 dummy reviews
        mock_reviews = []
        for i in range(30):
            mock_reviews.append(
                RawReview(
                    text=f"This is a dummy test review number {i} for Groww. Excellent features and UI.",
                    rating=5 if i % 2 == 0 else 4,
                    published_at=datetime.utcnow() - f"day-{i % 7}" if False else datetime.utcnow(),
                    review_id=f"rev_{i}",
                    user_name=f"User {i}",
                    app_version="8.24.1"
                )
            )
        # Fix published_at datetime
        for i, r in enumerate(mock_reviews):
            r.published_at = datetime.utcnow() - timedelta(days=i % 7)
            
        mock_fetch.return_value = mock_reviews

        # 2. Mock Embeddings to return dummy vectors
        mock_embed.return_value = [[0.1] * 1536 for _ in range(30)]

        # 3. Mock Groq summarizer response
        mock_summarize.return_value = {
            "theme_name": "App Interface and Ease of Use",
            "summary": "Users generally praised the clean app design and smooth navigation features.",
            "quotes": ["Excellent features and UI"],
            "action_ideas": [
                {
                    "title": "Enhance UI consistency",
                    "detail": "Keep visual parameters uniform across stock/mutual fund indices."
                }
            ]
        }

        # Ensure database is initialized
        init_db()

        # 4. Trigger dry-run
        result = run_weekly_review_pulse(
            product_slug="groww",
            iso_week="2026-W23",
            dry_run=True
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["reviews_count"], 30)
        self.assertGreaterEqual(result["themes_count"], 1)

    @patch("pulse.agent.orchestrator.fetch_play_store_reviews")
    @patch("pulse.agent.orchestrator.load_from_cache")
    @patch("pulse.agent.orchestrator.get_embeddings")
    @patch("pulse.agent.orchestrator.summarize_cluster")
    @patch("pulse.agent.orchestrator.McpClient")
    def test_run_with_mcp_delivery(self, mock_mcp_class, mock_summarize, mock_embed, mock_cache, mock_fetch):
        mock_cache.return_value = None
        # 1. Setup ingestion & embeddings mocks
        mock_reviews = [
            RawReview(
                text=f"This is a dummy test review number {i} for Groww. Excellent features.",
                rating=5,
                published_at=datetime.utcnow() - timedelta(days=1),
                review_id=f"rev_{i}",
                user_name=f"User {i}",
                app_version="8.24.1"
            )
            for i in range(30)
        ]
        mock_fetch.return_value = mock_reviews
        mock_embed.return_value = [[0.1] * 1536 for _ in range(30)]
        mock_summarize.return_value = {
            "theme_name": "Features",
            "summary": "Excellent features",
            "quotes": ["Excellent features"],
            "action_ideas": [{"title": "Keep up", "detail": "Continue improving features."}]
        }

        # 2. Mock MCP client connections and tool returns
        mock_docs_client = MagicMock()
        mock_gmail_client = MagicMock()
        
        # Docs tools responses
        mock_docs_client.call_tool.side_effect = lambda tool, args: {
            "find_section_by_anchor": {"found": False},
            "append_section": {"heading_id": "h.1234abcd", "url": "https://docs.google.com/document/d/TEST_DOC_ID/edit#heading=h.1234abcd"},
            "get_document_url": {"url": "https://docs.google.com/document/d/TEST_DOC_ID/edit#heading=h.1234abcd"}
        }.get(tool, {})

        # Gmail tools responses
        mock_gmail_client.call_tool.side_effect = lambda tool, args: {
            "check_idempotency": {"already_sent": False},
            "create_draft": {"status": "success", "draft_id": "draft_abc123"}
        }.get(tool, {})

        # Make the mock class instantiate our mocked instances in order: Docs, then Gmail
        mock_mcp_class.side_effect = [mock_docs_client, mock_gmail_client]

        # Ensure database is clean for this week to avoid idempotency hit
        db_path = get_db_path()
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM runs WHERE product = 'groww' AND iso_week = '2026-W24'")
            conn.commit()
            conn.close()

        # Temporarily patch groww.yaml target doc ID to be a mock ID so config loads clean
        # (or rely on default, but let's override target yaml config parameters in orchestrator mock if needed.
        # Actually, let's patch load_yaml_config to inject custom mock config!)
        original_load = yaml.safe_load
        def mock_load_config(filepath):
            if "groww.yaml" in filepath:
                return {
                    "product": "groww",
                    "display_name": "Groww",
                    "play_store": {"app_id": "com.nextbillion.groww"},
                    "ingestion": {"window_weeks": 10, "min_reviews": 20, "max_reviews": 5000, "min_words": 8, "allowed_language": "en"},
                    "delivery": {
                        "google_doc_id": "mock_google_doc_id_123",
                        "email": {
                            "recipients": ["stakeholder@example.com"],
                            "default_mode": "draft"
                        }
                    }
                }
            with open(filepath, "r") as f:
                return original_load(f)

        with patch("pulse.agent.orchestrator.load_yaml_config", side_effect=mock_load_config):
            result = run_weekly_review_pulse(
                product_slug="groww",
                iso_week="2026-W24",
                dry_run=False
            )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["doc_delivery"]["heading_id"], "h.1234abcd")
        self.assertEqual(result["email_delivery"]["message_id"], "draft_abc123")
        self.assertEqual(result["email_delivery"]["mode"], "draft")

        # Verify idempotency ledger works on re-run
        with patch("pulse.agent.orchestrator.load_yaml_config", side_effect=mock_load_config):
            second_result = run_weekly_review_pulse(
                product_slug="groww",
                iso_week="2026-W24",
                dry_run=False
            )
        self.assertEqual(second_result["status"], "skipped")
        self.assertEqual(second_result["reason"], "run already completed")

if __name__ == "__main__":
    unittest.main()
