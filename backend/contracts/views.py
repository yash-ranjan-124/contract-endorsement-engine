from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from contracts.models import Contract
from contracts.serializers import (
    ContractCreateSerializer,
    ContractSlipSerializer,
    EndorsementCreateSerializer,
    EndorsementSerializer,
    PositionQuerySerializer,
    PositionSerializer,
)
from contracts.services import calculate_position, create_endorsement


@api_view(["GET", "POST"])
def contract_list(request):
    if request.method == "POST":
        return _create_contract(request)
    today = timezone.localdate()
    contracts = Contract.objects.prefetch_related("endorsements").order_by("mga_reference")
    positions = [
        calculate_position(contract, list(contract.endorsements.all()), today)
        for contract in contracts
    ]
    return Response(PositionSerializer(positions, many=True).data)


@api_view(["GET"])
def contract_detail(request, reference):
    today = timezone.localdate()
    contract = get_object_or_404(
        Contract.objects.prefetch_related("endorsements"), mga_reference=reference
    )
    endorsements = list(contract.endorsements.all())
    position = calculate_position(contract, endorsements, today)
    return Response(
        {
            "slip": ContractSlipSerializer(contract).data,
            "endorsements": EndorsementSerializer(endorsements, many=True).data,
            "current_position": PositionSerializer(position).data,
        }
    )


@api_view(["GET"])
def contract_position(request, reference):
    today = timezone.localdate()
    contract = get_object_or_404(
        Contract.objects.prefetch_related("endorsements"), mga_reference=reference
    )
    query = PositionQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    as_at = query.validated_data.get("as_at", today)
    endorsements = list(contract.endorsements.all())
    position = calculate_position(contract, endorsements, as_at)
    return Response(PositionSerializer(position).data)


@api_view(["POST"])
def endorsement_create(request, reference):
    serializer = EndorsementCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        endorsement = create_endorsement(reference, serializer.validated_data)
    except DjangoValidationError as exc:
        _raise_field_errors(exc)
    return Response(EndorsementSerializer(endorsement).data, status=status.HTTP_201_CREATED)


def _create_contract(request):
    serializer = ContractCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    contract = Contract(**serializer.validated_data)
    try:
        contract.save()
    except DjangoValidationError as exc:
        _raise_field_errors(exc)
    return Response(ContractSlipSerializer(contract).data, status=status.HTTP_201_CREATED)


def _raise_field_errors(exc):
    if hasattr(exc, "error_dict"):
        raise DRFValidationError(exc.message_dict) from exc
    raise DRFValidationError({"non_field_errors": exc.messages}) from exc
