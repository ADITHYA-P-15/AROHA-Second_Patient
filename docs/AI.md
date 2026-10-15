# AI in CareCircle

AI is **optional and advisory**. With no keys the app behaves exactly as before. Where AI is used, the backend rules still decide, and a person still confirms.

## What it does today

| Feature | What happens | AI's role | What it can never do |
|---|---|---|---|
| **Voice notes** | The patient (or a caretaker on their behalf) records up to a minute, in any language. | Turns the audio into text, detects the language, and translates it to English. | Replace the recording. The audio is always kept and playable. |
| **Preview before sending** | After recording, the sender sees the words in the spoken language, the English, and who will be told. They can correct the words and re-check. **Nothing is sent until they confirm.** | Provides the text, translation and suggestion shown in the preview. | Send anything by itself. |
| **Routing from the transcript** | The rules read the spoken text and its English translation, so a mis-heard word in one language can still be caught in the other. | May **raise** the level, with a one-sentence reason. | Lower a level, close a request, or decide who covers a task. |
| **Ambulance button** | A primary contact sees **Call ambulance 108** on requests that reach them. | None. | Place a call. The phone's dialer does; CareCircle records it and tells the rest of the team so nobody calls twice. |

Who is told is decided by the level: 1 caretaker, 2 family, 3 and 4 healthcare team, 5 everyone.

If transcription fails or hears nothing, the sender can type what they said or send the recording as it is. It is routed to the family as "Voice note to review" and shown as "Not transcribed. Please play the recording."

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

- `POST /api/v1/patients/{id}/voice-notes/preview[?language=hi]`: body is the raw audio (`audio/webm`, `ogg`, `mp4`, `mp3`, `wav`), up to `VOICE_MAX_BYTES` (3 MB). Creates a **draft**: transcript, English, and who would be told. Sends nothing.
- `POST /api/v1/voice-notes/{id}/check` `{transcript}`: re-translate and re-route corrected words. Still a preview.
- `POST /api/v1/voice-notes/{id}/send` `{transcript?}`: the confirmation. Only now is a request created. Supports `Idempotency-Key`; confirming twice returns the same request.
- `DELETE /api/v1/voice-notes/{id}`: throw away an unsent draft. Drafts also expire after a day.
- `GET /api/v1/voice-notes/{id}/audio`: playback for people who may read the request (drafts: the sender only).
- `POST /api/v1/incidents/{id}/ambulance`: a primary contact records that they are calling an ambulance; the rest of the team is notified.
- `GET /api/v1/incidents` includes `voice_note` and `ambulance` where there are any.

## Progress report for the professional (`progress_report` feature)

A draft summary of one patient's recorded care over 14, 30 or 60 days, on the Insights page (the **Progress report** button on a patient).

- **Numbers come from the backend** (`services/progress_report.py`): course of treatment from the prescriptions, share of doses given and the change between the first and last half of the period, missed and late doses (and the medicines most missed), appointments kept or missed, help requests and median time to a first response, optional check-ins (pain, mood), and what is being monitored (doses with an outcome, tasks without a confirmed caretaker in the next 7 days, last recorded contact).
- **The model only phrases them.** It receives the numbered facts (no name) and must return sentences that cite fact ids. A sentence is kept only if it cites known facts, uses only numbers found in those facts, contains no clinical vocabulary (diagnosis, condition, recovery, risk, "clinically"), and uses no judgement word ("improved", "better") unless it carries a figure and is not about the person. Rejected sentences are dropped and counted; if none survive, or no AI is configured, the report shows the facts' own sentences. So "adherence rose from 70% to 90%" can appear; "improving clinically" cannot.
- **A draft, never sent.** Nothing is stored or sent anywhere; the professional reads it and can copy it as text. Drafts are rate limited (10 per person per 10 minutes).
- **Check-ins make it more meaningful.** `POST /api/v1/patients/{id}/check-ins` `{pain 0-10?, mood 1-5?, note?}` is optional and quick, recorded by the patient (card on Request Help) or a family member or caretaker. The report quotes counts and averages only. Professionals cannot record check-ins for a patient.

API: `GET /api/v1/patients/{id}/progress-report?days=30` (facts and plain sentences, no AI) and `POST /api/v1/patients/{id}/progress-report/draft` `{days}` (AI phrasing, verified). Professionals on that patient's team only. Switch off with `FEATURES` (remove `progress_report`).

## Next

Caretaker voice handovers, read-aloud medicine instructions, clinician-entered vitals for the report. See the discussion in the project notes.
