from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from contracts.models import Endorsement

ONE = Decimal("1")
HUNDRED = Decimal("100")
CENT = Decimal("0.01")


def _round_money(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_position(contract, endorsements, as_at):
    position = {
        "mga_reference": contract.mga_reference,
        "as_at": as_at,
        "insured_name": contract.insured_name,
        "status": contract.status,
        "inception_date": contract.inception_date,
        "expiry_date": contract.expiry_date,
        "cancellation_effective_date": None,
        "currency": contract.currency,
        "sum_insured": contract.sum_insured,
        "gross_premium": contract.gross_premium,
        "net_premium": None,
        "our_net_premium": None,
        "applied_endorsements": [],
    }

    gross = contract.gross_premium
    for endorsement in _applicable_endorsements(contract, endorsements, as_at):
        if endorsement.premium_change is None:
            raise ValueError(
                f"Applicable endorsement {endorsement.endorsement_number} has no "
                "premium_change; its refund must be set before the position is calculated."
            )
        _apply_changes(position, endorsement)
        gross += endorsement.premium_change
        position["applied_endorsements"].append(endorsement.endorsement_number)

    gross = _round_money(gross)
    raw_net = gross * (ONE - contract.brokerage_pct / HUNDRED)
    position["gross_premium"] = gross
    position["net_premium"] = _round_money(raw_net)
    position["our_net_premium"] = _round_money(raw_net * contract.signed_line_pct / HUNDRED)
    return position


def _applicable_endorsements(contract, endorsements, as_at):
    if as_at < contract.inception_date:
        return []
    selected = [
        endorsement
        for endorsement in endorsements
        if endorsement.status == Endorsement.Status.AGREED
        and endorsement.effective_date <= as_at
    ]
    return sorted(selected, key=lambda endorsement: endorsement.endorsement_number)


def _apply_changes(position, endorsement):
    changes = endorsement.changes
    if endorsement.type == Endorsement.Type.CHANGE_DETAILS:
        position["insured_name"] = changes["insured_name"]
    elif endorsement.type == Endorsement.Type.CHANGE_SUM_INSURED:
        position["sum_insured"] = _round_money(Decimal(str(changes["sum_insured"])))
    elif endorsement.type == Endorsement.Type.EXTENSION:
        position["expiry_date"] = date.fromisoformat(changes["expiry_date"])
    elif endorsement.type == Endorsement.Type.CANCELLATION:
        position["status"] = "CANCELLED"
        position["cancellation_effective_date"] = endorsement.effective_date
        position["expiry_date"] = endorsement.effective_date - timedelta(days=1)
