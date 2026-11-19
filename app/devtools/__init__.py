"""Development-only tools (roadmap 3.9). Mounted only when ENVIRONMENT=development."""

from app.devtools.router import router

__all__ = ["router"]
