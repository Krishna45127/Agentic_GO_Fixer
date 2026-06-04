import os
import time
 
from google import genai
from google.genai import errors as genai_errors
 
# Retry settings for transient 503 / UNAVAILABLE errors
_MAX_RETRIES = 4
_BASE_DELAY  = 5   # seconds; doubles each attempt → 5, 10, 20, 40
 
 
def get_gemini_client() -> genai.Client:
    """
    Returns a configured Gemini client.
 
    Raises ValueError immediately if GOOGLE_API_KEY is not set,
    so misconfiguration surfaces at startup rather than mid-run.
    """
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError(
            "GOOGLE_API_KEY is not set.\n"
            "Add it to your .env file:\n"
            "  GOOGLE_API_KEY=your_key_here\n"
            "Get a free key at https://aistudio.google.com/apikey"
        )
    return genai.Client(api_key=api_key)
 
 
def call_with_retry(client: genai.Client, model: str, contents: str):
    """
    Calls client.models.generate_content with exponential backoff.
 
    Retries automatically on 503 UNAVAILABLE (high demand / transient errors).
    All other errors are re-raised immediately.
 
    Returns the raw GenerateContentResponse so callers can run
    extract_text() on it as usual.
    """
    delay = _BASE_DELAY
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return client.models.generate_content(model=model, contents=contents)
        except genai_errors.ServerError as exc:
            if attempt == _MAX_RETRIES:
                raise
            print(
                f"[Gemini] 503 UNAVAILABLE — retrying in {delay}s "
                f"(attempt {attempt}/{_MAX_RETRIES})…"
            )
            time.sleep(delay)
            delay *= 2          # exponential backoff: 5 → 10 → 20 → 40 s
 
 
def extract_text(response) -> str:
    """
    Returns the text from a Gemini GenerateContentResponse.
 
    .text is a convenience property on GenerateContentResponse; it raises
    ValueError if the response was blocked by safety filters. We return an
    empty string in that case so callers always receive a string.
    """
    try:
        return response.text or ""
    except (AttributeError, ValueError):
        return ""