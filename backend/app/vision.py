"""Visual quality inspection with Gemini (multimodal).

Gemini looks at a photo of a part and returns a structured defect assessment.
It must describe only what is visible, and say so when the image is unclear or
is not a manufactured part.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .ai import is_configured, make_client, model_name

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024

DefectType = Literal["none", "scratch", "crack", "dent", "contamination", "discoloration", "deformation",
                     "missing_component", "burr", "porosity", "misalignment", "other"]


class InspectionResult(BaseModel):
    defect_detected: bool
    defect_type: DefectType
    severity: Literal["none", "minor", "major", "critical"]
    confidence: float = Field(ge=0, le=1)
    description: str = Field(description="One or two sentences on what is visible")
    visible_evidence: str = Field(description="Where in the image the defect is, and what it looks like")
    recommended_action: str
    image_quality_ok: bool = Field(description="False if blurry, too dark, or not a manufactured part")


PROMPT = """You are a visual quality inspector in a factory.
Inspect the attached photo of a manufactured part and return a structured assessment.
Rules:
- Describe ONLY what is visible in the image. Do not guess about the process or root cause.
- If there is no visible defect, set defect_detected=false, defect_type="none", severity="none".
- If the image is blurry, badly lit, or not a manufactured part, set image_quality_ok=false,
  lower your confidence, and say what is wrong with the image.
- severity: minor = cosmetic; major = likely functional impact; critical = safety or certain failure.
- recommended_action: one practical next step for the line (e.g. quarantine batch, re-inspect, adjust tool).
Context from the operator (may be empty): {context}
"""


class VisionUnavailable(Exception):
    pass


def inspect(image: bytes, mime: str, line: str, part: str, notes: str) -> tuple[InspectionResult, str]:
    if not is_configured():
        raise VisionUnavailable("Visual inspection needs Gemini. Set GEMINI_API_KEY in backend/.env (or Cloud Run env vars) and restart the backend. Check with: python -m app.check_gemini")
    from google import genai
    from google.genai import types

    client = make_client()
    context = f"line={line!r}, part={part!r}, notes={notes!r}"
    resp = client.models.generate_content(
        model=model_name(),
        contents=[types.Part.from_bytes(data=image, mime_type=mime), PROMPT.format(context=context)],
        config=types.GenerateContentConfig(
            response_mime_type="application/json", response_schema=InspectionResult, temperature=0.1),
    )
    result = resp.parsed if isinstance(resp.parsed, InspectionResult) else InspectionResult.model_validate_json(resp.text)
    if not result.defect_detected:
        result.defect_type, result.severity = "none", "none"
    return result, model_name()


def visual_findings(inspections: list[dict]) -> list[dict]:
    """Each defective inspection becomes a finding V<seq> (stable: inspections are append-only)."""
    out = []
    for i in sorted(inspections, key=lambda x: x["seq"]):
        if not i["defect_detected"] or i["severity"] == "none":
            continue
        out.append({
            "id": f"V{i['seq']}",
            "severity": "critical" if i["severity"] in ("major", "critical") else "warning",
            "category": "visual",
            "line": i["line"],
            "date": i["created_at"][:10],
            "title": f"{i['line']}: {i['severity']} {i['defect_type'].replace('_', ' ')} found in photo inspection",
            "metric": "visual_defect",
            "value": round(i["confidence"], 2),
            "threshold": None,
            "evidence": f"{i['description']} Evidence: {i['visible_evidence']} "
                        f"(part: {i['part'] or 'n/a'}; AI confidence {i['confidence']:.0%}).",
        })
    return out
