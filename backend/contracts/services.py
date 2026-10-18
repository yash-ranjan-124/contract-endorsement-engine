from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from contracts.models import Contract, Endorsement, _normalize_money

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
CENT = Decimal("0.01")

_SUM_INSURED_FIELD = Contract._meta.get_field("sum_insured")
SUM_INSURED_LIMIT = (
    Decimal(10) ** (_SUM_INSURED_FIELD.max_digits - _SUM_INSURED_FIELD.decimal_places)
    - Decimal(10) ** -_SUM_INSURED_FIELD.decimal_places
)
INSURED_NAME_MAX_LENGTH = Contract._meta.get_field("insured_name").max_length
DATE_FORMAT_MESSAGE = "expiry_date must be a date in YYYY-MM-DD format."
NEGATIVE_PRE_CANCELLATION_GROSS = "Pre-cancellation gross premium cannot be negative."
CREATABLE_FIELDS = (
    "endorsement_number",
    "type",
    "status",
    "effective_date",
    "recorded_date",
    "premium_change",
    "changes",
    "reason",
)


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


def calculate_cancellation_premium_change(contract, endorsements, effective_date):
    if effective_date < contract.inception_date:
        raise ValueError("Cancellation effective date cannot be before inception.")
    history = [
        endorsement
        for endorsement in endorsements
        if endorsement.type != Endorsement.Type.CANCELLATION
    ]
    position = calculate_position(contract, history, effective_date)
    gross = position["gross_premium"]
    expiry = position["expiry_date"]
    if effective_date > expiry:
        raise ValueError(
            "Cancellation effective date cannot be after the pre-cancellation expiry."
        )
    if gross < ZERO:
        raise ValueError(NEGATIVE_PRE_CANCELLATION_GROSS)
    if gross == ZERO:
        return Decimal("0.00")
    total_days = (expiry - contract.inception_date).days + 1
    unused_days = (expiry - effective_date).days + 1
    refund = gross * Decimal(unused_days) / Decimal(total_days)
    return -_round_money(refund)


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


def validate_endorsement_changes(endorsement_type, changes):
    if endorsement_type not in Endorsement.Type.values:
        raise ValidationError({"type": "Unknown endorsement type."})
    if not isinstance(changes, dict):
        raise _changes_error("Changes must be a JSON object.")

    expected_keys, normalize = _CHANGE_RULES[endorsement_type]
    problems = [
        f"Missing required key '{key}'."
        for key in expected_keys
        if key not in changes
    ] + [
        f"Unexpected key '{key}' for this endorsement type."
        for key in changes
        if key not in expected_keys
    ]
    if problems:
        raise ValidationError({"changes": problems})
    return normalize(changes)


def _changes_error(message):
    return ValidationError({"changes": message})


def _normalize_insured_name(changes):
    name = changes["insured_name"]
    if not isinstance(name, str):
        raise _changes_error("insured_name must be a string.")
    name = name.strip()
    if not name:
        raise _changes_error("insured_name must not be blank.")
    if len(name) > INSURED_NAME_MAX_LENGTH:
        raise _changes_error(
            f"insured_name must be at most {INSURED_NAME_MAX_LENGTH} characters."
        )
    return {"insured_name": name}


def _normalize_sum_insured(changes):
    try:
        amount = _normalize_money(changes["sum_insured"])
    except ValidationError as exc:
        raise _changes_error(f"sum_insured: {exc.messages[0]}")
    if amount > SUM_INSURED_LIMIT:
        raise _changes_error(f"sum_insured must not exceed {SUM_INSURED_LIMIT:f}.")
    return {"sum_insured": f"{amount:.2f}"}


def _normalize_expiry_date(changes):
    value = changes["expiry_date"]
    if not isinstance(value, str):
        raise _changes_error(DATE_FORMAT_MESSAGE)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise _changes_error(DATE_FORMAT_MESSAGE)
    if parsed.isoformat() != value:
        raise _changes_error(DATE_FORMAT_MESSAGE)
    return {"expiry_date": parsed.isoformat()}


def _no_changes(changes):
    return {}


_CHANGE_RULES = {
    Endorsement.Type.CHANGE_DETAILS: (("insured_name",), _normalize_insured_name),
    Endorsement.Type.CHANGE_SUM_INSURED: (("sum_insured",), _normalize_sum_insured),
    Endorsement.Type.EXTENSION: (("expiry_date",), _normalize_expiry_date),
    Endorsement.Type.PREMIUM_ADJUSTMENT: ((), _no_changes),
    Endorsement.Type.CANCELLATION: ((), _no_changes),
}


def create_endorsement(mga_reference, data):
    with transaction.atomic():
        contract = _get_contract(mga_reference)
        candidate = _build_candidate(contract, data)
        candidate.full_clean(validate_constraints=False)
        existing = list(Endorsement.objects.filter(contract=contract))
        _reject_duplicate_number(candidate, existing)
        _apply_business_rules(contract, candidate, existing)
        candidate.save()
    return candidate


def _get_contract(mga_reference):
    try:
        return Contract.objects.get(mga_reference=mga_reference)
    except Contract.DoesNotExist:
        raise ValidationError(
            {"mga_reference": "No contract exists with this reference."}
        )


def _build_candidate(contract, data):
    unknown = [name for name in data if name not in CREATABLE_FIELDS]
    if unknown:
        raise ValidationError({name: "Unknown field." for name in unknown})
    candidate = Endorsement(
        contract=contract,
        **{name: data[name] for name in CREATABLE_FIELDS if name in data},
    )
    candidate.changes = validate_endorsement_changes(candidate.type, candidate.changes)
    if candidate.type == Endorsement.Type.CANCELLATION:
        candidate.premium_change = None
    elif candidate.premium_change is not None:
        candidate.premium_change = _normalize_premium(candidate.premium_change)
    return candidate


def _normalize_premium(value):
    try:
        return _normalize_money(value, allow_negative=True)
    except ValidationError as exc:
        raise ValidationError({"premium_change": exc.messages})


def _reject_duplicate_number(candidate, existing):
    if any(e.endorsement_number == candidate.endorsement_number for e in existing):
        raise ValidationError(
            {"endorsement_number": "This endorsement number is already used for this contract."}
        )


def _apply_business_rules(contract, candidate, existing):
    history = [e for e in existing if e.type != Endorsement.Type.CANCELLATION]
    current_expiry = calculate_position(contract, history, date.max)["expiry_date"]
    if not contract.inception_date <= candidate.effective_date <= current_expiry:
        raise ValidationError(
            {
                "effective_date": (
                    f"Effective date must be between {contract.inception_date.isoformat()} "
                    f"and {current_expiry.isoformat()}."
                )
            }
        )
    if candidate.type == Endorsement.Type.EXTENSION:
        proposed_expiry = date.fromisoformat(candidate.changes["expiry_date"])
        if proposed_expiry <= current_expiry:
            raise ValidationError(
                {"changes": f"expiry_date must be later than the current expiry {current_expiry.isoformat()}."}
            )

    agreed = [e for e in existing if e.status == Endorsement.Status.AGREED]
    agreed_cancellations = [
        e for e in agreed if e.type == Endorsement.Type.CANCELLATION
    ]
    is_agreed_cancellation = (
        candidate.type == Endorsement.Type.CANCELLATION
        and candidate.status == Endorsement.Status.AGREED
    )
    if is_agreed_cancellation and agreed_cancellations:
        raise ValidationError({"type": "Contract already has an agreed cancellation."})
    if agreed_cancellations:
        cutoff = agreed_cancellations[0].effective_date
        if candidate.effective_date >= cutoff:
            raise ValidationError(
                {
                    "effective_date": (
                        "Effective date must be before the agreed cancellation "
                        f"effective {cutoff.isoformat()}."
                    )
                }
            )
    if is_agreed_cancellation:
        affected = [
            str(e.endorsement_number)
            for e in agreed
            if e.type != Endorsement.Type.CANCELLATION
            and e.effective_date >= candidate.effective_date
        ]
        if affected:
            raise ValidationError(
                {
                    "effective_date": (
                        "Cancellation would invalidate agreed endorsement(s) "
                        f"{', '.join(affected)} effective on or after this date."
                    )
                }
            )

    if candidate.type == Endorsement.Type.CANCELLATION:
        candidate.premium_change = _cancellation_refund(
            contract, existing, candidate.effective_date
        )
    if candidate.status == Endorsement.Status.AGREED:
        _check_non_negative_premium(contract, agreed + [candidate])


def _cancellation_refund(contract, existing, effective_date):
    try:
        return calculate_cancellation_premium_change(contract, existing, effective_date)
    except ValueError as exc:
        key = (
            "premium_change"
            if str(exc) == NEGATIVE_PRE_CANCELLATION_GROSS
            else "effective_date"
        )
        raise ValidationError({key: str(exc)})


def _check_non_negative_premium(contract, endorsements):
    for as_of in sorted({e.effective_date for e in endorsements}):
        gross = contract.gross_premium
        effective = sorted(
            (e for e in endorsements if e.effective_date <= as_of),
            key=lambda e: e.endorsement_number,
        )
        for endorsement in effective:
            if endorsement.premium_change is None:
                raise ValidationError(
                    {
                        "premium_change": (
                            f"Agreed endorsement {endorsement.endorsement_number} has no premium change."
                        )
                    }
                )
            gross += endorsement.premium_change
            if gross < ZERO:
                raise ValidationError(
                    {
                        "premium_change": (
                            f"Gross premium would become negative after endorsement "
                            f"{endorsement.endorsement_number} on {as_of.isoformat()}."
                        )
                    }
                )
