import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ApiError, createEndorsement, type FieldErrors } from '../api'
import type {
  Endorsement,
  EndorsementCreatePayload,
  EndorsementStatus,
  EndorsementType,
} from '../types'

type FormValues = {
  endorsementNumber: string | null
  type: EndorsementType
  status: EndorsementStatus
  effectiveDate: string
  recordedDate: string
  premiumChange: string
  insuredName: string
  sumInsured: string
  expiryDate: string
  reason: string
}

type EndorsementFormProps = {
  reference: string
  endorsements: Endorsement[]
  disabled: boolean
  onSaved: () => void
}

const TYPE_OPTIONS: { value: EndorsementType; label: string }[] = [
  { value: 'CHANGE_DETAILS', label: 'Change details' },
  { value: 'CHANGE_SUM_INSURED', label: 'Change sum insured' },
  { value: 'PREMIUM_ADJUSTMENT', label: 'Premium adjustment' },
  { value: 'EXTENSION', label: 'Extension' },
  { value: 'CANCELLATION', label: 'Cancellation' },
]

const INITIAL_VALUES: FormValues = {
  endorsementNumber: null,
  type: 'PREMIUM_ADJUSTMENT',
  status: 'DRAFT',
  effectiveDate: '',
  recordedDate: '',
  premiumChange: '',
  insuredName: '',
  sumInsured: '',
  expiryDate: '',
  reason: '',
}

const FORM_FIELDS = new Set([
  'endorsement_number',
  'type',
  'status',
  'effective_date',
  'recorded_date',
  'premium_change',
  'reason',
  'changes',
])

function suggestNumber(endorsements: Endorsement[]): number {
  if (endorsements.length === 0) {
    return 1
  }
  return Math.max(...endorsements.map((endorsement) => endorsement.number)) + 1
}

function parseEndorsementNumber(text: string): number | null {
  const trimmed = text.trim()
  if (!/^\d+$/.test(trimmed)) {
    return null
  }
  const value = Number(trimmed)
  return Number.isSafeInteger(value) && value > 0 ? value : null
}

function typeSpecificKey(type: EndorsementType): 'insured_name' | 'sum_insured' | 'expiry_date' | null {
  switch (type) {
    case 'CHANGE_DETAILS':
      return 'insured_name'
    case 'CHANGE_SUM_INSURED':
      return 'sum_insured'
    case 'EXTENSION':
      return 'expiry_date'
    default:
      return null
  }
}

function validate(values: FormValues, number: number | null): FieldErrors {
  const errors: FieldErrors = {}
  const add = (field: string, message: string) => {
    errors[field] = [...(errors[field] ?? []), message]
  }
  if (number === null) {
    add('endorsement_number', 'Enter a whole number greater than zero.')
  }
  if (!values.effectiveDate) {
    add('effective_date', 'Enter an effective date.')
  }
  if (!values.recordedDate) {
    add('recorded_date', 'Enter a recorded date.')
  }
  if (!values.reason.trim()) {
    add('reason', 'Enter a reason.')
  }
  if (values.type !== 'CANCELLATION' && !values.premiumChange.trim()) {
    add('premium_change', 'Enter a premium change.')
  }
  if (values.type === 'CHANGE_DETAILS' && !values.insuredName.trim()) {
    add('insured_name', 'Enter the new insured name.')
  }
  if (values.type === 'CHANGE_SUM_INSURED' && !values.sumInsured.trim()) {
    add('sum_insured', 'Enter the new sum insured.')
  }
  if (values.type === 'EXTENSION' && !values.expiryDate) {
    add('expiry_date', 'Enter the new expiry date.')
  }
  return errors
}

function changesFor(values: FormValues): Record<string, string> {
  switch (values.type) {
    case 'CHANGE_DETAILS':
      return { insured_name: values.insuredName.trim() }
    case 'CHANGE_SUM_INSURED':
      return { sum_insured: values.sumInsured.trim() }
    case 'EXTENSION':
      return { expiry_date: values.expiryDate }
    default:
      return {}
  }
}

function buildPayload(values: FormValues, number: number): EndorsementCreatePayload {
  return {
    endorsement_number: number,
    type: values.type,
    status: values.status,
    effective_date: values.effectiveDate,
    recorded_date: values.recordedDate,
    premium_change: values.type === 'CANCELLATION' ? null : values.premiumChange.trim(),
    changes: changesFor(values),
    reason: values.reason.trim(),
  }
}

function splitServerErrors(fieldErrors: FieldErrors): { fields: FieldErrors; general: string[] } {
  const fields: FieldErrors = {}
  const general: string[] = []
  for (const [key, messages] of Object.entries(fieldErrors)) {
    if (FORM_FIELDS.has(key)) {
      fields[key] = messages
    } else if (key === 'non_field_errors') {
      general.push(...messages)
    } else {
      general.push(...messages.map((message) => `${key}: ${message}`))
    }
  }
  return { fields, general }
}

function fieldAttributes(id: string, messages: string[], baseClass: string) {
  const invalid = messages.length > 0
  return {
    id,
    className: invalid ? `${baseClass} is-invalid` : baseClass,
    'aria-invalid': invalid,
    'aria-describedby': invalid ? `${id}-feedback` : undefined,
  }
}

function FieldFeedback({ id, messages }: { id: string; messages: string[] }) {
  if (messages.length === 0) {
    return null
  }
  return (
    <div id={`${id}-feedback`} className="invalid-feedback">
      {messages.join(' ')}
    </div>
  )
}

export default function EndorsementForm({
  reference,
  endorsements,
  disabled,
  onSaved,
}: EndorsementFormProps) {
  const [values, setValues] = useState<FormValues>(INITIAL_VALUES)
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [generalErrors, setGeneralErrors] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const submittingRef = useRef(false)
  const mountedRef = useRef(false)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const numberText = values.endorsementNumber ?? String(suggestNumber(endorsements))
  const keyForTypeSpecific = typeSpecificKey(values.type)

  function messagesFor(...keys: string[]): string[] {
    return keys.flatMap((key) => fieldErrors[key] ?? [])
  }

  function setField<K extends keyof FormValues>(field: K, value: FormValues[K]) {
    setValues((current) => ({ ...current, [field]: value }))
  }

  function changeType(type: EndorsementType) {
    setValues((current) => ({ ...current, type }))
    setFieldErrors({})
    setGeneralErrors([])
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submittingRef.current) {
      return
    }
    setFieldErrors({})
    setGeneralErrors([])

    const number = parseEndorsementNumber(numberText)
    const errors = validate(values, number)
    if (number === null || Object.keys(errors).length > 0) {
      setFieldErrors(errors)
      return
    }

    submittingRef.current = true
    setSubmitting(true)
    try {
      await createEndorsement(reference, buildPayload(values, number))
      if (!mountedRef.current) {
        return
      }
      setValues(INITIAL_VALUES)
      onSaved()
    } catch (error) {
      if (!mountedRef.current) {
        return
      }
      if (error instanceof ApiError) {
        const { fields, general } = splitServerErrors(error.fieldErrors)
        setFieldErrors(fields)
        const hasFieldErrors = Object.keys(fields).length > 0
        if (general.length > 0) {
          setGeneralErrors(general)
        } else if (!hasFieldErrors) {
          setGeneralErrors([error.message])
        }
      } else {
        setGeneralErrors(['Could not add the endorsement.'])
      }
    } finally {
      submittingRef.current = false
      if (mountedRef.current) {
        setSubmitting(false)
      }
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate>
      <fieldset disabled={submitting || disabled}>
        {generalErrors.length > 0 && (
          <div className="alert alert-danger" role="alert">
            {generalErrors.map((message) => (
              <div key={message}>{message}</div>
            ))}
          </div>
        )}

        <div className="row g-3">
          <div className="col-12 col-md-4">
            <label htmlFor="endorsement-number" className="form-label">
              Endorsement number
            </label>
            <input
              {...fieldAttributes('endorsement-number', messagesFor('endorsement_number'), 'form-control')}
              type="number"
              min={1}
              step={1}
              inputMode="numeric"
              value={numberText}
              onChange={(event) => setField('endorsementNumber', event.target.value)}
            />
            <FieldFeedback id="endorsement-number" messages={messagesFor('endorsement_number')} />
          </div>

          <div className="col-12 col-md-4">
            <label htmlFor="endorsement-type" className="form-label">
              Type
            </label>
            <select
              {...fieldAttributes(
                'endorsement-type',
                keyForTypeSpecific === null
                  ? [...messagesFor('type'), ...messagesFor('changes')]
                  : messagesFor('type'),
                'form-select',
              )}
              value={values.type}
              onChange={(event) => changeType(event.target.value as EndorsementType)}
            >
              {TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <FieldFeedback
              id="endorsement-type"
              messages={
                keyForTypeSpecific === null
                  ? [...messagesFor('type'), ...messagesFor('changes')]
                  : messagesFor('type')
              }
            />
          </div>

          <div className="col-12 col-md-4">
            <label htmlFor="endorsement-status" className="form-label">
              Status
            </label>
            <select
              {...fieldAttributes('endorsement-status', messagesFor('status'), 'form-select')}
              value={values.status}
              onChange={(event) => setField('status', event.target.value as EndorsementStatus)}
            >
              <option value="DRAFT">Draft</option>
              <option value="AGREED">Agreed</option>
            </select>
            <FieldFeedback id="endorsement-status" messages={messagesFor('status')} />
          </div>

          <div className="col-12 col-md-6">
            <label htmlFor="effective-date" className="form-label">
              Effective date
            </label>
            <input
              {...fieldAttributes('effective-date', messagesFor('effective_date'), 'form-control')}
              type="date"
              value={values.effectiveDate}
              onChange={(event) => setField('effectiveDate', event.target.value)}
            />
            <FieldFeedback id="effective-date" messages={messagesFor('effective_date')} />
          </div>

          <div className="col-12 col-md-6">
            <label htmlFor="recorded-date" className="form-label">
              Recorded date
            </label>
            <input
              {...fieldAttributes('recorded-date', messagesFor('recorded_date'), 'form-control')}
              type="date"
              value={values.recordedDate}
              onChange={(event) => setField('recordedDate', event.target.value)}
            />
            <FieldFeedback id="recorded-date" messages={messagesFor('recorded_date')} />
          </div>

          {values.type === 'CHANGE_DETAILS' && (
            <div className="col-12">
              <label htmlFor="insured-name" className="form-label">
                New insured name
              </label>
              <input
                {...fieldAttributes(
                  'insured-name',
                  [...messagesFor('insured_name'), ...messagesFor('changes')],
                  'form-control',
                )}
                type="text"
                value={values.insuredName}
                onChange={(event) => setField('insuredName', event.target.value)}
              />
              <FieldFeedback
                id="insured-name"
                messages={[...messagesFor('insured_name'), ...messagesFor('changes')]}
              />
            </div>
          )}

          {values.type === 'CHANGE_SUM_INSURED' && (
            <div className="col-12 col-md-6">
              <label htmlFor="sum-insured" className="form-label">
                New sum insured
              </label>
              <input
                {...fieldAttributes(
                  'sum-insured',
                  [...messagesFor('sum_insured'), ...messagesFor('changes')],
                  'form-control',
                )}
                type="text"
                inputMode="decimal"
                value={values.sumInsured}
                onChange={(event) => setField('sumInsured', event.target.value)}
              />
              <FieldFeedback
                id="sum-insured"
                messages={[...messagesFor('sum_insured'), ...messagesFor('changes')]}
              />
            </div>
          )}

          {values.type === 'EXTENSION' && (
            <div className="col-12 col-md-6">
              <label htmlFor="expiry-date" className="form-label">
                New expiry date
              </label>
              <input
                {...fieldAttributes(
                  'expiry-date',
                  [...messagesFor('expiry_date'), ...messagesFor('changes')],
                  'form-control',
                )}
                type="date"
                value={values.expiryDate}
                onChange={(event) => setField('expiryDate', event.target.value)}
              />
              <FieldFeedback
                id="expiry-date"
                messages={[...messagesFor('expiry_date'), ...messagesFor('changes')]}
              />
            </div>
          )}

          <div className="col-12 col-md-6">
            {values.type === 'CANCELLATION' ? (
              <>
                <p className="text-body-secondary mb-0">Return premium is calculated automatically.</p>
                {messagesFor('premium_change').map((message) => (
                  <div key={message} className="invalid-feedback d-block">
                    {message}
                  </div>
                ))}
              </>
            ) : (
              <>
                <label htmlFor="premium-change" className="form-label">
                  Premium change
                </label>
                <input
                  {...fieldAttributes('premium-change', messagesFor('premium_change'), 'form-control')}
                  type="text"
                  inputMode="decimal"
                  placeholder="For example 500.00 or -100.00"
                  value={values.premiumChange}
                  onChange={(event) => setField('premiumChange', event.target.value)}
                />
                <FieldFeedback id="premium-change" messages={messagesFor('premium_change')} />
              </>
            )}
          </div>

          <div className="col-12">
            <label htmlFor="endorsement-reason" className="form-label">
              Reason
            </label>
            <textarea
              {...fieldAttributes('endorsement-reason', messagesFor('reason'), 'form-control')}
              rows={2}
              value={values.reason}
              onChange={(event) => setField('reason', event.target.value)}
            />
            <FieldFeedback id="endorsement-reason" messages={messagesFor('reason')} />
          </div>
        </div>

        <div className="mt-3">
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? 'Adding…' : 'Add endorsement'}
          </button>
        </div>
      </fieldset>
    </form>
  )
}
