from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models

ZERO = Decimal("0")
ONE_HUNDRED = Decimal("100")
MONEY_QUANTUM = Decimal("0.01")
MONETARY_FIELDS = ("sum_insured", "gross_premium")

AMOUNT_VALIDATORS = [MinValueValidator(ZERO)]
PERCENTAGE_VALIDATORS = [MinValueValidator(ZERO), MaxValueValidator(ONE_HUNDRED)]
CURRENCY_VALIDATOR = RegexValidator(
    regex=r"^[A-Z]{3}\Z",
    message="Currency must be exactly three uppercase ASCII letters.",
)


def _normalize_money(value, *, allow_negative=False):
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise ValidationError("Enter a valid amount.")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValidationError("Enter a valid amount.")
    if not amount.is_finite():
        raise ValidationError("Amount must be a finite number.")
    if not allow_negative and amount < ZERO:
        raise ValidationError("Amount cannot be negative.")
    try:
        return amount.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValidationError("Enter a valid amount.")


class Contract(models.Model):
    """The original bound slip for a contract.

    Immutability is application-level protection in save(). QuerySet.update(),
    bulk operations that modify existing rows, and raw SQL bypass it and must
    not be used to change slip data.
    """

    class Status(models.TextChoices):
        BOUND = "BOUND", "Bound"

    mga_reference = models.CharField(max_length=50, unique=True)
    insured_name = models.CharField(max_length=255)
    class_of_business = models.CharField(max_length=100)
    inception_date = models.DateField()
    expiry_date = models.DateField()
    currency = models.CharField(max_length=3, validators=[CURRENCY_VALIDATOR])
    sum_insured = models.DecimalField(
        max_digits=18, decimal_places=2, validators=AMOUNT_VALIDATORS
    )
    gross_premium = models.DecimalField(
        max_digits=18, decimal_places=2, validators=AMOUNT_VALIDATORS
    )
    brokerage_pct = models.DecimalField(
        max_digits=5, decimal_places=2, validators=PERCENTAGE_VALIDATORS
    )
    signed_line_pct = models.DecimalField(
        max_digits=5, decimal_places=2, validators=PERCENTAGE_VALIDATORS
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.BOUND
    )

    def __str__(self):
        return self.mga_reference

    def clean(self):
        super().clean()
        if isinstance(self.inception_date, date) and isinstance(self.expiry_date, date):
            if self.expiry_date < self.inception_date:
                raise ValidationError(
                    {"expiry_date": "Expiry date cannot be before inception date."}
                )

    def save(self, *args, **kwargs):
        persisted = Contract.objects.filter(pk=self.pk).first()
        if persisted is None:
            self._normalize_monetary_fields()
            self.full_clean()
        else:
            self._reject_slip_changes(persisted)
        super().save(*args, **kwargs)

    def _normalize_monetary_fields(self):
        normalized = {}
        errors = {}
        for name in MONETARY_FIELDS:
            try:
                normalized[name] = _normalize_money(getattr(self, name))
            except ValidationError as exc:
                errors[name] = exc.messages
        if errors:
            raise ValidationError(errors)
        for name, value in normalized.items():
            setattr(self, name, value)

    def _reject_slip_changes(self, persisted):
        changed = [
            name
            for name in self._slip_field_names()
            if getattr(self, name) != getattr(persisted, name)
        ]
        if changed:
            raise ValidationError(
                {
                    name: "Original slip fields cannot be changed after the contract is saved."
                    for name in changed
                }
            )

    @classmethod
    def _slip_field_names(cls):
        return [field.attname for field in cls._meta.concrete_fields if not field.primary_key]


class Endorsement(models.Model):
    class Type(models.TextChoices):
        CHANGE_SUM_INSURED = "CHANGE_SUM_INSURED", "Change sum insured"
        CHANGE_DETAILS = "CHANGE_DETAILS", "Change details"
        PREMIUM_ADJUSTMENT = "PREMIUM_ADJUSTMENT", "Premium adjustment"
        EXTENSION = "EXTENSION", "Extension"
        CANCELLATION = "CANCELLATION", "Cancellation"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        AGREED = "AGREED", "Agreed"

    contract = models.ForeignKey(
        Contract, on_delete=models.PROTECT, related_name="endorsements"
    )
    endorsement_number = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    type = models.CharField(max_length=30, choices=Type.choices)
    status = models.CharField(max_length=10, choices=Status.choices)
    effective_date = models.DateField()
    recorded_date = models.DateField()
    premium_change = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    changes = models.JSONField(default=dict, blank=True)
    reason = models.TextField()

    class Meta:
        ordering = ["endorsement_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["contract", "endorsement_number"],
                name="unique_endorsement_number_per_contract",
            ),
        ]

    def clean(self):
        super().clean()
        if not isinstance(self.changes, dict):
            raise ValidationError({"changes": "Changes must be a JSON object."})
        if self.premium_change is None and self.type != self.Type.CANCELLATION:
            raise ValidationError(
                {"premium_change": "Premium change is required for this endorsement type."}
            )

    def save(self, *args, **kwargs):
        if self.premium_change is not None:
            try:
                self.premium_change = _normalize_money(
                    self.premium_change, allow_negative=True
                )
            except ValidationError as exc:
                raise ValidationError({"premium_change": exc.messages})
        self.full_clean()
        super().save(*args, **kwargs)
