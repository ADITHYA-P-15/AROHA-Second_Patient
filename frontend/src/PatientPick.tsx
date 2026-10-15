import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from './api/client.ts';

type Row = { id: string; name: string };
const KEY = 'carecircle.patient';
const remembered = () => { try { return sessionStorage.getItem(KEY) ?? ''; } catch { return ''; } };
const remember = (id: string) => { try { sessionStorage.setItem(KEY, id); } catch { /* storage unavailable: selection lasts for this page only */ } };

/** Patient selection shared by every patient screen. Honours ?patient= and keeps the choice while moving between pages. */
export function usePatientPick() {
  const patients = useQuery({ queryKey: ['patients'], queryFn: () => api<{ items: Row[] }>('/api/v1/patients') });
  const [params] = useSearchParams();
  const [selected, setSelected] = useState(params.get('patient') || remembered());
  const items = patients.data?.items ?? [];
  const id = items.find(p => p.id === selected)?.id ?? items[0]?.id ?? '';
  const choose = (value: string) => { setSelected(value); remember(value); };
  const name = items.find(p => p.id === id)?.name ?? '';
  const picker = items.length > 1
    ? <label className="md-pick">Patient<select value={id} onChange={e => choose(e.target.value)}>{items.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
    : name ? <p className="md-pick-name"><span>Patient</span><strong>{name}</strong></p> : null;
  return { id, name, picker, patients, loading: patients.isLoading, empty: !patients.isLoading && items.length === 0 };
}
