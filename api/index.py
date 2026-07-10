import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app  # noqa: F401  — re-export ASGI app for serverless hosts (e.g. uvicorn api.index:app)
