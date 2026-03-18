"""SQLite database for local storage"""

import sqlite3
import json
import os
from pathlib import Path
from typing import Any, List, Optional, Dict
from contextlib import contextmanager
import threading

# Database file path - use user data directory
_DB_PATH: Optional[Path] = None
_DB_LOCK = threading.Lock()


def get_db_path() -> Path:
    """Get database file path in user data directory"""
    global _DB_PATH
    if _DB_PATH is None:
        from milkchan.bootstrap import get_db_path as _get_user_db_path
        _DB_PATH = _get_user_db_path()
    return _DB_PATH


def set_db_path(path: str) -> None:
    """Set custom database file path"""
    global _DB_PATH
    _DB_PATH = Path(path)


@contextmanager
def get_connection():
    """Get database connection with context manager"""
    conn = sqlite3.connect(str(get_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Initialize database tables"""
    with _DB_LOCK:
        os.makedirs(get_db_path().parent, exist_ok=True)
        with get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE TABLE IF NOT EXISTS memory (
                    doc TEXT NOT NULL,
                    item TEXT NOT NULL,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (doc, item)
                );
                
                CREATE INDEX IF NOT EXISTS idx_history_created ON history(created_at);
            """)
            conn.commit()


def ensure_db_initialized():
    """Ensure database is initialized before use"""
    if not get_db_path().exists():
        init_db()


# ============== History Operations ==============

def get_history() -> List[dict]:
    """Get all conversation history"""
    ensure_db_initialized()
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT role, content FROM history ORDER BY id ASC"
        )
        return [{"role": row["role"], "content": row["content"]} for row in cursor.fetchall()]


def update_history(history: List[dict]) -> bool:
    """Replace entire conversation history"""
    ensure_db_initialized()
    with _DB_LOCK:
        with get_connection() as conn:
            conn.execute("DELETE FROM history")
            for item in history:
                conn.execute(
                    "INSERT INTO history (role, content) VALUES (?, ?)",
                    (item.get("role", "user"), item.get("content", ""))
                )
            conn.commit()
    return True


def add_history_item(role: str, content: str) -> bool:
    """Add single item to history"""
    ensure_db_initialized()
    with _DB_LOCK:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO history (role, content) VALUES (?, ?)",
                (role, content)
            )
            conn.commit()
    return True


def clear_history() -> bool:
    """Clear all history"""
    ensure_db_initialized()
    with _DB_LOCK:
        with get_connection() as conn:
            conn.execute("DELETE FROM history")
            conn.commit()
    return True


# ============== Memory Operations ==============

def get_item(doc: str, item: str) -> Optional[Any]:
    """Get specific item from document"""
    ensure_db_initialized()
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT value FROM memory WHERE doc = ? AND item = ?",
            (doc, item)
        )
        row = cursor.fetchone()
        if row:
            try:
                return json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                return row["value"]
        return None


def set_item(doc: str, item: str, value: Any) -> bool:
    """Set item in document"""
    ensure_db_initialized()
    with _DB_LOCK:
        with get_connection() as conn:
            serialized = json.dumps(value) if not isinstance(value, str) else value
            conn.execute(
                """INSERT OR REPLACE INTO memory (doc, item, value, updated_at) 
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
                (doc, item, serialized)
            )
            conn.commit()
    return True


def get_doc(doc: str) -> Dict[str, Any]:
    """Get all items in a document"""
    ensure_db_initialized()
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT item, value FROM memory WHERE doc = ?",
            (doc,)
        )
        result = {}
        for row in cursor.fetchall():
            try:
                result[row["item"]] = json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                result[row["item"]] = row["value"]
        return result


def delete_item(doc: str, item: str) -> bool:
    """Delete specific item"""
    ensure_db_initialized()
    with _DB_LOCK:
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM memory WHERE doc = ? AND item = ?",
                (doc, item)
            )
            conn.commit()
    return True


def delete_doc(doc: str) -> bool:
    """Delete entire document"""
    ensure_db_initialized()
    with _DB_LOCK:
        with get_connection() as conn:
            conn.execute("DELETE FROM memory WHERE doc = ?", (doc,))
            conn.commit()
    return True


# ============== Migration from JSON ==============

def migrate_from_json(json_path: Optional[str] = None) -> bool:
    """Migrate data from old memory.json to SQLite"""
    if json_path is None:
        json_path = Path(__file__).parent.parent / 'desktop' / 'memory.json'
    else:
        json_path = Path(json_path)
    
    if not json_path.exists():
        return False
    
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        ensure_db_initialized()
        
        # Migrate history
        if 'history' in data:
            update_history(data['history'])
        
        # Migrate other items
        for doc, items in data.items():
            if doc == 'history':
                continue
            if isinstance(items, dict):
                for item, value in items.items():
                    set_item(doc, item, value)
        
        return True
    except Exception:
        return False