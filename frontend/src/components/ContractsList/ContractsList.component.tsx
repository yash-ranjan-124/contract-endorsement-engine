import { useEffect, useState } from 'react'
import { fetchContractPositions } from '../../api'
import type { ContractPosition } from '../../types'
import './ContractsList.style.css'
import type { ContractsListProps, LoadState } from './ContractsList.types'

function formatMoney(value: string): string {
  const [whole, fraction = ''] = value.split('.')
  return `${whole}.${fraction.padEnd(2, '0')}`
}

function statusBadgeClass(status: string): string {
  return status === 'CANCELLED' ? 'badge text-bg-danger' : 'badge text-bg-success'
}

export default function ContractsList({ onSelect }: ContractsListProps) {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    fetchContractPositions(controller.signal)
      .then((contracts) => {
        if (!controller.signal.aborted) {
          setState({ kind: 'ready', contracts })
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return
        }
        setState({
          kind: 'error',
          message: error instanceof Error ? error.message : 'Could not load contracts.',
        })
      })
    return () => controller.abort()
  }, [attempt])

  function retry() {
    setState({ kind: 'loading' })
    setAttempt((count) => count + 1)
  }

  if (state.kind === 'loading') {
    return <p role="status">Loading contracts…</p>
  }

  if (state.kind === 'error') {
    return (
      <div
        className="alert alert-danger d-flex flex-wrap align-items-center justify-content-between gap-2"
        role="alert"
      >
        <span>{state.message}</span>
        <button type="button" className="btn btn-outline-danger btn-sm" onClick={retry}>
          Retry
        </button>
      </div>
    )
  }

  if (state.contracts.length === 0) {
    return (
      <div className="alert alert-info" role="status">
        No contracts found.
      </div>
    )
  }

  return (
    <div className="table-responsive">
      <table className="table table-striped table-hover align-middle">
        <thead>
          <tr>
            <th scope="col">Reference</th>
            <th scope="col">Current insured name</th>
            <th scope="col">Status</th>
            <th scope="col">Current cover period</th>
            <th scope="col">Currency</th>
            <th scope="col" className="text-end">
              Current gross premium
            </th>
          </tr>
        </thead>
        <tbody>
          {state.contracts.map((contract: ContractPosition) => (
            <tr key={contract.mga_reference}>
              <td className="text-nowrap">
                <button
                  type="button"
                  className="btn btn-link p-0 text-start"
                  onClick={() => onSelect(contract.mga_reference)}
                >
                  {contract.mga_reference}
                </button>
              </td>
              <td>{contract.insured_name}</td>
              <td>
                <span className={statusBadgeClass(contract.status)}>{contract.status}</span>
              </td>
              <td className="text-nowrap">
                {contract.inception_date} to {contract.expiry_date}
              </td>
              <td>{contract.currency}</td>
              <td className="text-end contracts-list-money">{formatMoney(contract.gross_premium)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
