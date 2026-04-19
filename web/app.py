"""
ASGI entrypoint for the web admin panel.
Railway/Procfile expects `web.app:app`.
"""
from web.routes.admin import app

