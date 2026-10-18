from datetime import date

from rest_framework import serializers


def _money(**kwargs):
    return serializers.DecimalField(
        max_digits=18, decimal_places=2, coerce_to_string=True, read_only=True, **kwargs
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
    gross_premium = _money()
    net_premium = _money(allow_null=True)
    our_net_premium = _money(allow_null=True)
    applied_endorsements = serializers.ListField(
        child=serializers.IntegerField(), read_only=True
    )


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
