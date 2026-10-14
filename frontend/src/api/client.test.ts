import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from './client';

afterEach(() => vi.unstubAllGlobals());

describe('typed API client', () => {
  it('maps the server error envelope to ApiError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({error:{code:'denied',message:'No access',details:{field:'patient'},request_id:'req-1'}}), {status:403,headers:{'Content-Type':'application/json'}})));
    let actual: unknown;
    try { await api('/api/v1/patients/one'); }
    catch (error) {
      actual=error;
    }
    expect(actual).toBeInstanceOf(ApiError);
    expect(actual).toMatchObject({status:403,code:'denied',message:'No access',details:{field:'patient'}});
  });

  it('adds CSRF and credentials to mutations', async () => {
    const fetchMock=vi.fn().mockResolvedValue(new Response(JSON.stringify({ok:true}), {status:200,headers:{'Content-Type':'application/json'}}));
    vi.stubGlobal('fetch',fetchMock);
    await api('/api/example',{method:'POST',body:JSON.stringify({value:1})});
    const init=fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(init.headers).get('X-Requested-With')).toBe('second-patient');
    expect(init.credentials).toBe('include');
  });
});
