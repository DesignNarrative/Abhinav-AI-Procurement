"""
Vision OCR — Gemini-based text extraction for scanned PDFs and images.

Used by the Document Intelligence Engine as the OCR engine (Phase 3).
Renders each PDF page (or accepts an image) as a PNG/JPEG and asks the
Gemini vision model to transcribe ALL text exactly, preserving layout.

This reuses the same Gemini REST infrastructure as gemini_provider.py
(GEMINI_API_KEY / GEMINI_MODEL), so no additional local OCR engine
(PaddleOCR / paddlepaddle) is required.
"""

import os
import time
import base64

import httpx
from fastapi import HTTPException


# HTTP status codes that are transient and worth retrying (Gemini load spikes)
_RETRYABLE_STATUS = {429, 500, 503}
_MAX_ATTEMPTS = 4


# Maps image file extension -> MIME type accepted by Gemini inline_data
_EXTENSION_TO_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

_OCR_PROMPT = (
    "You are an OCR engine. Extract ALL text from this document image exactly "
    "as it appears, preserving line breaks, tables, and reading order. "
    "Include every number, code, quantity, rate, and amount. "
    "Output ONLY the raw extracted text with no commentary, no markdown, and no explanations."
)


def _resolve_mime(image_path: str) -> str:
    ext = os.path.splitext(image_path)[1].lower()
    return _EXTENSION_TO_MIME.get(ext, "image/png")


def ocr_images_to_text(image_paths: list) -> str:
    """
    Run Gemini vision OCR on a list of image files and return the combined text.

    Args:
        image_paths : ordered list of PNG/JPEG file paths (one per page).

    Returns:
        Combined extracted text, pages separated by a blank line.

    Raises:
        HTTPException 500: if GEMINI_API_KEY is missing or an image cannot be read.
        HTTPException 502: if the Gemini API returns an error or is unreachable.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="GEMINI_API_KEY environment variable not configured for vision OCR."
        )

    model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )

    page_texts = []

    for image_path in image_paths:
        try:
            with open(image_path, "rb") as f:
                image_bytes = f.read()
        except OSError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to read image for OCR '{image_path}': {str(e)}"
            )

        encoded = base64.b64encode(image_bytes).decode("utf-8")
        mime_type = _resolve_mime(image_path)

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": _OCR_PROMPT},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": encoded
                            }
                        }
                    ]
                }
            ]
        }

        r = None
        last_error = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                r = httpx.post(url, json=payload, timeout=180.0)
            except httpx.HTTPError as e:
                last_error = e
                r = None
                if attempt < _MAX_ATTEMPTS:
                    time.sleep(2 * attempt)
                    continue
                raise HTTPException(
                    status_code=502,
                    detail=f"HTTP connection error to Gemini vision API: {str(e)}"
                )

            if r.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
                # Transient overload — back off and retry.
                time.sleep(2 * attempt)
                continue
            break

        if r is None:
            raise HTTPException(
                status_code=502,
                detail=f"HTTP connection error to Gemini vision API: {str(last_error)}"
            )

        if r.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Gemini vision API returned error code {r.status_code}: {r.text}"
            )

        try:
            resp_json = r.json()
            text_response = (
                resp_json["candidates"][0]["content"]["parts"][0]["text"]
            ).strip()
        except (KeyError, IndexError, ValueError):
            # No text candidate returned for this page — treat as empty page.
            text_response = ""

        if text_response:
            page_texts.append(text_response)

    return "\n\n".join(page_texts).strip()
