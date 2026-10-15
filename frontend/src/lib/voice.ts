export const MAX_SECONDS = 60;
export const LEVEL_NAMES = ['For information', 'Caretakers asked', 'Family asked', 'Healthcare team asked', 'Doctor asked', 'Emergency'];
const LANGUAGES: Record<string, string> = { en: 'English', hi: 'Hindi', kn: 'Kannada', te: 'Telugu', ta: 'Tamil', ml: 'Malayalam', mr: 'Marathi', bn: 'Bengali', gu: 'Gujarati', pa: 'Punjabi', ur: 'Urdu' };

export type VoiceNoteInfo = {
  id: string; status: 'TRANSCRIBED' | 'UNTRANSCRIBED'; transcript: string; english?: string; edited?: boolean; language: string | null; confidence: number | null; low_confidence: boolean;
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

export type Routing = {
  level: number; level_name: string; emergency: boolean; no_recipients: boolean; reason: string | null;
  notify: { role: string; label: string; names: string[] }[];
  suggested_level: number | null; suggested_reason: string | null; applied_level: number | null; assistant: string | null;
};
export type VoicePreview = VoiceNoteInfo & { patient_id: string; heard: boolean; routing: Routing; english: string };

/** "Caretaker: Savitha · Family: Anita Iyer, Karthik Iyer" */
export function notifyLine(routing: Pick<Routing, 'notify'>): string {
  return routing.notify.map(n => (n.names.length ? `${n.label}: ${n.names.join(', ')}` : n.label)).join(' · ');
}

/** One plain sentence for the person about to send. */
export function routingHeadline(routing: Pick<Routing, 'level' | 'emergency' | 'notify'>): string {
  const who = routing.notify.map(n => n.label.toLowerCase());
  const list = who.length > 1 ? `${who.slice(0, -1).join(', ')} and ${who[who.length - 1]}` : who[0] ?? 'your care team';
  if (routing.emergency) return `This sounds urgent. The ${list} will all be told at once.`;
  return `This will go to the ${list}.`;
}

/** True when the text was edited after the last check, so the preview shown no longer matches it. */
export const isStale = (current: string, checked: string): boolean => current.trim() !== checked.trim();
