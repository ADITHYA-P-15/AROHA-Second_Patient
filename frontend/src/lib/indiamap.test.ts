import { describe, expect, it } from 'vitest';
import { TILES, mapSize, sectorLine, sectorOfState, tileBox, tileState } from './indiamap.ts';

describe('India sector map', () => {
  it('has one tile per state or territory, none overlapping', () => {
    expect(new Set(TILES.map(t => t.state)).size).toBe(TILES.length);
    expect(new Set(TILES.map(t => `${t.col},${t.row}`)).size).toBe(TILES.length);
    expect(new Set(TILES.map(t => t.code)).size).toBe(TILES.length);
  });
  it('colours tiles from the server sector map', () => {
    const map = sectorOfState([{ code: 'SOUTH', states: ['Karnataka', 'Kerala'] }, { code: 'NORTH', states: ['Delhi'] }]);
    expect(map['Karnataka']).toBe('SOUTH');
    expect(map['Delhi']).toBe('NORTH');
    expect(map['Goa']).toBeUndefined();
  });
  it('highlights the hovered or selected sector and dims the rest', () => {
    expect(tileState('SOUTH', '', '')).toBe('normal');
    expect(tileState('SOUTH', 'SOUTH', '')).toBe('active');
    expect(tileState('NORTH', 'SOUTH', '')).toBe('dim');
    expect(tileState('NORTH', 'SOUTH', 'NORTH')).toBe('active');  // hover previews another sector
    expect(tileState(undefined, 'SOUTH', '')).toBe('none');
  });
  it('lays tiles on a grid and sizes the drawing', () => {
    expect(tileBox({ col: 0, row: 0 })).toEqual({ x: 0, y: 0, w: 62, h: 42 });
    expect(tileBox({ col: 2, row: 1 })).toEqual({ x: 136, y: 48, w: 62, h: 42 });
    expect(mapSize()).toEqual({ width: 9 * 68 - 6, height: 9 * 48 - 6 });
    expect(sectorLine({ caretakers: 1, agency_count: 3 })).toBe('1 caretaker · 3 agencies');
  });
});
