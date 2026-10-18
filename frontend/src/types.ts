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
