"""
Model Fetcher - Get available models from OpenAI

Fetches the list of available models directly from OpenAI API.
No HTTP server needed - uses OpenAI SDK directly.
"""

import logging
from typing import List, Optional
from functools import lru_cache
import time

logger = logging.getLogger(__name__)


def _fetch_models_from_api(api_key: str, base_url: str) -> List[str]:
    """Fetch models from API (no caching)"""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url if base_url else None)
        
        # Fetch models
        models_data = client.models.list()
        models = [model.id for model in models_data.data]
        
        # Sort: put gpt-4o and gpt-4 models first
        def sort_key(m):
            m_lower = m.lower()
            if 'gpt-4o' in m_lower:
                return (0, m_lower)
            elif 'gpt-4' in m_lower:
                return (1, m_lower)
            elif 'gpt-3.5' in m_lower:
                return (2, m_lower)
            else:
                return (3, m_lower)
        
        models.sort(key=sort_key)
        return models
    except Exception as e:
        logger.warning(f"Failed to fetch models: {e}")
        # Return default models as fallback
        return []


def get_available_models(api_key: Optional[str] = None, base_url: Optional[str] = None) -> List[str]:
    """
    Get list of available models from OpenAI.
    
    Args:
        api_key: OpenAI API key (uses config if None)
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
        logger.warning("No API key provided, returning default models")
        return [
            'gpt-4o-mini',
            'gpt-4o',
            'gpt-4-turbo',
            'gpt-3.5-turbo',
        ]
    
    # Always fetch fresh - no caching of failures
    models = _fetch_models_from_api(api_key, base_url)
    
    # If API returned nothing, use defaults
    if not models:
        return [
            'gpt-4o-mini',
            'gpt-4o',
            'gpt-4-turbo',
            'gpt-3.5-turbo',
        ]
    
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
