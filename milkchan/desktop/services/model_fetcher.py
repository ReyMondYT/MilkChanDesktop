"""
Model Fetcher - Get available models from OpenAI-compatible APIs

Fetches the list of available models from various OpenAI-compatible APIs.
Handles OpenAI, NVIDIA NIM, Ollama, and other compatible endpoints.
"""

import logging
from typing import List, Optional
import requests

logger = logging.getLogger(__name__)


def _is_ollama_endpoint(base_url: str) -> bool:
    """Check if the endpoint is an Ollama server"""
    return 'localhost:11434' in base_url or '127.0.0.1:11434' in base_url


def _fetch_ollama_models(base_url: str) -> List[str]:
    """Fetch models from Ollama's native API"""
    try:
        # Ollama uses /api/tags for model list
        ollama_url = base_url.replace('/v1', '').rstrip('/')
        response = requests.get(f'{ollama_url}/api/tags', timeout=10)
        response.raise_for_status()
        
        data = response.json()
        models = []
        
        for model in data.get('models', []):
            name = model.get('name', '')
            if name:
                models.append(name)
        
        return models
    except Exception as e:
        logger.warning(f"Failed to fetch Ollama models: {e}")
        return []


def _fetch_models_from_api(api_key: str, base_url: Optional[str] = None) -> List[str]:
    """Fetch models from API"""
    # Handle Ollama specially
    if base_url and _is_ollama_endpoint(base_url):
        return _fetch_ollama_models(base_url)
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url if base_url else None)
        
        # Fetch models
        models_data = client.models.list()
        
        # Handle different API response formats
        if models_data is None:
            logger.warning("API returned None for models list")
            return []
        
        # Try iterating directly over the response (works for SyncPage)
        models = []
        try:
            for model in models_data:
                if hasattr(model, 'id'):
                    models.append(model.id)
                elif isinstance(model, dict):
                    model_id = model.get('id') or model.get('name', '')
                    if model_id:
                        models.append(model_id)
                elif isinstance(model, str):
                    models.append(model)
        except TypeError:
            pass
        
        # Also try the data attribute
        if not models:
            data = getattr(models_data, 'data', None)
            if data:
                for model in data:
                    if hasattr(model, 'id'):
                        models.append(model.id)
                    elif isinstance(model, dict):
                        model_id = model.get('id') or model.get('name', '')
                        if model_id:
                            models.append(model_id)
                    elif isinstance(model, str):
                        models.append(model)
        
        if not models:
            logger.warning("Could not extract model IDs from response")
            return []
        
        # Sort: put popular models first
        def sort_key(m):
            m_lower = m.lower()
            if 'gpt-4o' in m_lower:
                return (0, m_lower)
            elif 'gpt-4' in m_lower:
                return (1, m_lower)
            elif 'gpt-3.5' in m_lower:
                return (2, m_lower)
            elif 'llama' in m_lower:
                return (3, m_lower)
            elif 'qwen' in m_lower:
                return (3, m_lower)
            else:
                return (4, m_lower)
        
        models.sort(key=sort_key)
        return models
    except Exception as e:
        logger.warning(f"Failed to fetch models: {e}")
        return []


def get_available_models(api_key: Optional[str] = None, base_url: Optional[str] = None) -> List[str]:
    """
    Get list of available models from the configured API.
    
    Args:
        api_key: API key (uses config if None)
        base_url: Base URL (uses config if None)
    
    Returns:
        List of model IDs
    """
    if not api_key:
        from milkchan.core.config import get_config
        config = get_config()
        api_key = config.openai_api_key
        base_url = config.openai_base_url
    
    if not api_key:
        logger.warning("No API key configured")
        return []
    
    if not base_url:
        base_url = "https://api.openai.com/v1"
    
    # Fetch models from API
    models = _fetch_models_from_api(api_key, base_url)
    
    return models


def refresh_models():
    """Clear model cache to force refresh"""
    pass  # No caching anymore


def get_model_categories(models: List[str]) -> dict:
    """
    Categorize models by type.
    
    Returns:
        Dict with categories: {'gpt-4o': [...], 'gpt-4': [...], ...}
    """
    categories = {
        'gpt-4o': [],
        'gpt-4': [],
        'gpt-3.5': [],
        'other': []
    }
    
    for model in models:
        model_lower = model.lower()
        if 'gpt-4o' in model_lower:
            categories['gpt-4o'].append(model)
        elif 'gpt-4' in model_lower:
            categories['gpt-4'].append(model)
        elif 'gpt-3.5' in model_lower:
            categories['gpt-3.5'].append(model)
        else:
            categories['other'].append(model)
    
    # Remove empty categories
    return {k: v for k, v in categories.items() if v}
