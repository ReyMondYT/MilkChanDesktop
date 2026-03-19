"""
memory - Custom tool for MilkChan to interact with the memory system.

Allows the LLM to store and retrieve information for long-term memory.
"""

DESCRIPTION = """
Store or retrieve information from Milk Chan's long-term memory.
Use this to remember important facts about the user, preferences, or past conversations.
"""

ARGS_DESCRIPTION = {
    "action": "Action to perform: 'get' (retrieve), 'set' (store), 'list' (list all keys)",
    "category": "Category for the memory item (e.g., 'user_facts', 'preferences', 'events')",
    "key": "Key name for the memory item (required for get/set)",
    "value": "Value to store (required for set action)"
}

def run(action: str, category: str = "", key: str = "", value: str = ""):
    """Interact with MilkChan's memory system.
    
    Args:
        action: get, set, or list
        category: Memory category
        key: Item key
        value: Value to store
    """
    action = action.lower().strip()
    
    try:
        from milkchan.desktop.services import memory_client
    except ImportError:
        return {"error": "Memory client not available"}
    
    if action == "list":
        try:
            items = memory_client.list_items()
            return {"items": items}
        except Exception as e:
            return {"error": str(e)}
    
    if action == "get":
        if not category or not key:
            return {"error": "category and key are required for get action"}
        try:
            result = memory_client.get_item(category, key)
            if result is None:
                return {"found": False, "message": f"No item found for {category}/{key}"}
            return {"found": True, "value": result}
        except Exception as e:
            return {"error": str(e)}
    
    if action == "set":
        if not category or not key or not value:
            return {"error": "category, key, and value are required for set action"}
        try:
            memory_client.set_item(category, key, value)
            return {"success": True, "message": f"Stored {category}/{key}"}
        except Exception as e:
            return {"error": str(e)}
    
    return {"error": f"Unknown action '{action}'. Valid: get, set, list"}