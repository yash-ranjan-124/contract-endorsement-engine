import type { ContractPosition } from '../../types'

export type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; contracts: ContractPosition[] }

export type ContractsListProps = {
  onSelect: (reference: string) => void
}
