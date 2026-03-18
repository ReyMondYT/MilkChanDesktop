"""
Memory client - SQLite storage (NO HTTP!)

Uses local SQLite database for fast, reliable storage.
"""

from typing import List, Any, Optional

from milkchan.storage.database import (
    get_history as _db_get_history,
    update_history as _db_update_history,
    add_history_item as _db_add_history_item,
    clear_history as _db_clear_history,
    get_item as _db_get_item,
    set_item as _db_set_item,
    get_doc as _db_get_doc,
    delete_item as _db_delete_item,
    delete_doc as _db_delete_doc,
    init_db,
    migrate_from_json,
)


def init():
    """Initialize database and migrate from JSON if needed"""
    init_db()
    # Try to migrate from old memory.json
    migrate_from_json()


def get_history() -> List[dict]:
    """Get conversation history"""
    return _db_get_history()


def update_history(history: List[dict]) -> bool:
    """Update conversation history"""
    return _db_update_history(history)


def add_to_history(role: str, content: str) -> bool:
    """Add single item to history"""
    return _db_add_history_item(role, content)


def clear_history() -> bool:
    """Clear all history"""
    return _db_clear_history()


def get_item(doc: str, item: str) -> Optional[Any]:
    """Get specific item from document"""
    return _db_get_item(doc, item)


def set_item(doc: str, item: str, value: Any) -> bool:
    """Set specific item in document"""
    return _db_set_item(doc, item, value)


def get_document(doc: str) -> dict:
    """Get all items in a document"""
    return _db_get_doc(doc)


def delete_item(doc: str, item: str) -> bool:
    """Delete specific item"""
    return _db_delete_item(doc, item)


def delete_document(doc: str) -> bool:
    """Delete entire document"""
    return _db_delete_doc(doc)


def get_persona() -> Optional[str]:
    """Get persona"""
    return get_item('persona', 'personality')


def set_persona(personality: str) -> bool:
    """Set persona"""
    return set_item('persona', 'personality', personality)