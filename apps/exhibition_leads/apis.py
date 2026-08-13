"""API endpoints for Exhibition Leads (Munich API proxy)"""

import logging

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .clients.exceptions import (
    MunichAPIConnectionError,
    MunichAPIException,
    MunichAPINotFoundError,
    MunichAPITimeoutError,
    MunichAPIValidationError,
)
from .clients.munich_client import MunichExhibitionClient

logger = logging.getLogger(__name__)


class ExhibitionLeadListAPI(APIView):
    """List and create exhibition leads from Munich API"""

    permission_classes = [IsAuthenticated]

    class OutputSerializer(serializers.Serializer):
        """Output serializer for lead list"""

        count = serializers.IntegerField()
        next = serializers.URLField(allow_null=True)
        previous = serializers.URLField(allow_null=True)
        results = serializers.ListField()

    class InputSerializer(serializers.Serializer):
        """Input serializer for creating lead"""

        full_name = serializers.CharField(max_length=200)
        company_name = serializers.CharField(max_length=200)
        position = serializers.CharField(max_length=200)
        sphere_of_activity = serializers.CharField(max_length=200)
        phone_number = serializers.CharField(
            max_length=200, required=False, allow_blank=True
        )
        email = serializers.EmailField()
        company_address = serializers.CharField(required=False, allow_blank=True)
        company_type = serializers.ChoiceField(
            choices=[
                ("importer_exporter", "Importer/Exporter"),
                ("forwarder", "Forwarder"),
                ("agent", "Agent"),
            ]
        )
        cargo = serializers.CharField(max_length=200)
        mode_of_transport = serializers.ChoiceField(
            choices=[
                ("wagons", "Wagons"),
                ("containers", "Containers"),
                ("lcl", "LCL"),
                ("air", "Air"),
                ("auto", "Auto"),
            ]
        )
        shipment_volume = serializers.CharField(max_length=200)
        shipment_directions = serializers.ListField(
            child=serializers.IntegerField(), help_text="List of shipment direction IDs"
        )
        comments = serializers.CharField(required=False, allow_blank=True)
        meeting_place = serializers.CharField(
            max_length=200, required=False, allow_blank=True
        )
        category = serializers.IntegerField(required=False, allow_null=True)
        importance = serializers.ChoiceField(
            choices=[("low", "Low"), ("medium", "Medium"), ("high", "High")],
            default="medium",
        )

    @extend_schema(
        summary="List exhibition leads",
        description="Get paginated list of leads from Munich Exhibition API",
        parameters=[
            OpenApiParameter(
                name="search", type=OpenApiTypes.STR, description="Search query"
            ),
            OpenApiParameter(
                name="category_id",
                type=OpenApiTypes.INT,
                description="Filter by category (supports multiple values)",
                explode=True,
                style="form",
            ),
            OpenApiParameter(
                name="importance",
                type=OpenApiTypes.STR,
                description="Filter by importance: low, medium, high (supports multiple values)",
                explode=True,
                style="form",
            ),
            OpenApiParameter(
                name="company_type",
                type=OpenApiTypes.STR,
                description="Filter by company type: importer_exporter, forwarder, agent (supports multiple values)",
                explode=True,
                style="form",
            ),
            OpenApiParameter(
                name="mode_of_transport",
                type=OpenApiTypes.STR,
                description="Filter by mode of transport: wagons, containers, lcl, air, auto (supports multiple values)",
                explode=True,
                style="form",
            ),
            OpenApiParameter(
                name="page", type=OpenApiTypes.INT, description="Page number"
            ),
            OpenApiParameter(
                name="page_size", type=OpenApiTypes.INT, description="Items per page"
            ),
        ],
        responses={200: OutputSerializer},
    )
    def get(self, request):
        """List leads from Munich Exhibition API"""
        try:
            client = MunichExhibitionClient()

            # Build params dict with support for multiple values
            params = {}
            multi_value_params = [
                "category_id",
                "importance",
                "company_type",
                "mode_of_transport",
            ]

            for key in request.query_params.keys():
                values = request.query_params.getlist(key)
                # If multiple values or if it's a multi-value param, keep as list
                if len(values) > 1 or key in multi_value_params:
                    params[key] = values if len(values) > 1 else values[0]
                else:
                    params[key] = values[0]

            leads_data = client.list_leads(params)

            return Response(leads_data, status=status.HTTP_200_OK)

        except MunichAPIConnectionError as e:
            logger.error(f"Connection error: {str(e)}")
            return Response(
                {"error": "Unable to connect to Munich Exhibition API"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except MunichAPITimeoutError:
            logger.error("Timeout error")
            return Response(
                {"error": "Request timed out"}, status=status.HTTP_504_GATEWAY_TIMEOUT
            )
        except MunichAPIException as e:
            logger.error(f"Munich API error: {str(e)}")
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        summary="Create exhibition lead",
        description="Create new lead in Munich Exhibition API",
        request=InputSerializer,
        responses={201: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        """Create lead in Munich Exhibition API"""
        serializer = self.InputSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            client = MunichExhibitionClient()
            lead_data = client.create_lead(serializer.validated_data)

            return Response(lead_data, status=status.HTTP_201_CREATED)

        except MunichAPIValidationError as e:
            return Response(
                {"error": "Validation error", "details": e.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except MunichAPIConnectionError as e:
            logger.error(f"Connection error: {str(e)}")
            return Response(
                {"error": "Unable to connect to Munich Exhibition API"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except MunichAPIException as e:
            logger.error(f"Munich API error: {str(e)}")
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ExhibitionLeadDetailAPI(APIView):
    """Get, update, delete exhibition lead"""

    permission_classes = [IsAuthenticated]

    class InputSerializer(serializers.Serializer):
        """Input serializer for updating lead"""

        full_name = serializers.CharField(max_length=200, required=False)
        company_name = serializers.CharField(max_length=200, required=False)
        position = serializers.CharField(max_length=200, required=False)
        sphere_of_activity = serializers.CharField(max_length=200, required=False)
        phone_number = serializers.CharField(
            max_length=200, required=False, allow_blank=True
        )
        email = serializers.EmailField(required=False)
        company_address = serializers.CharField(required=False, allow_blank=True)
        company_type = serializers.ChoiceField(
            choices=[
                ("importer_exporter", "Importer/Exporter"),
                ("forwarder", "Forwarder"),
                ("agent", "Agent"),
            ],
            required=False,
        )
        cargo = serializers.CharField(max_length=200, required=False)
        mode_of_transport = serializers.ChoiceField(
            choices=[
                ("wagons", "Wagons"),
                ("containers", "Containers"),
                ("lcl", "LCL"),
                ("air", "Air"),
                ("auto", "Auto"),
            ],
            required=False,
        )
        shipment_volume = serializers.CharField(max_length=200, required=False)
        shipment_directions = serializers.ListField(
            child=serializers.IntegerField(), required=False
        )
        comments = serializers.CharField(required=False, allow_blank=True)
        meeting_place = serializers.CharField(
            max_length=200, required=False, allow_blank=True
        )
        category = serializers.IntegerField(required=False, allow_null=True)
        importance = serializers.ChoiceField(
            choices=[("low", "Low"), ("medium", "Medium"), ("high", "High")],
            required=False,
        )

    @extend_schema(
        summary="Get exhibition lead details",
        description="Get single lead from Munich Exhibition API",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request, lead_id):
        """Get lead details"""
        try:
            client = MunichExhibitionClient()
            lead_data = client.get_lead(lead_id)

            return Response(lead_data, status=status.HTTP_200_OK)

        except MunichAPINotFoundError:
            return Response(
                {"error": "Lead not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except MunichAPIConnectionError as e:
            logger.error(f"Connection error: {str(e)}")
            return Response(
                {"error": "Unable to connect to Munich Exhibition API"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except MunichAPIException as e:
            logger.error(f"Munich API error: {str(e)}")
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        summary="Update exhibition lead",
        description="Update lead in Munich Exhibition API",
        request=InputSerializer,
        responses={200: OpenApiTypes.OBJECT},
    )
    def put(self, request, lead_id):
        """Update lead"""
        serializer = self.InputSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            client = MunichExhibitionClient()
            lead_data = client.update_lead(lead_id, serializer.validated_data)

            return Response(lead_data, status=status.HTTP_200_OK)

        except MunichAPINotFoundError:
            return Response(
                {"error": "Lead not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except MunichAPIValidationError as e:
            return Response(
                {"error": "Validation error", "details": e.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except MunichAPIConnectionError as e:
            logger.error(f"Connection error: {str(e)}")
            return Response(
                {"error": "Unable to connect to Munich Exhibition API"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except MunichAPIException as e:
            logger.error(f"Munich API error: {str(e)}")
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @extend_schema(
        summary="Delete exhibition lead",
        description="Delete lead from Munich Exhibition API",
        responses={204: None},
    )
    def delete(self, request, lead_id):
        """Delete lead"""
        try:
            client = MunichExhibitionClient()
            client.delete_lead(lead_id)

            return Response(status=status.HTTP_204_NO_CONTENT)

        except MunichAPINotFoundError:
            return Response(
                {"error": "Lead not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except MunichAPIConnectionError as e:
            logger.error(f"Connection error: {str(e)}")
            return Response(
                {"error": "Unable to connect to Munich Exhibition API"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except MunichAPIException as e:
            logger.error(f"Munich API error: {str(e)}")
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ExhibitionReferenceDataAPI(APIView):
    """Get reference data (categories, shipment directions, companies)"""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Get reference data",
        description="Get categories, shipment directions, and companies from Munich API",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        """Get all reference data"""
        try:
            client = MunichExhibitionClient()

            data = {
                "categories": client.get_categories(),
                "shipment_directions": client.get_shipment_directions(),
                "companies": client.get_companies(),
            }

            return Response(data, status=status.HTTP_200_OK)

        except MunichAPIConnectionError as e:
            logger.error(f"Connection error: {str(e)}")
            return Response(
                {"error": "Unable to connect to Munich Exhibition API"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except MunichAPIException as e:
            logger.error(f"Munich API error: {str(e)}")
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
