export const MAX_SECONDS = 60;
export const LEVEL_NAMES = ['For information', 'Caretakers asked', 'Family asked', 'Healthcare team asked', 'Doctor asked', 'Emergency'];
const LANGUAGES: Record<string, string> = { en: 'English', hi: 'Hindi', kn: 'Kannada', te: 'Telugu', ta: 'Tamil', ml: 'Malayalam', mr: 'Marathi', bn: 'Bengali', gu: 'Gujarati', pa: 'Punjabi', ur: 'Urdu' };

export type VoiceNoteInfo = {
  id: string; status: 'TRANSCRIBED' | 'UNTRANSCRIBED'; transcript: string; language: string | null; confidence: number | null; low_confidence: boolean;
  provider: string | null; suggested_level: number | null; suggested_reason: string | null; applied_level: number | null; audio_url: string; size_bytes: number;
};

export function languageName(code: string | null | undefined): string {
  if (!code) return '';
  return LANGUAGES[code.toLowerCase().slice(0, 2)] ?? code.toUpperCase();
}

/** The first recording format this browser can produce (Chrome/Firefox: webm or ogg, Safari: mp4). */
export function pickMime(isSupported: (type: string) => boolean): string {
  return ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'].find(isSupported) ?? '';
}

export function clock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** One plain sentence about what the assistant did with the level, or '' when it made no suggestion. */
export function assistantLine(note: Pick<VoiceNoteInfo, 'suggested_level' | 'applied_level' | 'suggested_reason'>): string {
  if (note.suggested_level === null) return '';
  const name = LEVEL_NAMES[note.suggested_level] ?? `level ${note.suggested_level}`;
  const reason = note.suggested_reason ? ` ${note.suggested_reason}` : '';
  return note.applied_level !== null
    ? `The assistant raised this to “${name}”.${reason}`
    : `The assistant suggested “${name}”; the rules had already routed it at least that high.${reason}`;
}
