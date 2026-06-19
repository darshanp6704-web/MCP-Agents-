import sys
import argparse
import logging
import json
import sqlite3
from datetime import datetime, timedelta
from typing import List

from pulse.agent.orchestrator import run_weekly_review_pulse, get_iso_week_dates
from pulse.ledger.store import get_db_path

def get_weeks_between(from_week: str, to_week: str) -> List[str]:
    """Generates a sequential list of ISO weeks between from_week and to_week (inclusive)."""
    start_date = datetime.strptime(from_week + "-1", "%G-W%V-%u")
    end_date = datetime.strptime(to_week + "-1", "%G-W%V-%u")
    
    weeks = []
    current = start_date
    while current <= end_date:
        y, w, _ = current.isocalendar()
        weeks.append(f"{y}-W{w:02d}")
        current += timedelta(weeks=1)
        
    return weeks

def handle_run(args) -> None:
    try:
        result = run_weekly_review_pulse(
            product_slug=args.product,
            iso_week=args.iso_week,
            dry_run=False,
            email_mode=args.email_mode
        )
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error running pulse: {e}", file=sys.stderr)
        sys.exit(1)

def handle_dry_run(args) -> None:
    try:
        result = run_weekly_review_pulse(
            product_slug=args.product,
            iso_week=args.iso_week,
            dry_run=True,
            email_mode=args.email_mode
        )
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error executing dry-run: {e}", file=sys.stderr)
        sys.exit(1)

def handle_backfill(args) -> None:
    try:
        weeks = get_weeks_between(args.from_week, args.to_week)
        print(f"Starting backfill for product '{args.product}' across {len(weeks)} weeks: {weeks}")
        
        results = []
        for week in weeks:
            print(f"\nProcessing week {week}...")
            res = run_weekly_review_pulse(
                product_slug=args.product,
                iso_week=week,
                dry_run=args.dry_run,
                email_mode=args.email_mode
            )
            print(f"Week {week} status: {res.get('status', 'unknown')}")
            results.append(res)
            
        print("\nBackfill execution complete.")
        print(json.dumps(results, indent=2))
    except Exception as e:
        print(f"Error during backfill: {e}", file=sys.stderr)
        sys.exit(1)

def handle_status(args) -> None:
    db_path = get_db_path()
    if not os.path.exists(db_path):
        print(f"Ledger database does not exist at {db_path}.")
        sys.exit(0)

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if args.iso_week:
            cursor.execute(
                "SELECT * FROM runs WHERE product = ? AND iso_week = ?",
                (args.product, args.iso_week)
            )
            rows = cursor.fetchall()
        else:
            cursor.execute(
                "SELECT * FROM runs WHERE product = ? ORDER BY started_at DESC LIMIT 10",
                (args.product,)
            )
            rows = cursor.fetchall()

        if not rows:
            print(f"No run records found for product '{args.product}'" + (f" and week '{args.iso_week}'" if args.iso_week else ""))
            conn.close()
            return

        for row in rows:
            run_data = dict(row)
            # Fetch deliveries
            cursor.execute("SELECT * FROM deliveries WHERE run_id = ?", (run_data["run_id"],))
            deliveries = cursor.fetchall()
            run_data["deliveries"] = [dict(d) for d in deliveries]
            
            print(json.dumps(run_data, indent=2))
            print("-" * 50)

        conn.close()
    except Exception as e:
        print(f"Error querying ledger status: {e}", file=sys.stderr)
        sys.exit(1)

import os

def handle_scrape(args) -> None:
    try:
        from pulse.agent.orchestrator import load_yaml_config, get_iso_week_dates
        from pulse.ingestion.play_store import fetch_play_store_reviews
        from pulse.ingestion.normalizer import normalize_reviews
        from pulse.ingestion.cache import save_to_cache

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        product_cfg_path = os.path.join(base_dir, "config", "products", f"{args.product}.yaml")
        product_config = load_yaml_config(product_cfg_path)

        iso_week = args.iso_week
        if not iso_week:
            target_date = datetime.utcnow() - timedelta(days=7)
            iso_year, iso_wk, _ = target_date.isocalendar()
            iso_week = f"{iso_year}-W{iso_wk:02d}"

        window_weeks = product_config.get("ingestion", {}).get("window_weeks", 10)
        app_id = product_config.get("play_store", {}).get("app_id", f"com.nextbillion.{args.product}")
        max_reviews = product_config.get("ingestion", {}).get("max_reviews", 5000)
        min_words = product_config.get("ingestion", {}).get("min_words", 8)
        allowed_lang = product_config.get("ingestion", {}).get("allowed_language", "en")

        _, week_sunday = get_iso_week_dates(iso_week)

        print(f"Scraping Google Play Store reviews for '{args.product}' (App ID: {app_id})...")
        raw_reviews = fetch_play_store_reviews(app_id, week_sunday, window_weeks, max_reviews)
        print(f"Successfully scraped {len(raw_reviews)} raw reviews.")

        print("Normalizing reviews...")
        normalized_reviews = normalize_reviews(raw_reviews, min_words=min_words, allowed_lang=allowed_lang)
        print(f"Kept {len(normalized_reviews)} reviews after quality filters.")

        print(f"Saving to cache...")
        save_to_cache(args.product, iso_week, raw_reviews, normalized_reviews, window_weeks)
        print(f"Cache successfully saved for product '{args.product}' and week '{iso_week}'.")
    except Exception as e:
        print(f"Error executing scrape: {e}", file=sys.stderr)
        sys.exit(1)

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    parser = argparse.ArgumentParser(
        description="Pulse CLI - Orchestrator for the Weekly Product Review Pulse"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. run command
    run_parser = subparsers.add_parser("run", help="Run the pulse analysis and delivery for a specific week")
    run_parser.add_argument("--product", required=True, help="Product slug (e.g. groww)")
    run_parser.add_argument("--iso-week", help="ISO 8601 week string (e.g. 2026-W23). Defaults to previous week.")
    run_parser.add_argument("--email-mode", choices=["draft", "send"], help="Overrides email delivery mode")

    # 2. dry-run command
    dry_parser = subparsers.add_parser("dry-run", help="Run full pipeline except Docs/Gmail MCP writes")
    dry_parser.add_argument("--product", required=True, help="Product slug (e.g. groww)")
    dry_parser.add_argument("--iso-week", help="ISO 8601 week string (e.g. 2026-W23)")
    dry_parser.add_argument("--email-mode", choices=["draft", "send"], help="Overrides email delivery mode")

    # 3. backfill command
    back_parser = subparsers.add_parser("backfill", help="Perform backfill runs for a range of weeks")
    back_parser.add_argument("--product", required=True, help="Product slug (e.g. groww)")
    back_parser.add_argument("--from-week", dest="from_week", required=True, help="ISO start week (e.g. 2026-W01)")
    back_parser.add_argument("--to-week", dest="to_week", required=True, help="ISO end week (e.g. 2026-W20)")
    back_parser.add_argument("--dry-run", action="store_true", help="Execute backfill in dry-run mode")
    back_parser.add_argument("--email-mode", choices=["draft", "send"], default="draft", help="Email delivery mode during backfill")

    # 4. status command
    status_parser = subparsers.add_parser("status", help="Query execution ledger for runs metadata")
    status_parser.add_argument("--product", required=True, help="Product slug (e.g. groww)")
    status_parser.add_argument("--iso-week", help="Target ISO week. If omitted, prints last 10 runs.")

    # 5. scrape command
    scrape_parser = subparsers.add_parser("scrape", help="Only scrape and cache reviews from the Play Store")
    scrape_parser.add_argument("--product", required=True, help="Product slug (e.g. groww)")
    scrape_parser.add_argument("--iso-week", help="ISO 8601 week string (e.g. 2026-W23)")

    args = parser.parse_args()

    if args.command == "run":
        handle_run(args)
    elif args.command == "dry-run":
        handle_dry_run(args)
    elif args.command == "backfill":
        handle_backfill(args)
    elif args.command == "status":
        handle_status(args)
    elif args.command == "scrape":
        handle_scrape(args)

if __name__ == "__main__":
    main()
