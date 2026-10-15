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
        def models():
            reply = httpx.get(f"{settings.gemini_base_url.rstrip('/')}/models?pageSize=200", headers={"x-goog-api-key": settings.gemini_api_key}, timeout=20)
            if reply.status_code >= 400: raise ai.AIError(f"HTTP {reply.status_code} (check the key)")
            names = {m["name"].split("/")[-1] for m in reply.json().get("models", [])}
            missing = [m for m in {settings.gemma_model, settings.gemini_speech_model} if m not in names]
            if missing: raise ai.AIError(f"not available on this key: {', '.join(missing)}. Available: {', '.join(sorted(n for n in names if 'gemma' in n or 'gemini' in n))[:600]}")
            return "configured models are available"
        print("\nGoogle key")
        ok &= attempt("model list", models)
    checks = {"gemma": ("Gemma audio", ai._gemma_transcribe, settings.gemma_model), "gemini": ("Gemini audio", ai._gemini_transcribe, settings.gemini_speech_model),
              "groq": ("Groq Whisper audio", ai._groq_transcribe, settings.groq_stt_model)}
    print("\nSpeech to text, in your order:", ", ".join(ai.speech_providers()) or "none")
    for provider in ai.speech_providers():
        label, fn, model = checks[provider]
        ok &= attempt(f"{label} ({model})", lambda fn=fn: fn(wav, "audio/wav", None).__class__.__name__ + " (accepted audio)")
    print("\nText tasks (urgency suggestion), in your order:", ", ".join(ai.text_providers()) or "none")
    for provider in ai.text_providers():
        model = settings.groq_text_model if provider == "groq" else settings.gemma_model if provider == "gemma" else settings.gemini_speech_model
        def ask(provider=provider):
            raw = ai._groq_chat("Reply with JSON only.", 'Reply with {"ok": true}') if provider == "groq" else ai._gemma_generate([{"text": 'Reply with ONLY this JSON: {"ok": true}'}], None if provider == "gemma" else settings.gemini_speech_model, settings.ai_text_timeout_seconds)
            return ai._json_object(raw) or (_ for _ in ()).throw(ai.AIError("reply was not JSON"))
        ok &= attempt(f"{provider} ({model})", ask)
    print("\nAll providers working." if ok else "\nSome checks failed. The app still works: failed providers are skipped and voice notes are routed for a person to listen.")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
