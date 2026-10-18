export type ContractPosition = {
  mga_reference: string
  as_at: string
  insured_name: string
  status: string
  inception_date: string
  expiry_date: string
  cancellation_effective_date: string | null
  currency: string
  sum_insured: string
  gross_premium: string
  net_premium: string | null
  our_net_premium: string | null
  applied_endorsements: number[]
}

export type ContractSlip = {
  mga_reference: string
  insured_name: string
  class_of_business: string
  inception_date: string
  expiry_date: string
  currency: string
  sum_insured: string
  gross_premium: string
  brokerage_pct: string
  signed_line_pct: string
  status: string
}

export type Endorsement = {
  number: number
  type: string
  status: string
  effective_date: string
  recorded_date: string
  premium_change: string | null
  changes: Record<string, unknown>
  reason: string
}

export type ContractDetail = {
  slip: ContractSlip
  endorsements: Endorsement[]
  current_position: ContractPosition
}
