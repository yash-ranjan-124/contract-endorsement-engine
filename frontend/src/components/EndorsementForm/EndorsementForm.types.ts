import type { Endorsement, EndorsementStatus, EndorsementType } from '../../types'

export type FormValues = {
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

export type EndorsementFormProps = {
  reference: string
  endorsements: Endorsement[]
  disabled: boolean
  onSaved: () => void
}
