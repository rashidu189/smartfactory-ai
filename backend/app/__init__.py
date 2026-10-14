"""SmartFactory AI backend package.

Loads backend/.env automatically (if present) so local runs work with or without
`--env-file .env`. Real environment variables always win (override=False).
Set SMARTFACTORY_NO_DOTENV=1 to disable (the tests do this).
"""
import os
from pathlib import Path

if not os.getenv("SMARTFACTORY_NO_DOTENV"):
    _env = Path(__file__).resolve().parent.parent / ".env"
    if _env.is_file():
        try:
            from dotenv import load_dotenv
            load_dotenv(_env, override=False)
        except ImportError:  # python-dotenv missing: fall back to --env-file
            pass
