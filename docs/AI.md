# AI in CareCircle

AI is **optional and advisory**. With no keys the app behaves exactly as before. Where AI is used, the backend rules still decide, and a person still confirms.

## What it does today

| Feature | What happens | AI's role | What it can never do |
|---|---|---|---|
| **Voice notes** | The patient (or a caretaker on their behalf) records up to a minute, in any language. | Turns the audio into text and detects the language. | Replace the recording. The audio is always kept and playable. |
| **Urgency suggestion** | The transcript goes through the normal rules first. | May **raise** the routing level, with a one-sentence reason shown to the care team. | Lower a level, close a request, or decide who covers a task. |

If transcription fails or hears nothing, the note is still sent, routed to the family ("Voice note to review"), and shown as "Not transcribed. Please play the recording."

## Providers

| Task | First | Fallback |
|---|---|---|
| Speech to text | **Gemma** (Gemini API key) | **Groq** (hosted Whisper) |
| Urgency suggestion (text) | **Groq** (Llama) | **Gemma** |

A provider that fails is skipped for 60 seconds, so a quota error never makes a patient wait. Order and models are settings (`.env`):

```
GEMINI_API_KEY=            GEMMA_MODEL=gemma-3n-e4b-it
GROQ_API_KEY=              GROQ_STT_MODEL=whisper-large-v3-turbo   GROQ_TEXT_MODEL=llama-3.3-70b-versatile
AI_SPEECH_ORDER=gemma,groq AI_TEXT_ORDER=groq,gemma
```

**Check your keys** (sends one second of silence and one tiny text question; nothing real, nothing stored):

```bash
python scripts/ai_check.py
```

It also lists the Gemma models your key can use. Gemma audio on the Gemini API is not guaranteed for every model or key. If the check reports it, set `GEMMA_MODEL` to a listed one, or let Groq carry speech.

## Safety and privacy

- Keys live only on the server (`.env`, git-ignored). The browser never sees them.
- Audio and transcripts of a real patient go to Google and Groq when keys are set. Use fictional data for demos, and get consent and set a retention rule before real use.
- Every note stores which provider and model produced the transcript and the suggestion.
- A confidence badge ("The transcript may be wrong. Please play the recording.") appears when a provider reports low confidence or none. Gemma's confidence is self-reported, so treat it as a hint.
- The suggestion step ignores instructions inside the message, and since it can only raise a level, a manipulated message cannot lower anything.
- Accuracy for Hindi, Kannada and Telugu, elderly speech and background noise is **not yet measured**. Record about 20 clips per language and compare providers before claiming accuracy.

## API

- `POST /api/v1/patients/{id}/voice-notes[?language=hi]`: body is the raw audio (`audio/webm`, `ogg`, `mp4`, `mp3`, `wav`), up to `VOICE_MAX_BYTES` (3 MB). Supports `Idempotency-Key`. Returns the incident plus `voice_note`.
- `GET /api/v1/voice-notes/{id}/audio`: playback for people who may read the request.
- `GET /api/v1/incidents` includes `voice_note` where there is one. `GET /api/v1/meta` reports which providers are configured.

## Next

Progress reports for professionals, caretaker voice handovers, read-aloud medicine instructions. See the discussion in the project notes.
