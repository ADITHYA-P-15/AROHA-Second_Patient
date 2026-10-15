import json

import pytest

from app.core.config import settings
from app.services import ai


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "gem-key")
    monkeypatch.setattr(settings, "groq_api_key", "groq-key")
    monkeypatch.setattr(settings, "ai_speech_order", "gemma,groq")
    monkeypatch.setattr(settings, "ai_text_order", "groq,gemma")
    ai.reset_breakers()
    yield
    ai.reset_breakers()


def gemma_reply(payload):
    return {"candidates": [{"content": {"parts": [{"text": payload}]}}]}


def groq_speech(text="mujhe paani chahiye", language="hindi", logprob=-0.1):
    return {"text": text, "language": language, "segments": [{"avg_logprob": logprob, "no_speech_prob": 0.01}]}


def test_gemma_is_tried_first_and_a_fenced_json_reply_is_parsed(monkeypatch):
    calls = []
    def post_json(url, headers, payload, timeout):
        calls.append(url)
        assert headers["x-goog-api-key"] == "gem-key" and "inline_data" in json.dumps(payload) and "systemInstruction" not in payload
        assert "responseMimeType" not in payload["generationConfig"]  # Gemma rejects JSON mode on this API
        return gemma_reply('```json\n{"language": "hi", "text": "mujhe paani chahiye", "confidence": 0.9}\n```')
    monkeypatch.setattr(ai, "_post_json", post_json)
    heard = ai.transcribe_audio(b"audio", "audio/webm;codecs=opus")
    assert (heard.provider, heard.language, heard.confidence, heard.text) == ("gemma", "hi", 0.9, "mujhe paani chahiye")
    assert len(calls) == 1 and "gemma" in calls[0]


def test_groq_is_the_fallback_and_a_failed_provider_is_skipped_for_a_while(monkeypatch):
    gemma_calls = []
    def post_json(url, headers, payload, timeout):
        gemma_calls.append(1); raise ai.AIError("HTTP 429")
    def post_multipart(url, headers, data, files, timeout):
        assert url.endswith("/audio/transcriptions") and data["model"] == settings.groq_stt_model and data["response_format"] == "verbose_json"
        assert files["file"][0].endswith(".webm")
        return groq_speech()
    monkeypatch.setattr(ai, "_post_json", post_json); monkeypatch.setattr(ai, "_post_multipart", post_multipart)
    first = ai.transcribe_audio(b"audio", "audio/webm")
    assert first.provider == "groq" and first.language == "hi" and 0.85 < first.confidence <= 0.91
    ai.transcribe_audio(b"audio", "audio/webm")
    assert len(gemma_calls) == 1  # the breaker kept the second request from waiting on Gemma again


def test_no_speech_from_one_provider_falls_through_and_nothing_configured_returns_none(monkeypatch):
    monkeypatch.setattr(ai, "_post_json", lambda *a, **k: gemma_reply('{"language": "en", "text": "", "confidence": 0}'))
    monkeypatch.setattr(ai, "_post_multipart", lambda *a, **k: groq_speech("I feel dizzy", "english", -0.3))
    assert ai.transcribe_audio(b"audio", "audio/ogg").provider == "groq"
    monkeypatch.setattr(settings, "gemini_api_key", ""); monkeypatch.setattr(settings, "groq_api_key", "")
    assert ai.transcribe_audio(b"audio", "audio/ogg") is None and ai.urgency_advisor() is None


def test_unstructured_gemma_reply_is_kept_as_text_without_confidence(monkeypatch):
    monkeypatch.setattr(ai, "_post_json", lambda *a, **k: gemma_reply("I need some water please"))
    heard = ai.transcribe_audio(b"audio", "audio/webm", language_hint="en")
    assert heard.text == "I need some water please" and heard.confidence is None and heard.language == "en"


def test_advisor_uses_groq_then_gemma_and_rejects_out_of_range_answers(monkeypatch):
    order = []
    def groq_chat(system, user):
        order.append("groq"); return '{"level": 4, "reason": "Dizzy after tablet. A doctor should look."}'
    monkeypatch.setattr(ai, "_groq_chat", groq_chat)
    advisor = ai.urgency_advisor()
    assert advisor.advise("dizzy after tablet", {}) == 4 and advisor.provider == "groq" and "doctor" in advisor.reason
    def broken(system, user): raise ai.AIError("HTTP 500")
    monkeypatch.setattr(ai, "_groq_chat", broken)
    monkeypatch.setattr(ai, "_post_json", lambda *a, **k: gemma_reply('{"level": 3, "reason": "Symptom mentioned."}'))
    fallback = ai.urgency_advisor()
    assert fallback.advise("pain", {}) == 3 and fallback.provider == "gemma"
    ai.reset_breakers()
    monkeypatch.setattr(ai, "_post_json", lambda *a, **k: (_ for _ in ()).throw(ai.AIError("HTTP 500")))  # Gemma down too: only Groq's bad answers remain
    for bad in ('{"level": 9}', '{"level": "high"}', '{"level": true}', '{"level": 2.5}', "not json"):
        monkeypatch.setattr(ai, "_groq_chat", lambda s, u, bad=bad: bad)
        assert ai.urgency_advisor().advise("x", {}) is None, bad
        ai.reset_breakers()


def test_language_names_become_codes():
    assert ai.normalise_language("Kannada") == "kn" and ai.normalise_language("te") == "te" and ai.normalise_language("") is None and ai.normalise_language(5) is None


def test_a_verbose_reply_is_read_by_its_last_json_object():
    verbose = 'Input: "Reply with ONLY JSON {"ok": true}"\n* Level for chest pain is high.\n{"level": 4, "reason": "Chest pain."}'
    assert ai._json_object(verbose) == {"level": 4, "reason": "Chest pain."}
    assert ai._json_object("no json here") is None and ai._json_object("") is None


def test_default_order_is_groq_then_gemini_for_speech_and_the_gemini_model_is_used(monkeypatch):
    monkeypatch.setattr(settings, "ai_speech_order", "groq,gemini")
    seen = []
    def post_json(url, headers, payload, timeout):
        seen.append(url); return gemma_reply('{"language": "kn", "text": "ತಲೆ ತಿರುಗುತ್ತಿದೆ", "confidence": 0.8}')
    monkeypatch.setattr(ai, "_post_json", post_json)
    monkeypatch.setattr(ai, "_post_multipart", lambda *a, **k: (_ for _ in ()).throw(ai.AIError("HTTP 429")))
    heard = ai.transcribe_audio(b"audio", "audio/webm")
    assert heard.provider == "gemini" and heard.model == settings.gemini_speech_model and settings.gemini_speech_model in seen[0]
    assert ai.speech_providers() == ["groq", "gemini"]


def test_translation_returns_english_unchanged_and_asks_a_text_model_otherwise(monkeypatch):
    assert ai.translate_to_english("I need water", "en") == "I need water" and ai.translate_to_english("", "hi") is None
    seen = []
    def groq_chat(system, user):
        seen.append(user); return '{"english": "I have a headache and feel dizzy"}'
    monkeypatch.setattr(ai, "_groq_chat", groq_chat)
    assert ai.translate_to_english("मुझे सिर दर्द है और चक्कर आ रहा है", "hi") == "I have a headache and feel dizzy" and "Language: hi" in seen[0]
    monkeypatch.setattr(ai, "_groq_chat", lambda s, u: '{"nope": 1}')
    ai.reset_breakers()
    monkeypatch.setattr(ai, "_post_json", lambda *a, **k: (_ for _ in ()).throw(ai.AIError("HTTP 500")))
    assert ai.translate_to_english("ನನಗೆ ತಲೆ ನೋವು", "kn") is None
