import { useEffect, useState } from 'react'
import { fetchContractDetail, fetchContractPosition } from '../api'
import type {
  ContractDetail as ContractDetailData,
  ContractPosition,
  ContractSlip,
  Endorsement,
} from '../types'

type DetailState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; detail: ContractDetailData }

type PositionState =
  | { kind: 'loading'; asAt: string }
  | { kind: 'error'; asAt: string; message: string }
  | { kind: 'ready'; position: ContractPosition }

type PositionRequest = { asAt: string }

type PositionView =
  | { kind: 'cleared' }
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; position: ContractPosition }

type ContractDetailProps = {
  reference: string
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}

function positionView(
  selectedDate: string,
  state: PositionState,
): PositionView {
  if (selectedDate === '') {
    return { kind: 'cleared' }
  }
  if (state.kind === 'ready' && state.position.as_at === selectedDate) {
    return { kind: 'ready', position: state.position }
  }
  if (state.kind === 'error' && state.asAt === selectedDate) {
    return { kind: 'error', message: state.message }
  }
  return { kind: 'loading' }
}

function applicationStatus(endorsement: Endorsement, position: ContractPosition | null): string {
  if (endorsement.status === 'DRAFT') {
    return 'Not applied'
  }
  if (position === null) {
    return '—'
  }
  return position.applied_endorsements.includes(endorsement.number)
    ? 'Applied'
    : 'Not applied on selected date'
}

export default function ContractDetail({ reference }: ContractDetailProps) {
  const [detailState, setDetailState] = useState<DetailState>({ kind: 'loading' })
  const [detailAttempt, setDetailAttempt] = useState(0)
  const [selectedDate, setSelectedDate] = useState('')
  const [positionState, setPositionState] = useState<PositionState | null>(null)
  const [positionRequest, setPositionRequest] = useState<PositionRequest | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    fetchContractDetail(reference, controller.signal)
      .then((detail) => {
        if (controller.signal.aborted) {
          return
        }
        setSelectedDate(detail.current_position.as_at)
        setPositionState({ kind: 'ready', position: detail.current_position })
        setPositionRequest(null)
        setDetailState({ kind: 'ready', detail })
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return
        }
        setDetailState({
          kind: 'error',
          message: errorMessage(error, 'Could not load contract details.'),
        })
      })
    return () => controller.abort()
  }, [reference, detailAttempt])

  useEffect(() => {
    if (positionRequest === null) {
      return
    }
    const controller = new AbortController()
    fetchContractPosition(reference, positionRequest.asAt, controller.signal)
      .then((position) => {
        if (!controller.signal.aborted) {
          setPositionState({ kind: 'ready', position })
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return
        }
        setPositionState({
          kind: 'error',
          asAt: positionRequest.asAt,
          message: errorMessage(error, 'Could not load the position.'),
        })
      })
    return () => controller.abort()
  }, [reference, positionRequest])

  function retryDetail() {
    setDetailState({ kind: 'loading' })
    setDetailAttempt((count) => count + 1)
  }

  function handleDateChange(value: string) {
    setSelectedDate(value)
    if (value === '') {
      setPositionRequest(null)
      setPositionState(null)
      return
    }
    setPositionRequest({ asAt: value })
    setPositionState({ kind: 'loading', asAt: value })
  }

  function retryPosition() {
    if (selectedDate === '') {
      return
    }
    setPositionRequest({ asAt: selectedDate })
    setPositionState({ kind: 'loading', asAt: selectedDate })
  }

  if (detailState.kind === 'loading') {
    return <p role="status">Loading contract…</p>
  }

  if (detailState.kind === 'error') {
    return (
      <div
        className="alert alert-danger d-flex flex-wrap align-items-center justify-content-between gap-2"
        role="alert"
      >
        <span>{detailState.message}</span>
        <button type="button" className="btn btn-outline-danger btn-sm" onClick={retryDetail}>
          Retry
        </button>
      </div>
    )
  }

  const { detail } = detailState
  const slip = detail.slip
  const view = positionView(selectedDate, positionState ?? { kind: 'loading', asAt: selectedDate })
  const activePosition = view.kind === 'ready' ? view.position : null
  const endorsements = [...detail.endorsements].sort((a, b) => a.number - b.number)

  return (
    <>
      <div className="row g-4">
        <section className="col-12 col-lg-6" aria-labelledby="original-slip-heading">
          <h2 id="original-slip-heading" className="h5">
            Original slip
          </h2>
          <dl className="row mb-0">
            <Term label="Reference" value={slip.mga_reference} />
            <Term label="Class of business" value={slip.class_of_business} />
            <Term label="Insured name" value={slip.insured_name} />
            <Term label="Status" value={slip.status} />
            <Term label="Inception" value={slip.inception_date} />
            <Term label="Expiry" value={slip.expiry_date} />
            <Term label="Currency" value={slip.currency} />
            <Term label="Sum insured" value={slip.sum_insured} />
            <Term label="Gross premium" value={slip.gross_premium} />
            <Term label="Brokerage percentage" value={slip.brokerage_pct} />
            <Term label="Signed line percentage" value={slip.signed_line_pct} />
          </dl>
        </section>

        <section className="col-12 col-lg-6" aria-labelledby="position-heading">
          <h2 id="position-heading" className="h5">
            Position on selected date
          </h2>
          <div className="mb-3">
            <label htmlFor="position-date" className="form-label">
              Position date
            </label>
            <input
              id="position-date"
              type="date"
              className="form-control"
              value={selectedDate}
              onChange={(event) => handleDateChange(event.target.value)}
            />
          </div>
          <PositionPanel view={view} slip={slip} onRetry={retryPosition} />
        </section>
      </div>

      <section className="mt-4" aria-labelledby="endorsements-heading">
        <h2 id="endorsements-heading" className="h5">
          Endorsement history
        </h2>
        {endorsements.length === 0 ? (
          <p className="text-body-secondary">No endorsements found.</p>
        ) : (
          <div className="table-responsive">
            <table className="table table-sm table-striped align-middle">
              <thead>
                <tr>
                  <th scope="col">Number</th>
                  <th scope="col">Type</th>
                  <th scope="col">Status</th>
                  <th scope="col">Effective date</th>
                  <th scope="col">Recorded date</th>
                  <th scope="col" className="text-end">
                    Premium change
                  </th>
                  <th scope="col">Reason</th>
                  <th scope="col">Application status</th>
                </tr>
              </thead>
              <tbody>
                {endorsements.map((endorsement) => (
                  <tr key={endorsement.number}>
                    <td>{endorsement.number}</td>
                    <td>{endorsement.type}</td>
                    <td>{endorsement.status}</td>
                    <td className="text-nowrap">{endorsement.effective_date}</td>
                    <td className="text-nowrap">{endorsement.recorded_date}</td>
                    <td className="text-end money">{endorsement.premium_change ?? '—'}</td>
                    <td>{endorsement.reason}</td>
                    <td className="text-nowrap">
                      {applicationStatus(endorsement, activePosition)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  )
}

function PositionPanel({
  view,
  slip,
  onRetry,
}: {
  view: PositionView
  slip: ContractSlip
  onRetry: () => void
}) {
  if (view.kind === 'cleared') {
    return <p className="text-body-secondary mb-0">Select a date to view the position.</p>
  }

  if (view.kind === 'loading') {
    return <p role="status">Loading position…</p>
  }

  if (view.kind === 'error') {
    return (
      <div
        className="alert alert-danger d-flex flex-wrap align-items-center justify-content-between gap-2"
        role="alert"
      >
        <span>{view.message}</span>
        <button type="button" className="btn btn-outline-danger btn-sm" onClick={onRetry}>
          Retry
        </button>
      </div>
    )
  }

  const position = view.position
  return (
    <dl className="row mb-0">
      <AmendedTerm label="Insured name" value={position.insured_name} original={slip.insured_name} />
      <AmendedTerm label="Status" value={position.status} original={slip.status} />
      <AmendedTerm label="Inception" value={position.inception_date} original={slip.inception_date} />
      <AmendedTerm label="Expiry" value={position.expiry_date} original={slip.expiry_date} />
      <AmendedTerm label="Currency" value={position.currency} original={slip.currency} />
      <AmendedTerm label="Sum insured" value={position.sum_insured} original={slip.sum_insured} />
      <AmendedTerm label="Gross premium" value={position.gross_premium} original={slip.gross_premium} />
      <Term label="Net premium" value={position.net_premium ?? '—'} />
      <Term label="Our net premium" value={position.our_net_premium ?? '—'} />
      {position.cancellation_effective_date !== null && (
        <Term label="Cancellation effective date" value={position.cancellation_effective_date} />
      )}
      <Term
        label="Applied endorsements"
        value={
          position.applied_endorsements.length === 0
            ? 'None'
            : position.applied_endorsements.join(', ')
        }
      />
    </dl>
  )
}

function Term({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="col-sm-5">{label}</dt>
      <dd className="col-sm-7">{value}</dd>
    </>
  )
}

function AmendedTerm({
  label,
  value,
  original,
}: {
  label: string
  value: string
  original: string
}) {
  const changed = original !== value
  return (
    <>
      <dt className="col-sm-5">{label}</dt>
      <dd className={changed ? 'col-sm-7 bg-warning-subtle' : 'col-sm-7'}>
        {value}
        {changed && <span className="badge text-bg-warning ms-2">Changed</span>}
      </dd>
    </>
  )
}
