"""Indicator protocol package with eager restart-based module discovery."""

from app.indicators.discovery import discover_indicators

# Importing the package is the backend startup boundary for local indicators.
discover_indicators()

__all__ = ["discover_indicators"]
