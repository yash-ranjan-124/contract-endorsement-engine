import type { ContractPosition } from './types'

export async function fetchContractPositions(signal: AbortSignal): Promise<ContractPosition[]> {
  let response: Response
  try {
    response = await fetch('/api/contracts/', {
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
    throw new Error(`Could not load contracts (HTTP ${response.status}).`)
  }
  return (await response.json()) as ContractPosition[]
}
