import os
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

def get_db_path() -> str:
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    db_dir = os.path.join(base_dir, "data")
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, "runs.db")

def init_db() -> None:
    """Initializes SQLite database tables and indexes."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 1. Create runs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            product TEXT NOT NULL,
            iso_week TEXT NOT NULL,
            status TEXT NOT NULL,
            review_count INTEGER,
            window_weeks INTEGER,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            error_message TEXT
        )
    """)
    
    # 2. Create deliveries table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deliveries (
            run_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            external_id TEXT,
            url TEXT,
            idempotency_key TEXT,
            FOREIGN KEY (run_id) REFERENCES runs(run_id)
        )
    """)
    
    # 3. Create unique index to enforce at-most-one successful run per product/week
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_completed_run 
        ON runs(product, iso_week) 
        WHERE status = 'completed'
    """)
    
    # 4. Create llm_usage table for tracking daily rate limits
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS llm_usage (
            timestamp TEXT NOT NULL,
            tokens INTEGER NOT NULL,
            requests INTEGER NOT NULL
        )
    """)
    
    conn.commit()
    conn.close()

def check_completed_run(product: str, iso_week: str) -> Optional[Dict[str, Any]]:
    """Checks if a completed run exists for a product and ISO week. Returns details if found."""
    init_db()
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT * FROM runs WHERE product = ? AND iso_week = ? AND status = 'completed'",
        (product, iso_week)
    )
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return None
        
    run_details = dict(row)
    
    # Retrieve delivery details
    cursor.execute("SELECT * FROM deliveries WHERE run_id = ?", (run_details["run_id"],))
    deliveries = cursor.fetchall()
    run_details["deliveries"] = [dict(d) for d in deliveries]
    
    conn.close()
    return run_details

def start_run(run_id: str, product: str, iso_week: str, window_weeks: int, review_count: int) -> None:
    """Inserts a run record with 'pending' status."""
    init_db()
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    started_at = datetime.utcnow().isoformat()
    cursor.execute(
        """
        INSERT INTO runs (run_id, product, iso_week, status, review_count, window_weeks, started_at)
        VALUES (?, ?, ?, 'pending', ?, ?, ?)
        """,
        (run_id, product, iso_week, review_count, window_weeks, started_at)
    )
    conn.commit()
    conn.close()

def complete_run(run_id: str, error_message: Optional[str] = None) -> None:
    """Updates run record status to 'completed' or 'failed'."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    completed_at = datetime.utcnow().isoformat()
    status = "failed" if error_message else "completed"
    
    cursor.execute(
        """
        UPDATE runs
        SET status = ?, completed_at = ?, error_message = ?
        WHERE run_id = ?
        """,
        (status, completed_at, error_message, run_id)
    )
    conn.commit()
    conn.close()

def record_delivery(
    run_id: str,
    channel: str,
    external_id: str,
    url: Optional[str] = None,
    idempotency_key: Optional[str] = None
) -> None:
    """Records details about Google Docs or Gmail deliveries."""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute(
        """
        INSERT INTO deliveries (run_id, channel, external_id, url, idempotency_key)
        VALUES (?, ?, ?, ?, ?)
        """,
        (run_id, channel, external_id, url, idempotency_key)
    )
    conn.commit()
    conn.close()

def record_llm_usage(tokens: int, requests: int = 1) -> None:
    """Records LLM token and request counts to the SQLite database."""
    init_db()
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    timestamp = datetime.utcnow().isoformat()
    cursor.execute(
        "INSERT INTO llm_usage (timestamp, tokens, requests) VALUES (?, ?, ?)",
        (timestamp, tokens, requests)
    )
    conn.commit()
    conn.close()

def get_daily_llm_usage() -> Tuple[int, int]:
    """
    Returns the total (tokens, requests) consumed in the last 24 hours.
    Returns (0, 0) if no usage is recorded.
    """
    init_db()
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Calculate time 24 hours ago in ISO format
    cutoff = (datetime.utcnow() - timedelta(days=1)).isoformat()
    
    cursor.execute(
        "SELECT SUM(tokens), SUM(requests) FROM llm_usage WHERE timestamp >= ?",
        (cutoff,)
    )
    row = cursor.fetchone()
    
    conn.close()
    
    if row and row[0] is not None and row[1] is not None:
        return int(row[0]), int(row[1])
    return 0, 0

