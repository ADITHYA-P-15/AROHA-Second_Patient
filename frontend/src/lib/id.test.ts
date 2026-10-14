import { describe, expect, it } from 'vitest';
import { newId } from './id';

describe('newId', () => {
  it('falls back to getRandomValues when randomUUID is unavailable (plain-HTTP LAN)', () => {
    const id = newId({ getRandomValues: <T extends ArrayBufferView | null>(array: T) => { new Uint8Array((array as unknown as Uint8Array).buffer).fill(0xab); return array; } });
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });
  it('uses randomUUID when present', () => {
    expect(newId({ getRandomValues: a => a, randomUUID: () => 'fixed-id' })).toBe('fixed-id');
  });
});
