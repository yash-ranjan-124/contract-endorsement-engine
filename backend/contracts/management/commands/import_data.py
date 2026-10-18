import json

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from rest_framework.exceptions import ValidationError as DRFValidationError

from contracts.models import Contract
from contracts.serializers import ContractCreateSerializer
from contracts.services import create_endorsement


class Command(BaseCommand):
    help = "Import contracts, then endorsements, from two JSON arrays."

    def add_arguments(self, parser):
        parser.add_argument("contracts_file")
        parser.add_argument("endorsements_file")

    def handle(self, *args, **options):
        contract_rows = _load_rows(options["contracts_file"])
        endorsement_rows = _load_rows(options["endorsements_file"])

        loaded, rejected = self._import_contracts(contract_rows)
        self.stdout.write(f"Contracts: {loaded} loaded, {rejected} rejected.")

        loaded, rejected = self._import_endorsements(endorsement_rows)
        self.stdout.write(f"Endorsements: {loaded} loaded, {rejected} rejected.")

    def _import_contracts(self, rows):
        loaded = rejected = 0
        for row_number, row in enumerate(rows, start=1):
            reference = row.get("mga_reference")
            try:
                with transaction.atomic():
                    serializer = ContractCreateSerializer(data=row)
                    serializer.is_valid(raise_exception=True)
                    Contract(**serializer.validated_data).save()
            except (DRFValidationError, DjangoValidationError) as exc:
                rejected += 1
                self.stdout.write(
                    f"Contract row {row_number} ({reference}) rejected: "
                    f"{_describe(_field_errors(exc))}"
                )
            else:
                loaded += 1
        return loaded, rejected

    def _import_endorsements(self, rows):
        loaded = rejected = 0
        for row_number, row in enumerate(rows, start=1):
            data = dict(row)
            reference = data.pop("mga_reference", None)
            number = data.get("endorsement_number")
            try:
                with transaction.atomic():
                    create_endorsement(reference, data)
            except DjangoValidationError as exc:
                rejected += 1
                self.stdout.write(
                    f"Endorsement row {row_number} ({reference}, endorsement {number}) "
                    f"rejected: {_describe(_field_errors(exc))}"
                )
            else:
                loaded += 1
        return loaded, rejected


def _load_rows(path):
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        raise CommandError(f"File not found: {path}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CommandError(f"{path} is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise CommandError(f"Cannot read {path}: {exc.strerror}") from exc
    if not isinstance(data, list):
        raise CommandError(f"{path} must contain a top-level JSON array.")
    for row_number, row in enumerate(data, start=1):
        if not isinstance(row, dict):
            raise CommandError(f"{path}: row {row_number} must be a JSON object.")
    return data


def _field_errors(exc):
    if isinstance(exc, DRFValidationError):
        detail = exc.detail
        if isinstance(detail, dict):
            return {field: _as_list(messages) for field, messages in detail.items()}
        return {"non_field_errors": _as_list(detail)}
    if hasattr(exc, "error_dict"):
        return exc.message_dict
    return {"non_field_errors": exc.messages}


def _as_list(messages):
    if isinstance(messages, list):
        return [str(message) for message in messages]
    return [str(messages)]


def _describe(errors):
    return "; ".join(f"{field}: {' '.join(messages)}" for field, messages in errors.items())
