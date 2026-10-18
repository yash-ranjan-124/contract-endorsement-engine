from datetime import date
from decimal import Decimal

from rest_framework import serializers

from contracts.models import Contract, Endorsement

PERCENTAGE_MIN = Decimal("0")
PERCENTAGE_MAX = Decimal("100")


def _money(**kwargs):
    return serializers.DecimalField(
        max_digits=18, decimal_places=2, coerce_to_string=True, read_only=True, **kwargs
    )


def _calculated_money(**kwargs):
    return serializers.DecimalField(
        max_digits=None, decimal_places=2, coerce_to_string=True, read_only=True, **kwargs
    )


def _percentage():
    return serializers.DecimalField(
        max_digits=5, decimal_places=2, coerce_to_string=True, read_only=True
    )


class ContractSlipSerializer(serializers.Serializer):
    mga_reference = serializers.CharField(read_only=True)
    insured_name = serializers.CharField(read_only=True)
    class_of_business = serializers.CharField(read_only=True)
    inception_date = serializers.DateField(read_only=True)
    expiry_date = serializers.DateField(read_only=True)
    currency = serializers.CharField(read_only=True)
    sum_insured = _money()
    gross_premium = _money()
    brokerage_pct = _percentage()
    signed_line_pct = _percentage()
    status = serializers.CharField(read_only=True)


class EndorsementSerializer(serializers.Serializer):
    number = serializers.IntegerField(source="endorsement_number", read_only=True)
    type = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    effective_date = serializers.DateField(read_only=True)
    recorded_date = serializers.DateField(read_only=True)
    premium_change = _money(allow_null=True)
    changes = serializers.JSONField(read_only=True)
    reason = serializers.CharField(read_only=True)


class PositionSerializer(serializers.Serializer):
    mga_reference = serializers.CharField(read_only=True)
    as_at = serializers.DateField(read_only=True)
    insured_name = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    inception_date = serializers.DateField(read_only=True)
    expiry_date = serializers.DateField(read_only=True)
    cancellation_effective_date = serializers.DateField(read_only=True, allow_null=True)
    currency = serializers.CharField(read_only=True)
    sum_insured = _money()
    gross_premium = _calculated_money()
    net_premium = _calculated_money(allow_null=True)
    our_net_premium = _calculated_money(allow_null=True)
    applied_endorsements = serializers.ListField(
        child=serializers.IntegerField(), read_only=True
    )


class MoneyInputField(serializers.Field):
    default_error_messages = {
        "invalid": "Enter an amount as a decimal string or integer, not a floating-point number.",
    }

    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, (str, int)):
            self.fail("invalid")
        return data

    def to_representation(self, value):
        return str(value)


class StrictInputSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if isinstance(data, dict):
            unknown = {key: "Unknown field." for key in data if key not in self.fields}
            if unknown:
                raise serializers.ValidationError(unknown)
        return super().to_internal_value(data)


class ContractCreateSerializer(StrictInputSerializer):
    mga_reference = serializers.CharField(max_length=50)
    insured_name = serializers.CharField(max_length=255)
    class_of_business = serializers.CharField(max_length=100)
    inception_date = serializers.DateField()
    expiry_date = serializers.DateField()
    currency = serializers.CharField(max_length=3)
    sum_insured = MoneyInputField()
    gross_premium = MoneyInputField()
    brokerage_pct = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=PERCENTAGE_MIN, max_value=PERCENTAGE_MAX
    )
    signed_line_pct = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=PERCENTAGE_MIN, max_value=PERCENTAGE_MAX
    )
    status = serializers.ChoiceField(
        choices=Contract.Status.choices, required=False
    )


class EndorsementCreateSerializer(StrictInputSerializer):
    endorsement_number = serializers.IntegerField()
    type = serializers.ChoiceField(choices=Endorsement.Type.choices)
    status = serializers.ChoiceField(choices=Endorsement.Status.choices)
    effective_date = serializers.DateField()
    recorded_date = serializers.DateField()
    premium_change = MoneyInputField(required=False, allow_null=True)
    changes = serializers.JSONField(required=False, default=dict)
    reason = serializers.CharField()


class PositionQuerySerializer(serializers.Serializer):
    as_at = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)

    def validate_as_at(self, value):
        message = "as_at must be a date in YYYY-MM-DD format."
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise serializers.ValidationError(message)
        if parsed.isoformat() != value:
            raise serializers.ValidationError(message)
        return parsed
