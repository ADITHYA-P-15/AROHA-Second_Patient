import { describe, expect, it } from 'vitest';
import { DEFAULT_PREFS, ago, freshOnes, highest, loadPrefs, savePrefs, shouldPopUp, staysUntilDismissed, tabTitle, type AppNotification } from './notify.ts';

const n = (over: Partial<AppNotification>): AppNotification => ({ id: 'a', patient_id: 'p', kind: 'STATUS', severity: 'LOW', title: 't', body: '', requires_ack: false, channel: 'ALERT', created_at: '2026-10-15T10:00:00Z', ...over });

describe('what pops up', () => {
  it('shows everything on "all" and only important ones otherwise', () => {
    expect(shouldPopUp(n({ severity: 'LOW' }), { ...DEFAULT_PREFS, level: 'all' })).toBe(true);
    expect(shouldPopUp(n({ severity: 'LOW' }), { ...DEFAULT_PREFS, level: 'important' })).toBe(false);
    expect(shouldPopUp(n({ severity: 'MEDIUM' }), { ...DEFAULT_PREFS, level: 'important' })).toBe(true);
    expect(shouldPopUp(n({ severity: 'LOW', requires_ack: true }), { ...DEFAULT_PREFS, level: 'important' })).toBe(true);
  });
  it('keeps urgent alerts until dismissed', () => {
    expect(staysUntilDismissed(n({ severity: 'HIGH' }))).toBe(true);
    expect(staysUntilDismissed(n({ severity: 'LOW', requires_ack: true }))).toBe(true);
    expect(staysUntilDismissed(n({ severity: 'MEDIUM' }))).toBe(false);
  });
});

describe('new notifications', () => {
  it('returns only unseen, unread ones, oldest first', () => {
    const items = [n({ id: 'c', created_at: '2026-10-15T10:03:00Z' }), n({ id: 'b', created_at: '2026-10-15T10:01:00Z' }), n({ id: 'a' }), n({ id: 'd', read_at: '2026-10-15T10:04:00Z' })];
    expect(freshOnes(items, new Set(['a'])).map(x => x.id)).toEqual(['b', 'c']);
  });
  it('finds the highest severity', () => {
    expect(highest([n({ severity: 'LOW' }), n({ severity: 'HIGH' })])).toBe('HIGH');
    expect(highest([n({ severity: 'LOW' })])).toBe('LOW');
    expect(highest([])).toBeNull();
  });
});

describe('small helpers', () => {
  it('writes relative time and the tab title', () => {
    const now = new Date('2026-10-15T10:10:00Z');
    expect(ago('2026-10-15T10:09:40Z', now)).toBe('just now');
    expect(ago('2026-10-15T09:55:00Z', now)).toBe('15 min ago');
    expect(ago('2026-10-15T07:10:00Z', now)).toBe('3 h ago');
    expect(tabTitle('CareCircle', 0)).toBe('CareCircle');
    expect(tabTitle('CareCircle', 3)).toBe('(3) CareCircle');
    expect(tabTitle('CareCircle', 250)).toBe('(99+) CareCircle');
  });
  it('stores preferences and survives broken storage', () => {
    const store: Record<string, string> = {};
    const storage = { getItem: (k: string) => store[k] ?? null, setItem: (k: string, v: string) => { store[k] = v; } };
    savePrefs({ level: 'important', sound: false, desktop: true }, storage);
    expect(loadPrefs(storage)).toEqual({ level: 'important', sound: false, desktop: true });
    expect(loadPrefs({ getItem: () => { throw new Error('blocked'); } })).toEqual(DEFAULT_PREFS);
    expect(loadPrefs({ getItem: () => 'not json' })).toEqual(DEFAULT_PREFS);
  });
});
