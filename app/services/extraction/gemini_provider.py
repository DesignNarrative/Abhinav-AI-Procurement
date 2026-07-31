import os
import json
import time
import httpx
from fastapi import HTTPException
from app.schemas.document_extraction import DocumentExtractionPayload
from app.services.extraction.base_provider import BaseExtractionProvider
from app.services.extraction.lenient_parser import lenient_parse_and_validate
from app.services.extraction.prompt_helper import get_extraction_prompt

# Transient HTTP status codes worth retrying (Gemini load spikes / rate limits)
_RETRYABLE_STATUS = {429, 500, 503}
_MAX_ATTEMPTS = 4

class GeminiExtractionProvider(BaseExtractionProvider):
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise HTTPException(
                status_code=500,
                detail="GEMINI_API_KEY environment variable not configured."
            )
        self.model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
        self.url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

    def extract(self, text: str, document_uuid: str) -> DocumentExtractionPayload:
        prompt = get_extraction_prompt(text, self.model, document_uuid)

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt
                        }
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json"
            }
        }

        try:
            r = None
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                r = httpx.post(self.url, json=payload, timeout=180.0)
                if r.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
                    # Transient overload — back off and retry.
                    time.sleep(2 * attempt)
                    continue
                break
            if r.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"Gemini API returned error code {r.status_code}: {r.text}"
                )
            
            resp_json = r.json()
            text_response = resp_json['candidates'][0]['content']['parts'][0]['text'].strip()
            
            # Parse and validate against Pydantic schema using lenient parser
            return lenient_parse_and_validate(text_response, self.model, document_uuid)
        except httpx.HTTPError as e:
            raise HTTPException(
                status_code=502,
                detail=f"HTTP connection error to Gemini API: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to extract structured data using Gemini: {str(e)}"
            )
