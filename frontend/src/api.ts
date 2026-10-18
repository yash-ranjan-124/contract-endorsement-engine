import type { ContractDetail, ContractPosition } from './types'

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
