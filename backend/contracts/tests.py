from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from contracts.models import Contract


def valid_contract_data(**overrides):
    data = {
        "mga_reference": "MGA-2026-0001",
        "insured_name": "Acme Logistics Ltd",
        "class_of_business": "Marine Cargo",
        "inception_date": date(2026, 1, 1),
        "expiry_date": date(2026, 12, 31),
        "currency": "USD",
        "sum_insured": Decimal("1000000.00"),
        "gross_premium": Decimal("15000.00"),
        "brokerage_pct": Decimal("10.00"),
        "signed_line_pct": Decimal("25.00"),
    }
    data.update(overrides)
    return data


def build_contract(**overrides):
    return Contract(**valid_contract_data(**overrides))


CHANGED_SLIP_VALUES = {
    "mga_reference": "MGA-2026-9999",
    "insured_name": "Different Insured Ltd",
    "class_of_business": "Property",
    "inception_date": date(2026, 2, 1),
    "expiry_date": date(2027, 1, 31),
    "currency": "EUR",
    "sum_insured": Decimal("2000000.00"),
    "gross_premium": Decimal("20000.00"),
    "brokerage_pct": Decimal("12.50"),
    "signed_line_pct": Decimal("50.00"),
    "status": "CANCELLED",
}


class ContractCreationTests(TestCase):
    def test_valid_creation_defaults_to_bound(self):
        contract = build_contract()
        contract.save()

        stored = Contract.objects.get(pk=contract.pk)
        self.assertEqual(stored.status, Contract.Status.BOUND)
        self.assertEqual(stored.sum_insured, Decimal("1000000.00"))
        self.assertEqual(str(stored), "MGA-2026-0001")

    def test_duplicate_reference_rejected(self):
        build_contract().save()

        with self.assertRaises(ValidationError) as ctx:
            build_contract().save()

        self.assertIn("mga_reference", ctx.exception.message_dict)
        self.assertEqual(Contract.objects.count(), 1)

    def test_expiry_before_inception_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            build_contract(
                inception_date=date(2026, 6, 1), expiry_date=date(2026, 5, 31)
            ).save()

        self.assertIn("expiry_date", ctx.exception.message_dict)
        self.assertEqual(Contract.objects.count(), 0)

    def test_same_day_cover_accepted(self):
        build_contract(
            inception_date=date(2026, 6, 1), expiry_date=date(2026, 6, 1)
        ).save()

        self.assertEqual(Contract.objects.count(), 1)

    def test_negative_amounts_rejected(self):
        for field in ("sum_insured", "gross_premium"):
            for value in (Decimal("-0.01"), Decimal("-1000")):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError) as ctx:
                        build_contract(**{field: value}).save()

                    self.assertIn(field, ctx.exception.message_dict)

        self.assertEqual(Contract.objects.count(), 0)

    def test_percentage_boundaries_accepted(self):
        cases = [
            ("brokerage_pct", Decimal("0")),
            ("brokerage_pct", Decimal("100")),
            ("signed_line_pct", Decimal("0")),
            ("signed_line_pct", Decimal("100")),
        ]
        for index, (field, value) in enumerate(cases):
            with self.subTest(field=field, value=value):
                build_contract(
                    mga_reference=f"MGA-BOUNDARY-{index}", **{field: value}
                ).save()

        self.assertEqual(Contract.objects.count(), len(cases))

    def test_percentage_outside_range_rejected(self):
        for field in ("brokerage_pct", "signed_line_pct"):
            for value in (Decimal("-0.01"), Decimal("100.01")):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError) as ctx:
                        build_contract(**{field: value}).save()

                    self.assertIn(field, ctx.exception.message_dict)

        self.assertEqual(Contract.objects.count(), 0)

    def test_invalid_currency_rejected(self):
        for value in ("usd", "US", "USDX", "US1", "US ", "EU\n", "ÄBC"):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError) as ctx:
                    build_contract(currency=value).save()

                self.assertIn("currency", ctx.exception.message_dict)

        self.assertEqual(Contract.objects.count(), 0)


class ContractMoneyRoundingTests(TestCase):
    def test_half_up_rounding_on_initial_save(self):
        cases = [
            ("gross_premium", Decimal("100.005"), "100.01"),
            ("sum_insured", Decimal("100.005"), "100.01"),
            ("gross_premium", Decimal("100.004"), "100.00"),
            ("sum_insured", Decimal("100.004"), "100.00"),
            ("gross_premium", "100.005", "100.01"),
            ("sum_insured", "100.005", "100.01"),
        ]
        for index, (field, value, expected) in enumerate(cases):
            with self.subTest(field=field, value=value):
                build_contract(
                    mga_reference=f"MGA-ROUND-{index}", **{field: value}
                ).save()
                stored = Contract.objects.filter(mga_reference=f"MGA-ROUND-{index}")
                self.assertEqual(
                    stored.values_list(field, flat=True).get(), Decimal(expected)
                )

    def test_negative_amounts_rejected_before_rounding(self):
        for field in ("sum_insured", "gross_premium"):
            for value in (Decimal("-0.001"), "-0.001"):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError) as ctx:
                        build_contract(**{field: value}).save()

                    self.assertIn(field, ctx.exception.message_dict)

        self.assertEqual(Contract.objects.count(), 0)

    def test_malformed_and_non_finite_amounts_rejected(self):
        invalid_values = [
            "abc",
            "",
            "1,000.00",
            "NaN",
            "sNaN",
            "Infinity",
            "-Infinity",
            "1E+40",
            100.5,
            None,
            True,
        ]
        for field in ("sum_insured", "gross_premium"):
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValidationError) as ctx:
                        build_contract(**{field: value}).save()

                    self.assertIn(field, ctx.exception.message_dict)

        self.assertEqual(Contract.objects.count(), 0)


class ContractImmutabilityTests(TestCase):
    def setUp(self):
        self.contract = build_contract()
        self.contract.save()

    def test_changes_to_slip_fields_rejected(self):
        self.assertEqual(
            set(CHANGED_SLIP_VALUES),
            set(Contract._slip_field_names()),
            "Every slip field needs an immutability case.",
        )
        original = Contract.objects.values().get(pk=self.contract.pk)

        for field, new_value in CHANGED_SLIP_VALUES.items():
            with self.subTest(field=field):
                stored = Contract.objects.get(pk=self.contract.pk)
                setattr(stored, field, new_value)

                with self.assertRaises(ValidationError) as ctx:
                    stored.save()

                self.assertIn(field, ctx.exception.message_dict)

                reloaded = Contract.objects.values().get(pk=self.contract.pk)
                self.assertEqual(reloaded, original)

    def test_unchanged_save_accepted(self):
        stored = Contract.objects.get(pk=self.contract.pk)
        stored.save()

        self.assertEqual(Contract.objects.count(), 1)
        self.assertEqual(Contract.objects.get(pk=self.contract.pk).insured_name, "Acme Logistics Ltd")
