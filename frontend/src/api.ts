import type {
  ContractDetail,
  ContractPosition,
  Endorsement,
  EndorsementCreatePayload,
} from './types'

export type FieldErrors = Record<string, string[]>

export class ApiError extends Error {
  readonly fieldErrors: FieldErrors

  constructor(message: string, fieldErrors: FieldErrors = {}) {
    super(message)
    this.name = 'ApiError'
    this.fieldErrors = fieldErrors
  }
}

async function getJson<T>(url: string, signal: AbortSignal, description: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, {
      headers: { Accept: 'application/json' },
      signal,
    })
  } catch (error) {
    if (signal.aborted) {
      throw error
    }
    throw new Error('Could not reach the server. Check that the backend is running.')
  }

  if (!response.ok) {
    throw new Error(`Could not load ${description} (HTTP ${response.status}).`)
  }
  return (await response.json()) as T
}

function toFieldErrors(body: unknown): FieldErrors {
  if (typeof body !== 'object' || body === null || Array.isArray(body)) {
    return {}
  }
  const fieldErrors: FieldErrors = {}
  for (const [field, messages] of Object.entries(body)) {
    const list = Array.isArray(messages) ? messages : [messages]
    fieldErrors[field] = list.map((message) => String(message))
  }
  return fieldErrors
}

export function fetchContractPositions(signal: AbortSignal): Promise<ContractPosition[]> {
  return getJson<ContractPosition[]>('/api/contracts/', signal, 'contracts')
}

export function fetchContractDetail(reference: string, signal: AbortSignal): Promise<ContractDetail> {
  return getJson<ContractDetail>(
    `/api/contracts/${encodeURIComponent(reference)}/`,
    signal,
    'contract details',
  )
}

export function fetchContractPosition(
  reference: string,
  asAt: string,
  signal: AbortSignal,
): Promise<ContractPosition> {
  const query = new URLSearchParams({ as_at: asAt })
  return getJson<ContractPosition>(
    `/api/contracts/${encodeURIComponent(reference)}/position/?${query.toString()}`,
    signal,
    'position',
  )
}

export async function createEndorsement(
  reference: string,
  payload: EndorsementCreatePayload,
): Promise<Endorsement> {
  let response: Response
  try {
    response = await fetch(`/api/contracts/${encodeURIComponent(reference)}/endorsements/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      body: JSON.stringify(payload),
    })
  } catch {
    throw new ApiError('Could not reach the server. Check that the backend is running.')
  }

  if (response.status === 201) {
    return (await response.json()) as Endorsement
  }

  if (response.status === 400) {
    const body: unknown = await response.json().catch(() => null)
    throw new ApiError('Please correct the highlighted fields.', toFieldErrors(body))
  }

  throw new ApiError(`Could not add the endorsement (HTTP ${response.status}).`)
}
