from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from contracts.models import Contract
from contracts.serializers import (
    ContractCreateSerializer,
    ContractDetailSerializer,
    ContractSlipSerializer,
    EndorsementCreateSerializer,
    EndorsementSerializer,
    PositionQuerySerializer,
    PositionSerializer,
)
from contracts.services import calculate_position, create_endorsement

REFERENCE_PARAMETER = OpenApiParameter(
    name='reference',
    type=str,
    location=OpenApiParameter.PATH,
    description='Contract MGA reference, for example MNK-PR-2026-001.',
)

def validation_errors(example):
    return OpenApiResponse(
        description=(
            'Validation failed. Each key is a field name and each value is a list of '
            'messages. Nothing is saved.'
        ),
        response={
            'type': 'object',
            'additionalProperties': {'type': 'array', 'items': {'type': 'string'}},
            'example': example,
        },
    )

NOT_FOUND = OpenApiResponse(
    description='No contract exists with this reference.',
    response={
        'type': 'object',
        'properties': {'detail': {'type': 'string'}},
        'required': ['detail'],
    },
)


@extend_schema(
    methods=['GET'],
    operation_id='list_contracts',
    tags=['Contracts'],
    summary='List current contract positions',
    description=(
        "Returns today's position for every contract as a plain JSON array, ordered by "
        'reference. The list is not paginated. Money values are decimal strings.'
    ),
    responses={200: PositionSerializer(many=True)},
    auth=[],
)
@extend_schema(
    methods=['POST'],
    operation_id='create_contract',
    tags=['Contracts'],
    summary='Create a contract',
    description=(
        'Creates the original contract slip. The status is always BOUND and may be omitted. '
        'The slip cannot be changed afterwards.'
    ),
    request=ContractCreateSerializer,
    responses={
        201: ContractSlipSerializer,
        400: validation_errors({'expiry_date': ['Expiry date cannot be before inception date.']}),
    },
    auth=[],
)
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


@extend_schema(
    operation_id='get_contract',
    tags=['Contracts'],
    summary='Get a contract with its history',
    description=(
        'Returns the original slip, every endorsement in number order (drafts included) '
        "and today's position."
    ),
    parameters=[REFERENCE_PARAMETER],
    responses={200: ContractDetailSerializer, 404: NOT_FOUND},
    auth=[],
)
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


@extend_schema(
    operation_id='get_contract_position',
    tags=['Contracts'],
    summary='Get a contract position on a date',
    description=(
        'Calculates the position from the original slip and the agreed endorsements '
        'effective on or before the date. Dates before inception or after expiry are '
        'allowed. Positions are calculated on request and never stored.'
    ),
    parameters=[
        REFERENCE_PARAMETER,
        OpenApiParameter(
            name='as_at',
            type=OpenApiTypes.DATE,
            location=OpenApiParameter.QUERY,
            required=False,
            description=(
                'Date to calculate the position for, as canonical YYYY-MM-DD. Defaults to '
                'today. An empty or malformed value returns 400.'
            ),
        ),
    ],
    responses={
        200: PositionSerializer,
        400: validation_errors({'as_at': ['as_at must be a date in YYYY-MM-DD format.']}),
        404: NOT_FOUND,
    },
    auth=[],
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


@extend_schema(
    operation_id='create_endorsement',
    tags=['Endorsements'],
    summary='Add an endorsement to a contract',
    description=(
        'Validates the endorsement against the contract history and saves it. For a '
        'cancellation the server calculates the return premium and ignores any '
        'premium_change supplied. An unknown contract returns 400 with an mga_reference '
        'error. Rejected requests save nothing.'
    ),
    parameters=[REFERENCE_PARAMETER],
    request=EndorsementCreateSerializer,
    responses={
        201: EndorsementSerializer,
        400: validation_errors(
            {'effective_date': ['Effective date must be between 2026-01-01 and 2026-12-31.']}
        ),
    },
    auth=[],
)
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
