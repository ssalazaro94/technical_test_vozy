"""ASGI entry point: `uvicorn callaudit.main:app`."""

import logging

from callaudit.adapters.http.app import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = create_app()
