import { describe, expect, it } from 'vitest';
import { assistantLine, clock, languageName, pickMime } from './voice.ts';

describe('voice helpers', () => {
  it('picks the first supported recording format', () => {
    expect(pickMime(t => t === 'audio/mp4')).toBe('audio/mp4');
    expect(pickMime(t => t.startsWith('audio/webm'))).toBe('audio/webm;codecs=opus');
    expect(pickMime(() => false)).toBe('');
  });
  it('names languages and formats time', () => {
    expect(languageName('kn')).toBe('Kannada');
    expect(languageName('hi-IN')).toBe('Hindi');
    expect(languageName('xx')).toBe('XX');
    expect(languageName(null)).toBe('');
    expect(clock(65.7)).toBe('1:05');
  });
  it('explains the assistant suggestion without overstating it', () => {
    expect(assistantLine({ suggested_level: null, applied_level: null, suggested_reason: null })).toBe('');
    expect(assistantLine({ suggested_level: 4, applied_level: 4, suggested_reason: 'Sounds unwell.' })).toContain('raised this to “Doctor asked”');
    expect(assistantLine({ suggested_level: 0, applied_level: null, suggested_reason: null })).toContain('already routed it at least that high');
  });
});
