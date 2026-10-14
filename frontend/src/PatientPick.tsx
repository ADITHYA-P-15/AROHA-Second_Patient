import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from './api/client.ts';

type Row = { id: string; name: string };

/** Patient selection shared by the care-feed screens (honours ?patient=). */
export function usePatientPick() {
  const patients = useQuery({ queryKey: ['patients'], queryFn: () => api<{ items: Row[] }>('/api/v1/patients') });
  const [params] = useSearchParams();
  const [selected, setSelected] = useState(params.get('patient') ?? '');
  const items = patients.data?.items ?? [];
  const id = items.find(p => p.id === selected)?.id ?? items[0]?.id ?? '';
  const picker = <label className="md-pick">Patient<select value={id} onChange={e => setSelected(e.target.value)}>{items.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>;
  return { id, picker, loading: patients.isLoading, empty: !patients.isLoading && items.length === 0 };
}
