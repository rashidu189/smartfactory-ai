"""Check the Gemini configuration and make one tiny test call.

    cd backend
    python -m app.check_gemini

Reads backend/.env automatically. Prints which mode is used, then calls Gemini.
If the call fails with an API key, it also tries the other key mode and tells you which setting works.
"""
from __future__ import annotations

import os
import sys

from . import ai  # noqa: F401  (importing the package loads backend/.env)


def _mask(k: str) -> str:
    return (k[:6] + "…" + k[-4:]) if len(k) > 12 else ("(set)" if k else "(empty)")


def _try(mode: str, st: dict) -> tuple[bool, str]:
    from google import genai
    try:
        if mode == "api_key":
            c = genai.Client(vertexai=False, api_key=st["key"])
        elif mode == "vertex_express":
            c = genai.Client(vertexai=True, api_key=st["key"])
        else:
            c = genai.Client(vertexai=True, project=st["project"], location=st["location"])
        r = c.models.generate_content(model=ai.model_name(), contents="Reply with exactly: OK")
        return True, (r.text or "").strip()[:60]
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:300]}"


def main() -> int:
    st = ai.gemini_settings()
    print("Gemini configuration")
    print(f"  GEMINI_API_KEY / GOOGLE_API_KEY : {_mask(st['key'])}")
    print(f"  GOOGLE_GENAI_USE_VERTEXAI       : {os.getenv('GOOGLE_GENAI_USE_VERTEXAI', '(not set)')}")
    print(f"  GOOGLE_CLOUD_PROJECT            : {os.getenv('GOOGLE_CLOUD_PROJECT', '(not set)')}"
          + ("   <- placeholder, ignored" if os.getenv("GOOGLE_CLOUD_PROJECT") and not st["project"] else ""))
    print(f"  GEMINI_MODEL                    : {ai.model_name()}")
    print(f"  -> mode                         : {st['mode'] or 'NOT CONFIGURED'}")
    if not st["mode"]:
        print("\nSet GEMINI_API_KEY=<your key> in backend/.env (no quotes) and run this again.")
        return 1
    ok, msg = _try(st["mode"], st)
    print(f"\nTest call ({st['mode']}): {'OK - ' + msg if ok else 'FAILED - ' + msg}")
    if ok:
        print("\nGemini works. Restart the backend so it picks up the settings.")
        return 0
    if st["key"]:
        other = "vertex_express" if st["mode"] == "api_key" else "api_key"
        ok2, msg2 = _try(other, st)
        print(f"Test call ({other}): {'OK - ' + msg2 if ok2 else 'FAILED - ' + msg2}")
        if ok2:
            print(f"\nYour key works in '{other}' mode. Add this line to backend/.env and restart:\n  GEMINI_AUTH={other}")
            return 0
    print("\nNeither mode worked. Common causes:"
          "\n  - key copied incompletely or revoked -> create a new key"
          "\n  - Vertex AI key: enable the 'Vertex AI API' in the key's Google Cloud project"
          "\n  - model not available for this key -> try GEMINI_MODEL=gemini-2.0-flash"
          "\n  - no internet / firewall")
    return 1


if __name__ == "__main__":
    sys.exit(main())
