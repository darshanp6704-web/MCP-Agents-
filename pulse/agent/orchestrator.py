import os
import yaml
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

from pulse.ingestion.models import Review, RawReview, RunContext
from pulse.ingestion.play_store import fetch_play_store_reviews
from pulse.ingestion.normalizer import normalize_reviews
from pulse.ingestion.cache import save_to_cache, load_from_cache
from pulse.pipeline.scrubber import scrub_pii
from pulse.pipeline.embeddings import get_embeddings
from pulse.pipeline.clustering import run_clustering
from pulse.pipeline.summarizer import summarize_cluster
from pulse.pipeline.quote_validator import validate_theme_quotes
from pulse.render.doc_section import render_doc_section_blocks
from pulse.render.email_teaser import render_email_teaser
from pulse.ledger.store import (
    check_completed_run,
    start_run,
    complete_run,
    record_delivery
)
from pulse.agent.mcp_client import McpClient

logger = logging.getLogger(__name__)

def load_yaml_config(filepath: str) -> Dict[str, Any]:
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Configuration file not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def get_iso_week_dates(iso_week_str: str) -> Tuple[datetime, datetime]:
    """
    Parses an ISO week string (e.g. 2026-W23) and returns the range:
    (Monday 00:00:00, Sunday 23:59:59).
    """
    # monday of the week
    monday = datetime.strptime(iso_week_str + "-1", "%G-W%V-%u")
    sunday = monday + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return monday, sunday

def run_weekly_review_pulse(
    product_slug: str,
    iso_week: Optional[str] = None,
    dry_run: bool = False,
    email_mode: Optional[str] = None
) -> Dict[str, Any]:
    """
    Orchestrates the entire Weekly Product Review Pulse execution:
    1. Configurations loading
    2. Idempotency ledger checking
    3. Scrape reviews (or load cache)
    4. Run UMAP/HDBSCAN clustering
    5. Summarize clusters via Groq
    6. Verify quotes verbatim
    7. Generate structured outputs (Docs & Email)
    8. Write to workspace using Google Docs & Gmail MCP servers
    9. Log execution metrics in local SQLite runs ledger
    """
    # Initialize run directories
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # Load configs
    product_cfg_path = os.path.join(base_dir, "config", "products", f"{product_slug}.yaml")
    pipeline_cfg_path = os.path.join(base_dir, "config", "pipeline.yaml")
    
    product_config = load_yaml_config(product_cfg_path)
    pipeline_config = load_yaml_config(pipeline_cfg_path)
    
    # Merge configs for general ingestion/pipeline parameters
    run_config = {**pipeline_config, **product_config}
    
    # Resolve ISO week (default to previous full week)
    if not iso_week:
        # Get ISO week of 7 days ago to ensure week is completed
        target_date = datetime.utcnow() - timedelta(days=7)
        iso_year, iso_wk, _ = target_date.isocalendar()
        iso_week = f"{iso_year}-W{iso_wk:02d}"
        
    logger.info(f"Initiating review pulse for product '{product_slug}' for week '{iso_week}' (Dry Run = {dry_run})")
    
    # 1. Idempotency Check (Ledger level)
    prior_run = check_completed_run(product_slug, iso_week)
    if prior_run and not dry_run:
        logger.info(f"Idempotency Triggered: Run already exists and is COMPLETED in ledger for {product_slug} / {iso_week}.")
        return {
            "status": "skipped",
            "reason": "run already completed",
            "run_id": prior_run["run_id"],
            "doc_delivery": next((d for d in prior_run["deliveries"] if d["channel"] == "google_doc"), None),
            "email_delivery": next((d for d in prior_run["deliveries"] if d["channel"] == "gmail"), None)
        }
        
    run_id = f"{product_slug}-{iso_week}-{str(uuid.uuid4())[:8]}"
    window_weeks = run_config.get("ingestion", {}).get("window_weeks", 10)
    
    # Calculate scraping windows
    _, week_sunday = get_iso_week_dates(iso_week)
    
    # 2. Ingestion & Caching
    cached_data = load_from_cache(product_slug, iso_week)
    if cached_data:
        raw_reviews, normalized_reviews = cached_data
    else:
        app_id = run_config.get("play_store", {}).get("app_id", f"com.nextbillion.{product_slug}")
        max_reviews = run_config.get("ingestion", {}).get("max_reviews", 5000)
        
        # Ingestion step
        try:
            raw_reviews = fetch_play_store_reviews(app_id, week_sunday, window_weeks, max_reviews)
        except Exception as err:
            logger.error(f"Ingestion stage failed: {err}")
            raise err
            
        # Normalization step
        min_words = run_config.get("ingestion", {}).get("min_words", 8)
        allowed_lang = run_config.get("ingestion", {}).get("allowed_language", "en")
        normalized_reviews = normalize_reviews(raw_reviews, min_words=min_words, allowed_lang=allowed_lang)
        
        # Save cache
        save_to_cache(product_slug, iso_week, raw_reviews, normalized_reviews, window_weeks)

    # ML count check floor
    min_reviews = run_config.get("ingestion", {}).get("min_reviews", 20)
    if len(normalized_reviews) < min_reviews:
        logger.warning(f"Aborting execution: Normalized review count {len(normalized_reviews)} is below floor threshold {min_reviews}.")
        return {
            "status": "aborted",
            "reason": f"insufficient reviews: {len(normalized_reviews)} (floor is {min_reviews})"
        }
        
    # Start ledger entry (as pending)
    if not dry_run:
        start_run(run_id, product_slug, iso_week, window_weeks, len(normalized_reviews))

    # 3. PII Redaction
    logger.info("Scrubbing PII from reviews...")
    scrubbed_reviews = [
        Review(
            text=scrub_pii(r.text),
            rating=r.rating,
            review_id=r.review_id,
            published_at=r.published_at
        )
        for r in normalized_reviews
    ]

    # 4. Embeddings & Clustering
    logger.info("Vectorizing review text...")
    embed_cfg = run_config.get("embedding", {})
    embeddings = get_embeddings(
        [r.text for r in scrubbed_reviews],
        [r.rating for r in scrubbed_reviews],
        provider=embed_cfg.get("provider", "openai"),
        model=embed_cfg.get("model", "text-embedding-3-small"),
        batch_size=embed_cfg.get("batch_size", 64)
    )
    
    logger.info("Grouping reviews into semantic clusters...")
    clusters = run_clustering(scrubbed_reviews, embeddings, run_config)
    
    # 5. Summarization & Verbatim Quote Validation
    themes = []
    max_themes = run_config.get("summarization", {}).get("max_themes", 5)
    
    full_corpus_texts = [r.text for r in scrubbed_reviews]
    
    # Process clusters up to max_themes limit
    for cluster in clusters[:max_themes]:
        cluster_id = cluster["cluster_id"]
        avg_rating = cluster["avg_rating"]
        size = cluster["size"]
        samples = cluster["samples"]
        
        theme_json = summarize_cluster(cluster_id, avg_rating, size, samples, run_config)
        if theme_json:
            # Validate quotes
            cluster_texts = [r.text for r in cluster["reviews"]]
            validated_theme = validate_theme_quotes(theme_json, cluster_texts, full_corpus_texts)
            themes.append(validated_theme)

    if not themes:
        logger.error("Analysis completed but no valid themes were summarized.")
        if not dry_run:
            complete_run(run_id, error_message="No themes summarized by LLM pipeline")
        return {"status": "failed", "reason": "no themes generated"}

    # 6. Render Outputs
    anchor_key = f"{product_slug}-{iso_week}"
    doc_blocks = render_doc_section_blocks(
        product_name=run_config.get("display_name", product_slug),
        iso_week=iso_week,
        window_weeks=window_weeks,
        themes=themes,
        anchor_key=anchor_key
    )

    # 7. Delivery / Workspace writes (MCP Client integration)
    doc_delivery_info = {}
    email_delivery_info = {}

    if dry_run:
        logger.info("DRY-RUN Execution: Printing output blocks & skipping workspace writes.")
        print("\n=== GOOGLE DOC BLOCK GENERATION ===")
        for b in doc_blocks:
            print(f"[{b['type'].upper()}]: {b['text']}")
        print("\n=== EMAIL TEASER GENERATION ===")
        # Build mock URL for teaser print
        mock_doc_url = f"https://docs.google.com/document/d/MOCK_ID/edit#heading=h.mock_heading"
        resolved_email_mode = email_mode or run_config.get("delivery", {}).get("email", {}).get("default_mode", "draft")
        subject, html, text = render_email_teaser(
            product_display_name=run_config.get("display_name", product_slug),
            iso_week=iso_week,
            doc_url=mock_doc_url,
            themes=themes,
            window_weeks=window_weeks
        )
        print(f"Subject: {subject}")
        print(f"Mode: {resolved_email_mode}")
        print(f"Body (Text):\n{text}")
        
        return {
            "status": "completed",
            "run_id": run_id,
            "themes_count": len(themes),
            "reviews_count": len(normalized_reviews)
        }

    # Retrieve Google Docs MCP and Gmail MCP clients
    docs_mcp = None
    gmail_mcp = None
    
    try:
        # Load MCP server configurations
        mcp_servers_path = os.path.join(base_dir, "config", "mcp", "servers.json")
        servers_config = load_yaml_config(mcp_servers_path).get("mcpServers", {})
        
        google_doc_id = run_config.get("delivery", {}).get("google_doc_id")
        if not google_doc_id or google_doc_id == "YOUR_GOOGLE_DOC_ID_HERE":
            raise ValueError("google_doc_id has not been configured in groww.yaml.")
            
        # A. Google Docs Delivery
        logger.info("Initializing Google Docs MCP Client...")
        docs_cfg = servers_config.get("google-docs", {})
        docs_mcp = McpClient(
            command=docs_cfg.get("command", "node"),
            args=docs_cfg.get("args", []),
            env_file=docs_cfg.get("envFile")
        )
        docs_mcp.start()

        # Check section idempotency at doc level
        logger.info(f"Checking Google Doc for existing section anchor '{anchor_key}'...")
        lookup = docs_mcp.call_tool("find_section_by_anchor", {
            "document_id": google_doc_id,
            "anchor": anchor_key
        })

        heading_id = ""
        doc_url = ""

        if lookup.get("found"):
            logger.info("Section anchor already exists in target document. Skipping Docs write.")
            heading_id = lookup.get("heading_id", "")
            doc_url = docs_mcp.call_tool("get_document_url", {
                "document_id": google_doc_id,
                "heading_id": heading_id
            }).get("url", "")
        else:
            logger.info("Section anchor not found. Appending weekly section report to document...")
            append_res = docs_mcp.call_tool("append_section", {
                "document_id": google_doc_id,
                "anchor": anchor_key,
                "blocks": doc_blocks
            })
            heading_id = append_res.get("heading_id", "")
            doc_url = append_res.get("url", "")
            
        doc_delivery_info = {
            "document_id": google_doc_id,
            "section_anchor": anchor_key,
            "heading_id": heading_id,
            "url": doc_url
        }
        record_delivery(run_id, "google_doc", heading_id, doc_url, anchor_key)

        # B. Gmail Notification Delivery
        logger.info("Initializing Gmail MCP Client...")
        gmail_cfg = servers_config.get("gmail", {})
        gmail_mcp = McpClient(
            command=gmail_cfg.get("command", "node"),
            args=gmail_cfg.get("args", []),
            env_file=gmail_cfg.get("envFile")
        )
        gmail_mcp.start()

        # Check email idempotency
        gmail_idempotency_key = f"{anchor_key}-email"
        email_check = gmail_mcp.call_tool("check_idempotency", {
            "idempotency_key": gmail_idempotency_key
        })

        recipients = run_config.get("delivery", {}).get("email", {}).get("recipients", [])
        resolved_email_mode = email_mode or run_config.get("delivery", {}).get("email", {}).get("default_mode", "draft")

        if email_check.get("already_sent"):
            logger.info("Stakeholder email already sent. Skipping email notification.")
            email_delivery_info = {
                "mode": resolved_email_mode,
                "message_id": email_check.get("message_id"),
                "idempotency_key": gmail_idempotency_key
            }
        elif not recipients:
            logger.warning("No email recipients configured. Skipping email delivery.")
        else:
            subject, html_body, text_body = render_email_teaser(
                product_display_name=run_config.get("display_name", product_slug),
                iso_week=iso_week,
                doc_url=doc_url,
                themes=themes,
                window_weeks=window_weeks
            )

            if resolved_email_mode == "send":
                logger.info(f"Sending production email to stakeholders: {recipients}")
                email_res = gmail_mcp.call_tool("send_email", {
                    "to": recipients,
                    "subject": subject,
                    "html_body": html_body,
                    "text_body": text_body,
                    "idempotency_key": gmail_idempotency_key
                })
                msg_id = email_res.get("message_id", "")
                email_delivery_info = {
                    "mode": "send",
                    "message_id": msg_id,
                    "idempotency_key": gmail_idempotency_key
                }
                record_delivery(run_id, "gmail", msg_id, doc_url, gmail_idempotency_key)
            else:
                logger.info(f"Creating Gmail draft in stakeholder outbox for staging review...")
                draft_res = gmail_mcp.call_tool("create_draft", {
                    "to": recipients,
                    "subject": subject,
                    "html_body": html_body,
                    "text_body": text_body,
                    "idempotency_key": gmail_idempotency_key
                })
                draft_id = draft_res.get("draft_id", "")
                email_delivery_info = {
                    "mode": "draft",
                    "message_id": draft_id,
                    "idempotency_key": gmail_idempotency_key
                }
                record_delivery(run_id, "gmail", draft_id, doc_url, gmail_idempotency_key)

        # Complete SQLite ledger write
        complete_run(run_id)
        logger.info(f"Pulse run successfully completed for run_id: {run_id}.")

    except Exception as e:
        logger.error(f"Error encountered during delivery: {e}")
        complete_run(run_id, error_message=str(e))
        raise e
    finally:
        # Ensure MCP servers subprocesses are stopped gracefully
        if docs_mcp:
            docs_mcp.stop()
        if gmail_mcp:
            gmail_mcp.stop()

    return {
        "status": "completed",
        "run_id": run_id,
        "product": product_slug,
        "iso_week": iso_week,
        "doc_delivery": doc_delivery_info,
        "email_delivery": email_delivery_info
    }
