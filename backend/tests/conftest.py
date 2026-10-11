import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="sf_test_")
os.environ["SQLITE_PATH"] = str(Path(_tmp) / "test.db")
os.environ["LOCAL_STORAGE_DIR"] = str(Path(_tmp) / "files")
for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_CLOUD_PROJECT",
          "DATABASE_URL", "CLOUD_SQL_INSTANCE", "GCS_BUCKET"):
    os.environ.pop(k, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
