import type { ContractDetail as ContractDetailData, ContractPosition, ContractSlip } from '../../types'

export type DetailState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; detail: ContractDetailData }

export type PositionState =
  | { kind: 'loading'; asAt: string }
  | { kind: 'error'; asAt: string; message: string }
  | { kind: 'ready'; position: ContractPosition }

export type PositionRequest = { asAt: string }

export type PositionView =
  | { kind: 'cleared' }
  | { kind: 'loading' }
  | { kind: 'hidden'; message: string }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; position: ContractPosition }

export type ContractDetailProps = {
  reference: string
}

export type PositionPanelProps = {
  view: PositionView
  slip: ContractSlip
  onRetry: () => void
}

export type TermProps = {
  label: string
  value: string
}

export type AmendedTermProps = TermProps & {
  original: string
}
