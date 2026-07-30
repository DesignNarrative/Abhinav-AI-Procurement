"""
MaterialResearchService — Phase 8 LLM-backed material intelligence.

Answers "what is this material?" for unfamiliar items: typical usage,
alternatives, common brands, indicative market price range and GST%.

Pluggable across the same providers already used for extraction
(EXTRACTION_PROVIDER: gemini / groq / ollama). Failures degrade
gracefully — the endpoint returns an error field rather than raising,
so the UI never breaks.
"""

import os
import json

import httpx

RESEARCH_SCHEMA_HINT = {
    "material_name": "string",
    "category": "string",
    "typical_usage": "string",
    "common_brands": ["string"],
    "alternatives": ["string"],
    "market_price_range": "string (e.g. '₹45-55 per kg')",
    "typical_gst_percent": "number",
    "notes": "string"
}


def _build_prompt(material_name: str) -> str:
    schema = json.dumps(RESEARCH_SCHEMA_HINT, indent=2)
    return (
        "You are a procurement material expert for the Indian construction and "
        "industrial supply market. Provide concise, practical information about "
        f"the material: \"{material_name}\".\n\n"
        "Respond ONLY with a valid JSON object using exactly this schema "
        "(no markdown, no commentary):\n"
        f"{schema}\n\n"
        "If you are unsure about a numeric value, give your best estimate for "
        "the Indian market. Keep text fields short."
    )


def _extract_json(text: str) -> dict:
    text = text.strip()
    # Strip common markdown fences if present
    if text.startswith("```"):
        text = text.split("```", 2)[1] if "```" in text[3:] else text
        text = text.replace("json", "", 1).strip("`").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end + 1]
    return json.loads(text)


class MaterialResearchService:

    @staticmethod
    def research(material_name: str) -> dict:
        provider = os.getenv("EXTRACTION_PROVIDER", "gemini").lower()
        prompt = _build_prompt(material_name)

        try:
            if provider == "groq":
                raw = MaterialResearchService._call_groq(prompt)
            elif provider == "ollama":
                raw = MaterialResearchService._call_ollama(prompt)
            else:
                raw = MaterialResearchService._call_gemini(prompt)

            data = _extract_json(raw)
            data.setdefault("material_name", material_name)
            data["source"] = provider
            return data
        except Exception as e:
            return {
                "material_name": material_name,
                "error": f"Research unavailable: {str(e)}",
                "source": provider
            }

    # -------------------------------------------------
    # Provider calls (mirror the extraction providers)
    # -------------------------------------------------

    @staticmethod
    def _call_gemini(prompt: str) -> str:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not configured.")
        model = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"}
        }
        r = httpx.post(url, json=payload, timeout=60.0)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]

    @staticmethod
    def _call_groq(prompt: str) -> str:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not configured.")
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        r = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0.2
            },
            timeout=60.0
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    @staticmethod
    def _call_ollama(prompt: str) -> str:
        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        model = os.getenv("OLLAMA_MODEL", "llama3")
        r = httpx.post(
            f"{base}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=120.0
        )
        r.raise_for_status()
        return r.json().get("response", "")
