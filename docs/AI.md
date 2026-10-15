# AI in CareCircle

AI is **optional and advisory**. With no keys the app behaves exactly as before. Where AI is used, the backend rules still decide, and a person still confirms.

## What it does today

| Feature | What happens | AI's role | What it can never do |
|---|---|---|---|
| **Voice notes** | The patient (or a caretaker on their behalf) records up to a minute, in any language. | Turns the audio into text and detects the language (Groq Whisper, Gemini fallback). | Replace the recording. The audio is always kept and playable. |
| **Urgency suggestion** | The transcript goes through the normal rules first. | May **raise** the routing level, with a one-sentence reason shown to the care team. | Lower a level, close a request, or decide who covers a task. |

If transcription fails or hears nothing, the note is still sent, routed to the family ("Voice note to review"), and shown as "Not transcribed. Please play the recording."

## Providers (measured on real keys, 15 Oct 2026)

| Task | First | Fallback |
|---|---|---|
| Speech to text | **Groq** `whisper-large-v3` | **Gemini** `gemini-flash-lite-latest` (same Google key) |
| Urgency suggestion (text) | **Groq** `openai/gpt-oss-120b` | **Gemma** `gemma-4-31b-it` (same Google key) |

What the tests showed (synthesized clips: "I feel dizzy and my chest hurts" in four languages):

| Model | English | Hindi | Kannada | Telugu | Speed |
|---|---|---|---|---|---|
| Groq `whisper-large-v3` | correct | correct | correct | correct | 0.4 to 0.7 s |
| Groq `whisper-large-v3-turbo` | correct | correct | **wrong (labelled Tamil)** | **wrong (labelled Tamil)** | 0.4 to 0.8 s |
| Gemini `flash-lite` family | correct | correct | not tested | not tested | 2 to 3 s, occasional timeouts |
| Gemma 4 (`26b`, `31b`) | audio **rejected** by the API ("Audio input modality is not enabled") | | | | text works, 4 to 24 s and sometimes HTTP 500 |

Consequences:

- **Gemma cannot transcribe through the Gemini API today**, so Gemma is used for text only (fallback for the urgency suggestion). If Google enables audio for a Gemma model, put `gemma` into `AI_SPEECH_ORDER`.
- Use `whisper-large-v3`, **not** the turbo variant, for Indian languages.
- Text tasks have a short timeout (`AI_TEXT_TIMEOUT_SECONDS`, 8 s) so a slow model never holds up a patient's request. The rules route the note regardless.
- Clips were machine-generated speech. Real elderly speakers, accents and background noise will be harder. Measure again with real recordings.

A provider that fails is skipped for 60 seconds. All of this is settings in `.env`:

```
GEMINI_API_KEY=            GEMMA_MODEL=gemma-4-31b-it      GEMINI_SPEECH_MODEL=gemini-flash-lite-latest
GROQ_API_KEY=              GROQ_STT_MODEL=whisper-large-v3 GROQ_TEXT_MODEL=openai/gpt-oss-120b
AI_SPEECH_ORDER=groq,gemini  AI_TEXT_ORDER=groq,gemma
```

**Check your keys** (sends one second of silence and one tiny text question; nothing real, nothing stored):

```bash
python scripts/ai_check.py
```

It tells you which of your configured models are not available on your key, so you can change them.

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
