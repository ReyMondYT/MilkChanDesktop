"""
MilkChan v1.0 - Unified AI Companion Desktop Application

Everything you need in one package:
- Desktop GUI (PyQt5)
- API Server (FastAPI) 
- AI Services (OpenAI)
- Memory Services (SQLite)

Usage:
    python -m milkchan.main       # Full unified app
    ./run.sh                      # Source checkout launcher
"""

__version__ = "1.0.0"
__author__ = "MilkChan Team"

from .core.config import Config

__all__ = ["Config", "__version__"]
