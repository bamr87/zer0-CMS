// One way to read an openapi-fetch result: its data, or an ApiError carrying
// the platform's error envelope (code, message, per-field details), which
// TanStack Query then holds as the query's or the mutation's error.
import type { ErrorEnvelope } from '@zer0/api';

type Detail = ErrorEnvelope['error']['details'][number];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: Detail[] = [],
  ) {
    super(message);
  }
}

interface Result<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

function envelopeOf(error: unknown): ErrorEnvelope['error'] | undefined {
  return typeof error === 'object' && error !== null && 'error' in error
    ? (error as ErrorEnvelope).error
    : undefined;
}

export async function call<T>(request: Promise<Result<T>>): Promise<T> {
  const { data, error, response } = await request;
  if (error !== undefined || !response.ok || data === undefined) {
    const envelope = envelopeOf(error);
    throw new ApiError(
      response.status,
      envelope?.code ?? 'request.failed',
      envelope?.message ?? (response.statusText || `HTTP ${response.status}`),
      envelope?.details ?? [],
    );
  }
  return data;
}

/** A sentence a person can read: the message, then what each field said. */
export function errorText(error: unknown): string {
  if (!(error instanceof ApiError)) return String(error);
  const fields = error.details.map((d) => (d.field ? `${d.field}: ${d.message}` : d.message));
  return fields.length ? `${error.message} — ${fields.join('; ')}` : error.message;
}
