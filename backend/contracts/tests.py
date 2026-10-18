from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.test import SimpleTestCase, TestCase

from contracts.models import Endorsement, Contract
from contracts.services import (
    calculate_cancellation_premium_change,
    calculate_position,
    validate_endorsement_changes,
)


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


class PositionCalculationTests(TestCase):
    def setUp(self):
        self.contract = build_contract()
        self.contract.save()

    def endorsement(self, number, **overrides):
        values = {
            "status": Endorsement.Status.AGREED,
            "premium_change": Decimal("0.00"),
        }
        values.update(overrides)
        endorsement = build_endorsement(
            self.contract, endorsement_number=number, **values
        )
        endorsement.save()
        return endorsement

    def test_no_endorsements_returns_original_values_and_financials(self):
        position = calculate_position(self.contract, [], date(2026, 6, 1))

        self.assertEqual(
            set(position),
            {
                "mga_reference",
                "as_at",
                "insured_name",
                "status",
                "inception_date",
                "expiry_date",
                "cancellation_effective_date",
                "currency",
                "sum_insured",
                "gross_premium",
                "net_premium",
                "our_net_premium",
                "applied_endorsements",
            },
        )
        self.assertEqual(position["mga_reference"], "MGA-2026-0001")
        self.assertEqual(position["status"], "BOUND")
        self.assertEqual(position["gross_premium"], Decimal("15000.00"))
        self.assertEqual(position["net_premium"], Decimal("13500.00"))
        self.assertEqual(position["our_net_premium"], Decimal("3375.00"))
        self.assertIsNone(position["cancellation_effective_date"])
        self.assertEqual(position["applied_endorsements"], [])

    def test_before_inception_applies_no_endorsements(self):
        early = self.endorsement(
            1, effective_date=date(2025, 12, 1), premium_change=Decimal("500.00")
        )

        position = calculate_position(self.contract, [early], date(2025, 12, 31))

        self.assertEqual(position["applied_endorsements"], [])
        self.assertEqual(position["gross_premium"], Decimal("15000.00"))

    def test_effective_date_boundary_is_inclusive(self):
        first = self.endorsement(
            1, effective_date=date(2026, 3, 1), premium_change=Decimal("500.00")
        )
        future = self.endorsement(
            2, effective_date=date(2026, 4, 1), premium_change=Decimal("700.00")
        )
        endorsements = [first, future]

        before = calculate_position(self.contract, endorsements, date(2026, 2, 28))
        on_boundary = calculate_position(self.contract, endorsements, date(2026, 3, 1))
        before_future = calculate_position(self.contract, endorsements, date(2026, 3, 31))

        self.assertEqual(before["applied_endorsements"], [])
        self.assertEqual(before["gross_premium"], Decimal("15000.00"))
        self.assertEqual(on_boundary["applied_endorsements"], [1])
        self.assertEqual(on_boundary["gross_premium"], Decimal("15500.00"))
        self.assertEqual(before_future["applied_endorsements"], [1])

    def test_draft_endorsements_are_excluded(self):
        draft = self.endorsement(
            1,
            status=Endorsement.Status.DRAFT,
            effective_date=date(2026, 3, 1),
            premium_change=Decimal("500.00"),
        )
        agreed = self.endorsement(
            2, effective_date=date(2026, 3, 1), premium_change=Decimal("250.00")
        )

        position = calculate_position(self.contract, [draft, agreed], date(2026, 4, 1))

        self.assertEqual(position["applied_endorsements"], [2])
        self.assertEqual(position["gross_premium"], Decimal("15250.00"))

    def test_backdated_endorsement_included_despite_later_recorded_date(self):
        backdated = self.endorsement(
            1,
            effective_date=date(2026, 2, 1),
            recorded_date=date(2026, 5, 1),
            premium_change=Decimal("500.00"),
        )

        position = calculate_position(self.contract, [backdated], date(2026, 3, 1))

        self.assertEqual(position["applied_endorsements"], [1])
        self.assertEqual(position["gross_premium"], Decimal("15500.00"))

    def test_unsorted_input_applied_in_number_order(self):
        third = self.endorsement(
            3, effective_date=date(2026, 3, 1), premium_change=Decimal("300.00")
        )
        first = self.endorsement(
            1, effective_date=date(2026, 3, 1), premium_change=Decimal("100.00")
        )
        second = self.endorsement(
            2, effective_date=date(2026, 3, 1), premium_change=Decimal("200.00")
        )

        position = calculate_position(
            self.contract, [third, first, second], date(2026, 4, 1)
        )

        self.assertEqual(position["applied_endorsements"], [1, 2, 3])
        self.assertEqual(position["gross_premium"], Decimal("15600.00"))

    def test_number_order_wins_over_effective_date_order(self):
        later_effective = self.endorsement(
            1,
            type=Endorsement.Type.CHANGE_DETAILS,
            effective_date=date(2026, 3, 10),
            changes={"insured_name": "First Name"},
        )
        earlier_effective = self.endorsement(
            2,
            type=Endorsement.Type.CHANGE_DETAILS,
            effective_date=date(2026, 3, 1),
            changes={"insured_name": "Second Name"},
        )

        position = calculate_position(
            self.contract, [earlier_effective, later_effective], date(2026, 4, 1)
        )

        self.assertEqual(position["insured_name"], "Second Name")
        self.assertEqual(position["applied_endorsements"], [1, 2])

    def test_cover_replacement_and_signed_premium_adjustments(self):
        cover = self.endorsement(
            1,
            type=Endorsement.Type.CHANGE_SUM_INSURED,
            effective_date=date(2026, 3, 1),
            changes={"sum_insured": "1250000.005"},
        )
        increase = self.endorsement(
            2,
            type=Endorsement.Type.PREMIUM_ADJUSTMENT,
            effective_date=date(2026, 3, 1),
            premium_change=Decimal("250.00"),
        )
        reduction = self.endorsement(
            3,
            type=Endorsement.Type.PREMIUM_ADJUSTMENT,
            effective_date=date(2026, 3, 1),
            premium_change=Decimal("-100.005"),
        )
        self.assertEqual(reduction.premium_change, Decimal("-100.01"))

        position = calculate_position(
            self.contract, [cover, increase, reduction], date(2026, 4, 1)
        )

        self.assertEqual(position["sum_insured"], Decimal("1250000.01"))
        self.assertEqual(position["gross_premium"], Decimal("15149.99"))
        self.assertEqual(position["net_premium"], Decimal("13634.99"))
        self.assertEqual(position["our_net_premium"], Decimal("3408.75"))
        self.assertEqual(position["applied_endorsements"], [1, 2, 3])

    def test_extension_applies_only_from_effective_date(self):
        extension = self.endorsement(
            1,
            type=Endorsement.Type.EXTENSION,
            effective_date=date(2026, 6, 1),
            changes={"expiry_date": "2027-03-31"},
        )

        before = calculate_position(self.contract, [extension], date(2026, 5, 31))
        on_date = calculate_position(self.contract, [extension], date(2026, 6, 1))

        self.assertEqual(before["expiry_date"], date(2026, 12, 31))
        self.assertEqual(before["applied_endorsements"], [])
        self.assertEqual(on_date["expiry_date"], date(2027, 3, 31))
        self.assertEqual(on_date["applied_endorsements"], [1])

    def test_cancellation_with_refund_applies_from_effective_date(self):
        cancellation = self.endorsement(
            1,
            type=Endorsement.Type.CANCELLATION,
            effective_date=date(2026, 7, 1),
            premium_change=Decimal("-3000.00"),
        )

        previous_day = calculate_position(
            self.contract, [cancellation], date(2026, 6, 30)
        )
        on_date = calculate_position(self.contract, [cancellation], date(2026, 7, 1))

        self.assertEqual(previous_day["status"], "BOUND")
        self.assertIsNone(previous_day["cancellation_effective_date"])
        self.assertEqual(previous_day["expiry_date"], date(2026, 12, 31))
        self.assertEqual(previous_day["gross_premium"], Decimal("15000.00"))
        self.assertEqual(on_date["status"], "CANCELLED")
        self.assertEqual(on_date["cancellation_effective_date"], date(2026, 7, 1))
        self.assertEqual(on_date["expiry_date"], date(2026, 6, 30))
        self.assertEqual(on_date["gross_premium"], Decimal("12000.00"))
        self.assertEqual(on_date["net_premium"], Decimal("10800.00"))
        self.assertEqual(on_date["our_net_premium"], Decimal("2700.00"))
        self.assertEqual(on_date["applied_endorsements"], [1])

    def test_applicable_cancellation_without_refund_raises(self):
        cancellation = self.endorsement(
            1,
            type=Endorsement.Type.CANCELLATION,
            effective_date=date(2026, 7, 1),
            premium_change=None,
        )

        with self.assertRaisesRegex(ValueError, "premium_change"):
            calculate_position(self.contract, [cancellation], date(2026, 7, 1))

        position = calculate_position(self.contract, [cancellation], date(2026, 6, 30))
        self.assertEqual(position["applied_endorsements"], [])

    def test_exact_half_up_financial_rounding(self):
        net_rounding_contract = build_contract(
            mga_reference="MGA-ROUND-SHARE",
            gross_premium=Decimal("1.01"),
            brokerage_pct=Decimal("50.00"),
            signed_line_pct=Decimal("50.00"),
        )
        net_rounding_contract.save()
        share_contract = build_contract(
            mga_reference="MGA-ROUND-TIE",
            gross_premium=Decimal("10.01"),
            brokerage_pct=Decimal("50.00"),
            signed_line_pct=Decimal("100.00"),
        )
        share_contract.save()

        share_position = calculate_position(
            net_rounding_contract, [], date(2026, 6, 1)
        )
        tie_position = calculate_position(share_contract, [], date(2026, 6, 1))

        self.assertEqual(share_position["net_premium"], Decimal("0.51"))
        self.assertEqual(share_position["our_net_premium"], Decimal("0.25"))
        self.assertEqual(tie_position["net_premium"], Decimal("5.01"))
        self.assertEqual(tie_position["our_net_premium"], Decimal("5.01"))

    def test_repeated_calls_do_not_mutate_inputs_or_records(self):
        cover = self.endorsement(
            1,
            type=Endorsement.Type.CHANGE_SUM_INSURED,
            effective_date=date(2026, 3, 1),
            changes={"sum_insured": "1250000.005"},
        )
        extension = self.endorsement(
            2,
            type=Endorsement.Type.EXTENSION,
            effective_date=date(2026, 3, 1),
            changes={"expiry_date": "2027-03-31"},
        )
        cancellation = self.endorsement(
            3,
            type=Endorsement.Type.CANCELLATION,
            effective_date=date(2026, 7, 1),
            premium_change=Decimal("-3000.00"),
        )
        endorsements = [cancellation, extension, cover]
        contract_before = Contract.objects.values().get(pk=self.contract.pk)
        records_before = list(
            Endorsement.objects.filter(contract=self.contract).values()
        )
        changes_before = [dict(endorsement.changes) for endorsement in endorsements]
        premiums_before = [endorsement.premium_change for endorsement in endorsements]

        positions = [
            calculate_position(self.contract, endorsements, as_at)
            for as_at in (
                date(2026, 2, 28),
                date(2026, 3, 1),
                date(2026, 6, 30),
                date(2026, 7, 1),
                date(2027, 1, 1),
            )
        ]

        self.assertEqual(positions[0]["status"], "BOUND")
        self.assertEqual(positions[3]["status"], "CANCELLED")
        self.assertEqual(
            Contract.objects.values().get(pk=self.contract.pk), contract_before
        )
        self.assertEqual(
            list(Endorsement.objects.filter(contract=self.contract).values()),
            records_before,
        )
        self.assertEqual(
            [endorsement.changes for endorsement in endorsements], changes_before
        )
        self.assertEqual(
            [endorsement.premium_change for endorsement in endorsements],
            premiums_before,
        )


class CancellationCalculationTests(TestCase):
    def setUp(self):
        self.contract = build_contract(gross_premium=Decimal("120000.00"))
        self.contract.save()

    def endorsement(self, number, **overrides):
        values = {
            "status": Endorsement.Status.AGREED,
            "premium_change": Decimal("0.00"),
        }
        values.update(overrides)
        endorsement = build_endorsement(
            self.contract, endorsement_number=number, **values
        )
        endorsement.save()
        return endorsement

    def adjustment(self, number, amount, **overrides):
        values = {
            "type": Endorsement.Type.PREMIUM_ADJUSTMENT,
            "effective_date": date(2026, 3, 1),
            "premium_change": amount,
        }
        values.update(overrides)
        return self.endorsement(number, **values)

    def test_sample_refund_with_agreed_adjustment(self):
        adjustment = self.adjustment(1, Decimal("20000.00"))

        refund = calculate_cancellation_premium_change(
            self.contract, [adjustment], date(2026, 9, 30)
        )

        self.assertEqual(refund, Decimal("-35671.23"))

    def test_cancellation_at_inception_refunds_full_premium(self):
        refund = calculate_cancellation_premium_change(
            self.contract, [], date(2026, 1, 1)
        )

        self.assertEqual(refund, Decimal("-120000.00"))

    def test_cancellation_at_expiry_refunds_one_day(self):
        refund = calculate_cancellation_premium_change(
            self.contract, [], date(2026, 12, 31)
        )

        self.assertEqual(refund, Decimal("-328.77"))

    def test_same_day_cover_refunds_full_premium(self):
        same_day = build_contract(
            mga_reference="MGA-SAME-DAY",
            inception_date=date(2026, 6, 1),
            expiry_date=date(2026, 6, 1),
            gross_premium=Decimal("15000.00"),
        )
        same_day.save()

        refund = calculate_cancellation_premium_change(
            same_day, [], date(2026, 6, 1)
        )

        self.assertEqual(refund, Decimal("-15000.00"))

    def test_leap_year_uses_inclusive_day_counting(self):
        leap = build_contract(
            mga_reference="MGA-LEAP",
            inception_date=date(2028, 1, 1),
            expiry_date=date(2028, 12, 31),
            gross_premium=Decimal("36600.00"),
        )
        leap.save()

        refund = calculate_cancellation_premium_change(leap, [], date(2028, 7, 1))

        self.assertEqual(refund, Decimal("-18400.00"))

    def test_draft_and_future_premium_changes_are_excluded(self):
        draft = self.adjustment(
            1, Decimal("5000.00"), status=Endorsement.Status.DRAFT
        )
        future = self.adjustment(
            2,
            Decimal("7000.00"),
            effective_date=date(2026, 10, 1),
        )

        refund = calculate_cancellation_premium_change(
            self.contract, [draft, future], date(2026, 9, 30)
        )

        self.assertEqual(refund, Decimal("-30575.34"))

    def test_same_day_agreed_premium_adjustment_is_included(self):
        same_day = self.adjustment(
            1, Decimal("20000.00"), effective_date=date(2026, 9, 30)
        )

        refund = calculate_cancellation_premium_change(
            self.contract, [same_day], date(2026, 9, 30)
        )

        self.assertEqual(refund, Decimal("-35671.23"))

    def test_effective_extension_changes_denominator_and_unused_days(self):
        extension = self.endorsement(
            1,
            type=Endorsement.Type.EXTENSION,
            effective_date=date(2026, 6, 1),
            changes={"expiry_date": "2027-03-31"},
        )

        refund = calculate_cancellation_premium_change(
            self.contract, [extension], date(2026, 9, 30)
        )

        self.assertEqual(refund, Decimal("-48263.74"))

    def test_draft_and_future_extensions_do_not_change_refund(self):
        draft = self.endorsement(
            1,
            type=Endorsement.Type.EXTENSION,
            status=Endorsement.Status.DRAFT,
            effective_date=date(2026, 6, 1),
            changes={"expiry_date": "2027-06-30"},
        )
        future = self.endorsement(
            2,
            type=Endorsement.Type.EXTENSION,
            effective_date=date(2026, 10, 1),
            changes={"expiry_date": "2027-06-30"},
        )

        refund = calculate_cancellation_premium_change(
            self.contract, [draft, future], date(2026, 9, 30)
        )

        self.assertEqual(refund, Decimal("-30575.34"))

    def test_cancellations_in_history_are_excluded(self):
        pending = self.endorsement(
            1,
            type=Endorsement.Type.CANCELLATION,
            effective_date=date(2026, 9, 1),
            premium_change=None,
        )
        previous = self.endorsement(
            2,
            type=Endorsement.Type.CANCELLATION,
            effective_date=date(2026, 9, 15),
            premium_change=Decimal("-5000.00"),
        )

        refund = calculate_cancellation_premium_change(
            self.contract, [pending, previous], date(2026, 9, 30)
        )

        self.assertEqual(refund, Decimal("-30575.34"))

    def test_zero_premium_returns_zero(self):
        zero = build_contract(
            mga_reference="MGA-ZERO", gross_premium=Decimal("0.00")
        )
        zero.save()

        refund = calculate_cancellation_premium_change(
            zero, [], date(2026, 9, 30)
        )

        self.assertEqual(str(refund), "0.00")

    def test_invalid_boundaries_and_negative_gross_rejected(self):
        with self.assertRaisesRegex(ValueError, "before inception"):
            calculate_cancellation_premium_change(
                self.contract, [], date(2025, 12, 31)
            )
        with self.assertRaisesRegex(ValueError, "after the pre-cancellation expiry"):
            calculate_cancellation_premium_change(
                self.contract, [], date(2027, 1, 1)
            )

        overdraw = self.adjustment(1, Decimal("-200000.00"))
        with self.assertRaisesRegex(ValueError, "negative"):
            calculate_cancellation_premium_change(
                self.contract, [overdraw], date(2026, 9, 30)
            )

    def test_half_cent_refund_rounds_away_from_zero(self):
        short = build_contract(
            mga_reference="MGA-HALF-CENT",
            inception_date=date(2026, 1, 1),
            expiry_date=date(2026, 7, 19),
            gross_premium=Decimal("1.00"),
        )
        short.save()
        cases = [
            (date(2026, 7, 19), Decimal("-0.01")),
            (date(2026, 7, 17), Decimal("-0.02")),
        ]
        for effective_date, expected in cases:
            with self.subTest(effective_date=effective_date):
                refund = calculate_cancellation_premium_change(
                    short, [], effective_date
                )
                self.assertEqual(refund, expected)

    def test_inputs_and_records_remain_unchanged(self):
        adjustment = self.adjustment(1, Decimal("20000.00"))
        cancellation = self.endorsement(
            2,
            type=Endorsement.Type.CANCELLATION,
            effective_date=date(2026, 9, 1),
            premium_change=None,
        )
        endorsements = [cancellation, adjustment]
        contract_before = Contract.objects.values().get(pk=self.contract.pk)
        records_before = list(
            Endorsement.objects.filter(contract=self.contract).values()
        )
        premiums_before = [endorsement.premium_change for endorsement in endorsements]

        for effective_date in (
            date(2026, 1, 1),
            date(2026, 9, 30),
            date(2026, 12, 31),
        ):
            calculate_cancellation_premium_change(
                self.contract, endorsements, effective_date
            )

        self.assertEqual(
            Contract.objects.values().get(pk=self.contract.pk), contract_before
        )
        self.assertEqual(
            list(Endorsement.objects.filter(contract=self.contract).values()),
            records_before,
        )
        self.assertEqual(
            [endorsement.premium_change for endorsement in endorsements],
            premiums_before,
        )

    def test_refund_recorded_as_cancellation_updates_position(self):
        self.adjustment(1, Decimal("20000.00"))
        adjustment = Endorsement.objects.get(
            contract=self.contract, endorsement_number=1
        )
        cancellation_date = date(2026, 9, 30)

        refund = calculate_cancellation_premium_change(
            self.contract, [adjustment], cancellation_date
        )
        cancellation = self.endorsement(
            2,
            type=Endorsement.Type.CANCELLATION,
            effective_date=cancellation_date,
            premium_change=refund,
        )
        history = list(Endorsement.objects.filter(contract=self.contract))

        before = calculate_position(
            self.contract, history, date(2026, 9, 29)
        )
        after = calculate_position(self.contract, history, cancellation_date)

        self.assertEqual(refund, Decimal("-35671.23"))
        self.assertEqual(before["status"], "BOUND")
        self.assertEqual(before["gross_premium"], Decimal("140000.00"))
        self.assertEqual(before["net_premium"], Decimal("126000.00"))
        self.assertEqual(before["our_net_premium"], Decimal("31500.00"))
        self.assertEqual(after["status"], "CANCELLED")
        self.assertEqual(after["cancellation_effective_date"], cancellation_date)
        self.assertEqual(after["expiry_date"], date(2026, 9, 29))
        self.assertEqual(after["gross_premium"], Decimal("104328.77"))
        self.assertEqual(after["net_premium"], Decimal("93895.89"))
        self.assertEqual(after["our_net_premium"], Decimal("23473.97"))
        self.assertEqual(after["applied_endorsements"], [1, 2])
        self.assertEqual(cancellation.premium_change, Decimal("-35671.23"))


class EndorsementChangesValidationTests(SimpleTestCase):
    def assertChangesError(self, endorsement_type, changes, fragment=None):
        with self.assertRaises(ValidationError) as ctx:
            validate_endorsement_changes(endorsement_type, changes)
        messages = ctx.exception.message_dict["changes"]
        if fragment is not None:
            self.assertTrue(
                any(fragment in message for message in messages),
                f"{messages!r} does not mention {fragment!r}",
            )
        return messages

    def test_valid_normalized_payload_for_every_type(self):
        cases = [
            (
                Endorsement.Type.CHANGE_DETAILS,
                {"insured_name": "  Acme Logistics Ltd  "},
                {"insured_name": "Acme Logistics Ltd"},
            ),
            (
                Endorsement.Type.CHANGE_SUM_INSURED,
                {"sum_insured": "1250000.005"},
                {"sum_insured": "1250000.01"},
            ),
            (
                Endorsement.Type.EXTENSION,
                {"expiry_date": "2027-03-31"},
                {"expiry_date": "2027-03-31"},
            ),
            (Endorsement.Type.PREMIUM_ADJUSTMENT, {}, {}),
            (Endorsement.Type.CANCELLATION, {}, {}),
        ]
        self.assertEqual(
            {endorsement_type for endorsement_type, _, _ in cases},
            set(Endorsement.Type.values),
        )
        for endorsement_type, changes, expected in cases:
            with self.subTest(type=endorsement_type):
                self.assertEqual(
                    validate_endorsement_changes(endorsement_type, changes), expected
                )

    def test_unknown_type_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_endorsement_changes("UNKNOWN", {})

        self.assertIn("type", ctx.exception.message_dict)

    def test_non_object_changes_rejected(self):
        for value in (None, [], ["insured_name"], "text", 1):
            with self.subTest(value=value):
                self.assertChangesError(
                    Endorsement.Type.CHANGE_DETAILS, value, "JSON object"
                )
        with self.subTest(type=Endorsement.Type.PREMIUM_ADJUSTMENT):
            self.assertChangesError(
                Endorsement.Type.PREMIUM_ADJUSTMENT, [], "JSON object"
            )

    def test_missing_keys_rejected(self):
        cases = [
            (Endorsement.Type.CHANGE_DETAILS, "insured_name"),
            (Endorsement.Type.CHANGE_SUM_INSURED, "sum_insured"),
            (Endorsement.Type.EXTENSION, "expiry_date"),
        ]
        for endorsement_type, key in cases:
            with self.subTest(type=endorsement_type):
                self.assertChangesError(endorsement_type, {}, f"'{key}'")

    def test_wrong_and_extra_keys_rejected(self):
        messages = self.assertChangesError(
            Endorsement.Type.CHANGE_DETAILS, {"name": "Acme"}, "'insured_name'"
        )
        self.assertTrue(any("'name'" in message for message in messages))

        self.assertChangesError(
            Endorsement.Type.CHANGE_DETAILS,
            {"insured_name": "Acme", "extra": 1},
            "'extra'",
        )
        self.assertChangesError(
            Endorsement.Type.PREMIUM_ADJUSTMENT, {"reason": "x"}, "'reason'"
        )
        self.assertChangesError(
            Endorsement.Type.CANCELLATION, {"expiry_date": "2027-01-01"}, "'expiry_date'"
        )

    def test_invalid_insured_names_rejected(self):
        cases = [
            ("", "blank"),
            ("   ", "blank"),
            (123, "string"),
            (None, "string"),
            ("A" * 256, "at most 255"),
        ]
        for value, fragment in cases:
            with self.subTest(value=value):
                self.assertChangesError(
                    Endorsement.Type.CHANGE_DETAILS,
                    {"insured_name": value},
                    fragment,
                )

    def test_insured_name_at_max_length_accepted(self):
        result = validate_endorsement_changes(
            Endorsement.Type.CHANGE_DETAILS, {"insured_name": "A" * 255}
        )

        self.assertEqual(result, {"insured_name": "A" * 255})

    def test_sum_insured_rounds_half_up_to_fixed_string(self):
        cases = [
            ("100.005", "100.01"),
            (Decimal("100.004"), "100.00"),
            (5, "5.00"),
            ("0", "0.00"),
            ("9999999999999999.99", "9999999999999999.99"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                result = validate_endorsement_changes(
                    Endorsement.Type.CHANGE_SUM_INSURED, {"sum_insured": value}
                )
                self.assertEqual(result, {"sum_insured": expected})
                self.assertIsInstance(result["sum_insured"], str)

    def test_sum_insured_invalid_values_rejected(self):
        cases = [
            Decimal("-0.001"),
            "-0.001",
            "abc",
            "",
            "NaN",
            "sNaN",
            "Infinity",
            "-Infinity",
            "1E+40",
            100.5,
            True,
            None,
        ]
        for value in cases:
            with self.subTest(value=value):
                self.assertChangesError(
                    Endorsement.Type.CHANGE_SUM_INSURED,
                    {"sum_insured": value},
                    "sum_insured",
                )

    def test_sum_insured_field_overflow_rejected(self):
        cases = [
            "10000000000000000.00",
            "9999999999999999.995",
        ]
        for value in cases:
            with self.subTest(value=value):
                self.assertChangesError(
                    Endorsement.Type.CHANGE_SUM_INSURED,
                    {"sum_insured": value},
                    "must not exceed",
                )

    def test_invalid_and_noncanonical_dates_rejected(self):
        cases = [
            "2027-02-30",
            "31-03-2027",
            "2027/03/31",
            "20270331",
            "2027-3-31",
            " 2027-03-31",
            "",
            None,
            20270331,
        ]
        for value in cases:
            with self.subTest(value=value):
                self.assertChangesError(
                    Endorsement.Type.EXTENSION,
                    {"expiry_date": value},
                    "YYYY-MM-DD",
                )

    def test_nonempty_payload_rejected_for_premium_adjustment_and_cancellation(self):
        for endorsement_type in (
            Endorsement.Type.PREMIUM_ADJUSTMENT,
            Endorsement.Type.CANCELLATION,
        ):
            with self.subTest(type=endorsement_type):
                self.assertChangesError(
                    endorsement_type, {"insured_name": "Acme"}, "'insured_name'"
                )

    def test_input_dictionary_remains_unchanged(self):
        cases = [
            (Endorsement.Type.CHANGE_DETAILS, {"insured_name": "  Acme  "}),
            (Endorsement.Type.CHANGE_SUM_INSURED, {"sum_insured": "100.005"}),
            (Endorsement.Type.EXTENSION, {"expiry_date": "2027-03-31"}),
            (Endorsement.Type.PREMIUM_ADJUSTMENT, {}),
        ]
        for endorsement_type, changes in cases:
            with self.subTest(type=endorsement_type):
                original = dict(changes)
                result = validate_endorsement_changes(endorsement_type, changes)

                self.assertEqual(changes, original)
                self.assertIsNot(result, changes)
