export type ApiErrorBody = { error: { code: string; message: string; details: unknown; request_id: string } };
export class ApiError extends Error { constructor(public status: number, public code: string, message: string, public details: unknown) { super(message); } }
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (!['GET', 'HEAD', 'OPTIONS'].includes((options.method ?? 'GET').toUpperCase())) headers.set('X-Requested-With', 'second-patient');
  if (options.body) headers.set('Content-Type', 'application/json');
  const response = await fetch(path, { ...options, headers, credentials: 'include' });
  if (response.status === 204) return undefined as T;
  const body = await response.json();
  if (!response.ok) { const e = (body as ApiErrorBody).error; throw new ApiError(response.status, e?.code ?? 'unknown', e?.message ?? 'Request failed', e?.details); }
  return body as T;
}
