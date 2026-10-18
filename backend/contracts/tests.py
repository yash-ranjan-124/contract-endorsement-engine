from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.test import TestCase

from contracts.models import Endorsement, Contract


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


def build_endorsement(contract, **overrides):
    data = {
        "contract": contract,
        "endorsement_number": 1,
        "type": Endorsement.Type.PREMIUM_ADJUSTMENT,
        "status": Endorsement.Status.DRAFT,
        "effective_date": date(2026, 3, 1),
        "recorded_date": date(2026, 2, 15),
        "premium_change": Decimal("500.00"),
        "changes": {},
        "reason": "Adjust premium for additional exposure",
    }
    data.update(overrides)
    return Endorsement(**data)


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


class EndorsementCreationTests(TestCase):
    def setUp(self):
        self.contract = build_contract()
        self.contract.save()

    def test_valid_endorsement_linked_to_contract(self):
        build_endorsement(self.contract).save()

        endorsement = self.contract.endorsements.get()
        self.assertEqual(endorsement.endorsement_number, 1)
        self.assertEqual(endorsement.premium_change, Decimal("500.00"))
        self.assertEqual(endorsement.changes, {})
        self.assertEqual(str(endorsement.contract), "MGA-2026-0001")

    def test_draft_and_agreed_statuses_save(self):
        for number, status in enumerate(Endorsement.Status.values, start=1):
            with self.subTest(status=status):
                build_endorsement(
                    self.contract, endorsement_number=number, status=status
                ).save()

        self.assertEqual(
            set(self.contract.endorsements.values_list("status", flat=True)),
            set(Endorsement.Status.values),
        )

    def test_duplicate_number_within_contract_rejected(self):
        build_endorsement(self.contract, endorsement_number=1).save()

        with self.assertRaises(ValidationError):
            build_endorsement(self.contract, endorsement_number=1).save()

        self.assertEqual(self.contract.endorsements.count(), 1)

    def test_same_number_across_contracts_accepted(self):
        other = build_contract(mga_reference="MGA-2026-0002")
        other.save()

        build_endorsement(self.contract, endorsement_number=1).save()
        build_endorsement(other, endorsement_number=1).save()

        self.assertEqual(Endorsement.objects.filter(endorsement_number=1).count(), 2)

    def test_zero_and_negative_numbers_rejected(self):
        for number in (0, -1):
            with self.subTest(number=number):
                with self.assertRaises(ValidationError) as ctx:
                    build_endorsement(self.contract, endorsement_number=number).save()

                self.assertIn("endorsement_number", ctx.exception.message_dict)

        self.assertEqual(self.contract.endorsements.count(), 0)

    def test_unknown_type_status_and_missing_contract_rejected(self):
        cases = [
            ("type", {"type": "UNKNOWN"}),
            ("status", {"status": "APPROVED"}),
            ("status", {"status": ""}),
            ("contract", {"contract": None}),
            ("contract", {"contract": Contract(pk=999999)}),
        ]
        for field, overrides in cases:
            with self.subTest(field=field, overrides=overrides):
                endorsement = build_endorsement(self.contract)
                for name, value in overrides.items():
                    setattr(endorsement, name, value)

                with self.assertRaises(ValidationError) as ctx:
                    endorsement.save()

                self.assertIn(field, ctx.exception.message_dict)

        self.assertEqual(Endorsement.objects.count(), 0)

    def test_default_ordering_follows_endorsement_number(self):
        for number in (3, 1, 2):
            build_endorsement(self.contract, endorsement_number=number).save()

        numbers = list(
            Endorsement.objects.filter(contract=self.contract).values_list(
                "endorsement_number", flat=True
            )
        )
        self.assertEqual(numbers, [1, 2, 3])

    def test_changes_must_be_object(self):
        for value in ([], [1], "", "text", 1, None):
            with self.subTest(value=value):
                with self.assertRaises(ValidationError) as ctx:
                    build_endorsement(self.contract, changes=value).save()

                self.assertIn("changes", ctx.exception.message_dict)

        build_endorsement(self.contract, changes={}).save()
        build_endorsement(
            self.contract,
            endorsement_number=2,
            changes={"sum_insured": "2000000.00"},
        ).save()

        self.assertEqual(self.contract.endorsements.count(), 2)

    def test_signed_premium_changes_round_half_up(self):
        cases = [
            (Decimal("100.005"), "100.01"),
            (Decimal("-100.005"), "-100.01"),
            ("-100.005", "-100.01"),
            (Decimal("-250.00"), "-250.00"),
            (Decimal("250.00"), "250.00"),
            (Decimal("0"), "0.00"),
            (Decimal("-0.004"), "0.00"),
        ]
        for number, (value, expected) in enumerate(cases, start=1):
            with self.subTest(value=value):
                build_endorsement(
                    self.contract, endorsement_number=number, premium_change=value
                ).save()
                stored = Endorsement.objects.get(
                    contract=self.contract, endorsement_number=number
                )
                self.assertEqual(stored.premium_change, Decimal(expected))

    def test_null_premium_allowed_only_for_cancellation(self):
        number = 0
        for endorsement_type in Endorsement.Type.values:
            number += 1
            with self.subTest(type=endorsement_type):
                endorsement = build_endorsement(
                    self.contract,
                    endorsement_number=number,
                    type=endorsement_type,
                    premium_change=None,
                )
                if endorsement_type == Endorsement.Type.CANCELLATION:
                    endorsement.save()
                    self.assertIsNone(endorsement.premium_change)
                else:
                    with self.assertRaises(ValidationError) as ctx:
                        endorsement.save()
                    self.assertIn("premium_change", ctx.exception.message_dict)

    def test_invalid_premium_inputs_rejected(self):
        invalid_values = [
            100.5,
            True,
            False,
            "abc",
            "",
            "1,000.00",
            "NaN",
            "sNaN",
            "Infinity",
            "-Infinity",
            "1E+40",
        ]
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError) as ctx:
                    build_endorsement(self.contract, premium_change=value).save()

                self.assertIn("premium_change", ctx.exception.message_dict)

        self.assertEqual(self.contract.endorsements.count(), 0)


class EndorsementProtectionTests(TestCase):
    def test_contract_with_endorsements_cannot_be_deleted(self):
        contract = build_contract()
        contract.save()
        build_endorsement(contract).save()

        with self.assertRaises(ProtectedError):
            contract.delete()

        self.assertEqual(Contract.objects.count(), 1)
        self.assertEqual(Endorsement.objects.count(), 1)
