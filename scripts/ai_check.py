"""Check that your AI keys work, with a clear result per provider.

Reads the same settings the app uses (.env or environment variables: GEMINI_API_KEY, GROQ_API_KEY, GEMMA_MODEL ...).
Sends a one-second silent recording and a tiny text question. Nothing real is sent, and nothing is stored.

    python scripts/ai_check.py
"""
import io
import sys
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.services import ai  # noqa: E402


def silent_wav(seconds: float = 1.0) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buffer.getvalue()


def attempt(label, fn):
    started = time.perf_counter()
    try:
        result = fn()
        print(f"  OK    {label}: {result} ({(time.perf_counter() - started) * 1000:.0f} ms)")
        return True
    except Exception as exc:
        print(f"  FAIL  {label}: {type(exc).__name__}: {exc}")
        return False


def main() -> int:
    print("Configured:", ai.status())
    if not (settings.gemini_api_key or settings.groq_api_key):
        print("No keys set. Add GEMINI_API_KEY and/or GROQ_API_KEY to .env (see .env.example)."); return 1
    ok = True
    wav = silent_wav()
    if settings.gemini_api_key:
        print(f"\nGemma via the Gemini API (model '{settings.gemma_model}')")
        def models():
            reply = httpx.get(f"{settings.gemini_base_url.rstrip('/')}/models?pageSize=200", headers={"x-goog-api-key": settings.gemini_api_key}, timeout=20)
            if reply.status_code >= 400: raise ai.AIError(f"HTTP {reply.status_code} (check the key)")
            names = [m["name"].split("/")[-1] for m in reply.json().get("models", [])]
            gemma = [n for n in names if "gemma" in n]
            if settings.gemma_model not in names: raise ai.AIError(f"model not listed. Gemma models on this key: {', '.join(gemma) or 'none'}. Set GEMMA_MODEL to one of them")
            return f"model available ({len(gemma)} Gemma models listed)"
        ok &= attempt("model list", models)
        ok &= attempt("audio in -> text", lambda: ai._gemma_transcribe(wav, "audio/wav", None).__class__.__name__ + " (accepted audio)")
        ok &= attempt("text -> JSON", lambda: ai._json_object(ai._gemma_generate([{"text": 'Reply with ONLY this JSON: {"ok": true}'}])) or (_ for _ in ()).throw(ai.AIError("reply was not JSON")))
    if settings.groq_api_key:
        print(f"\nGroq (speech '{settings.groq_stt_model}', text '{settings.groq_text_model}')")
        ok &= attempt("audio in -> text", lambda: ai._groq_transcribe(wav, "audio/wav", None).__class__.__name__ + " (accepted audio)")
        ok &= attempt("text -> JSON", lambda: ai._json_object(ai._groq_chat("Reply with JSON only.", 'Reply with {"ok": true}')) or (_ for _ in ()).throw(ai.AIError("reply was not JSON")))
    print("\nAll providers working." if ok else "\nSome checks failed. The app still works: failed providers are skipped and voice notes are routed for a person to listen.")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
