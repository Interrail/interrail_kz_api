import io
from datetime import date, datetime

import pandas as pd
from django.http import HttpResponse
from django.utils.html import strip_tags
from django.utils.timezone import localtime
from drf_spectacular.openapi import OpenApiParameter, OpenApiTypes
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers, status
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api_config.pagination import (
    CustomPageNumberPagination,
    get_paginated_response,
)
from apps.api_config.utils import inline_serializer
from apps.authentication.authentication import CookieJWTAuthentication
from apps.core.permissions import IsAdminOnly, IsManagerOrAdmin

from .models import Inquiry, KPIWeights, PerformanceTarget
from .selectors import InquirySelectors, PerformanceTargetSelectors
from .services import (
    InquiryKPIServices,
    InquiryServices,
    KPIWeightsServices,
    PerformanceTargetServices,
)


class AttachmentField(serializers.Field):
    """Custom field that handles both file uploads and string commands"""

    def to_internal_value(self, data):
        # Handle file uploads (multipart requests)
        if hasattr(data, 'read'):
            return data

        # Handle string commands (JSON requests)
        if isinstance(data, str):
            if data == 'DELETE':
                return None  # Signal for deletion
            elif data == '':
                return ...  # Signal for no change (ellipsis)
            else:
                raise serializers.ValidationError(
                    "Invalid value. Use 'DELETE' to remove attachment or upload a file."
                )

        raise serializers.ValidationError(
            "Must be a file or 'DELETE' string."
        )

    def to_representation(self, value):
        if hasattr(value, 'url'):
            return value.url
        return str(value) if value else None


def build_inquiry_filter_data(request) -> dict:
    """Build the FilterSerializer input dict from list/export query params.

    Mirrors the array-param handling (status[], is_new_customer[]) and forces
    sales_manager_id = request.user.id for non-admin users so they only ever
    see their own inquiries. Shared by the list and export views so the two
    can never drift.
    """
    status_list = request.GET.getlist("status[]")
    is_new_customer = request.GET.get("is_new_customer[]")

    data = {}
    for key, value in request.query_params.items():
        if key not in ["status[]", "is_new_customer[]"]:
            data[key] = value

    if status_list:
        data["status"] = status_list

    if is_new_customer is not None:
        data["is_new_customer"] = is_new_customer

    if request.user.user_type != "admin":
        data["sales_manager_id"] = request.user.id

    return data


class InquiryListApiView(APIView):
    """
    List inquiries
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class Pagination(CustomPageNumberPagination):
        page_size = 10
        max_page_size = 50

    class FilterSerializer(serializers.Serializer):
        status = serializers.ListField(
            child=serializers.ChoiceField(choices=Inquiry.STATUS_CHOICES),
            required=False,
            allow_empty=True,
        )

        text = serializers.CharField(required=False)
        comment = serializers.CharField(required=False)
        search = serializers.CharField(required=False)
        is_new_customer = serializers.BooleanField(required=False)
        sales_manager_id = serializers.IntegerField(required=False)
        year = serializers.IntegerField(required=False, min_value=1900, max_value=9999)
        month = serializers.IntegerField(required=False, min_value=1, max_value=12)
        date_from = serializers.DateField(required=False)
        date_to = serializers.DateField(required=False)

    class InquiryListOutputSerializer(serializers.ModelSerializer):
        attachment_url = serializers.SerializerMethodField()
        attachment_name = serializers.SerializerMethodField()
        has_attachment = serializers.SerializerMethodField()
        status_display = serializers.CharField(source='get_status_display', read_only=True)
        sales_manager = inline_serializer(
            fields={
                "id": serializers.IntegerField(read_only=True),
                "username": serializers.CharField(read_only=True),
                "email": serializers.EmailField(read_only=True),
            },
            allow_null=True,
        )

        class Meta:
            model = Inquiry
            fields = [
                'id', 'client', 'text', 'attachment_url', 'attachment_name',
                'has_attachment', 'status', 'status_display', 'sales_manager',
                'is_new_customer', 'created_at', 'updated_at'
            ]

        def get_attachment_url(self, obj):
            return obj.attachment.url if obj.attachment else None

        def get_attachment_name(self, obj):
            return obj.attachment.name.split('/')[-1] if obj.attachment else None

        def get_has_attachment(self, obj):
            return bool(obj.attachment)

    @extend_schema(
        tags=["Inquiries"],
        summary="List Inquiries",
        parameters=[
            OpenApiParameter(
                "page", OpenApiTypes.INT, description="Page number (default: 1)"
            ),
            OpenApiParameter(
                "page_size",
                OpenApiTypes.INT,
                description="Items per page (default: 10, max: 100)",
            ),
            OpenApiParameter(
                "status",
                OpenApiTypes.STR,
                description="Filter by multiple statuses (comma-separated)",
            ),
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                description="Search across all fields: client, text, comment, status, sales manager info (username, email, first/last name), attachment filenames, and KPI grades",
            ),
            OpenApiParameter(
                "is_new_customer",
                OpenApiTypes.BOOL,
                description="Filter by new customer status",
            ),
            OpenApiParameter(
                "sales_manager_id",
                OpenApiTypes.INT,
                description="Filter by sales manager ID",
            ),
            OpenApiParameter(
                "year",
                OpenApiTypes.INT,
                description="Filter by year (e.g., 2024)",
            ),
            OpenApiParameter(
                "month",
                OpenApiTypes.INT,
                description="Filter by month (1-12)",
            ),
        ],
        responses={200: InquiryListOutputSerializer},
    )
    def get(self, request):
        # Build filters (array params + non-admin manager lock) via shared helper
        data = build_inquiry_filter_data(request)

        filter_serializer = self.FilterSerializer(data=data)
        filter_serializer.is_valid(raise_exception=True)

        queryset = InquirySelectors.get_inquiries_list(
            filters=filter_serializer.validated_data
        )

        # Use pagination helper
        return get_paginated_response(
            pagination_class=self.Pagination,
            serializer_class=self.InquiryListOutputSerializer,
            queryset=queryset,
            request=request,
            view=self,
        )


class InquiryExportApiView(APIView):
    """Export the (optionally filtered) inquiries list as an .xlsx file."""

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    # Reuse the list view's filter contract verbatim
    FilterSerializer = InquiryListApiView.FilterSerializer

    EXPORT_COLUMNS = [
        "ID", "Sales Manager", "Client", "Status",
        "New Customer", "Text", "File", "Created At",
    ]

    @extend_schema(
        tags=["Inquiries"],
        summary="Export Inquiries to Excel",
        responses={200: OpenApiTypes.BINARY},
    )
    def get(self, request):
        data = build_inquiry_filter_data(request)

        filter_serializer = self.FilterSerializer(data=data)
        filter_serializer.is_valid(raise_exception=True)

        queryset = InquirySelectors.get_inquiries_list(
            filters=filter_serializer.validated_data
        )

        rows = [self._build_row(inquiry) for inquiry in queryset]
        df = pd.DataFrame(rows, columns=self.EXPORT_COLUMNS)

        buffer = io.BytesIO()
        df.to_excel(buffer, index=False, engine="openpyxl", sheet_name="Inquiries")
        buffer.seek(0)

        filename = f"inquiries_{date.today().isoformat()}.xlsx"
        response = HttpResponse(
            buffer.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    @staticmethod
    def _build_row(inquiry):
        manager = inquiry.sales_manager
        attachment = (
            inquiry.attachment.name.split("/")[-1] if inquiry.attachment else ""
        )
        return {
            "ID": inquiry.id,
            "Sales Manager": manager.username if manager else "",
            "Client": inquiry.client,
            "Status": inquiry.get_status_display(),
            "New Customer": "Yes" if inquiry.is_new_customer else "No",
            "Text": strip_tags(inquiry.text) if inquiry.text else "",
            "File": attachment,
            "Created At": localtime(inquiry.created_at).strftime("%Y-%m-%d %H:%M"),
        }


class InquiryCreateApiView(APIView):
    """
    Create inquiry
    Supports both JSON (text) and multipart/form-data (file) requests
    """

    authentication_classes = []
    permission_classes = []
    parser_classes = [JSONParser, MultiPartParser]

    class InquiryCreateSerializer(serializers.Serializer):
        client = serializers.CharField(max_length=255, required=True)
        text = serializers.CharField(required=False, allow_blank=True)
        attachment = serializers.FileField(required=False, allow_null=True)
        status = serializers.ChoiceField(
            choices=Inquiry.STATUS_CHOICES,
            default=Inquiry.STATUS_CHOICES[0][0],
        )
        comment = serializers.CharField(required=False, allow_blank=True)
        sales_manager_id = serializers.IntegerField(required=True)
        is_new_customer = serializers.BooleanField(default=False)



    class InquiryCreateOutputSerializer(serializers.Serializer):
        id = serializers.IntegerField(read_only=True)
        client = serializers.CharField(read_only=True)
        text = serializers.CharField(read_only=True, allow_null=True)
        attachment_url = serializers.CharField(read_only=True, allow_null=True)
        attachment_name = serializers.CharField(read_only=True, allow_null=True)
        has_attachment = serializers.BooleanField(read_only=True)
        status = serializers.CharField(read_only=True)
        status_display = serializers.CharField(read_only=True)
        sales_manager = inline_serializer(
            fields={
                "id": serializers.IntegerField(read_only=True),
                "username": serializers.CharField(read_only=True),
                "email": serializers.EmailField(read_only=True),
            },
            allow_null=True,
        )
        is_new_customer = serializers.BooleanField(read_only=True)
        comment = serializers.CharField(read_only=True, allow_blank=True)
        created_at = serializers.DateTimeField(read_only=True)
        updated_at = serializers.DateTimeField(read_only=True)

    @extend_schema(
        tags=["Inquiries"],
        summary="Create Inquiry",
        request=InquiryCreateSerializer,
        responses={201: InquiryCreateOutputSerializer},
    )
    def post(self, request):
        serializer = self.InquiryCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            inquiry = InquiryServices.create_inquiry(
                client=serializer.validated_data["client"],
                text=serializer.validated_data.get("text"),
                attachment=serializer.validated_data.get("attachment"),
                comment=serializer.validated_data.get("comment", ""),
                sales_manager_id=serializer.validated_data.get("sales_manager_id"),
                is_new_customer=serializer.validated_data.get("is_new_customer", False),
                status=serializer.validated_data.get("status", "pending"),
            )

            data = InquirySelectors.get_inquiry_by_id(inquiry_id=inquiry.id)

            return Response(
                self.InquiryCreateOutputSerializer(data).data,
                status=status.HTTP_201_CREATED,
            )

        except ValueError as e:
            return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class InquiryDetailApiView(APIView):
    """
    Retrieve inquiry detail
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class InquiryDetailSerializer(serializers.Serializer):
        id = serializers.IntegerField(read_only=True)
        client = serializers.CharField(read_only=True)
        text = serializers.CharField(read_only=True, allow_null=True)
        attachment_url = serializers.CharField(read_only=True, allow_null=True)
        attachment_name = serializers.CharField(read_only=True, allow_null=True)
        has_attachment = serializers.BooleanField(read_only=True)
        status = serializers.CharField(read_only=True)
        status_display = serializers.CharField(read_only=True)
        sales_manager = inline_serializer(
            fields={
                "id": serializers.IntegerField(read_only=True),
                "username": serializers.CharField(read_only=True),
                "email": serializers.EmailField(read_only=True),
            },
            allow_null=True,
        )
        is_new_customer = serializers.BooleanField(read_only=True)
        comment = serializers.CharField(read_only=True, allow_blank=True)
        created_at = serializers.DateTimeField(read_only=True)
        updated_at = serializers.DateTimeField(read_only=True)

    @extend_schema(
        tags=["Inquiries"],
        summary="Get Inquiry Detail",
        responses={200: InquiryDetailSerializer},
    )
    def get(self, request, inquiry_id):
        try:
            data = InquirySelectors.get_inquiry_by_id(inquiry_id=inquiry_id)

            return Response(
                self.InquiryDetailSerializer(data).data, status=status.HTTP_200_OK
            )
        except Inquiry.DoesNotExist:
            return Response(
                {"message": "Inquiry not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except ValueError as e:
            return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class InquiryUpdateApiView(APIView):
    """
    Update inquiry
    Supports switching between text and file
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]
    parser_classes = [JSONParser, MultiPartParser]

    class InquiryUpdateSerializer(serializers.Serializer):
        client = serializers.CharField(max_length=255, required=False)
        text = serializers.CharField(required=False, allow_blank=True)
        attachment = AttachmentField(required=False)
        status = serializers.ChoiceField(choices=Inquiry.STATUS_CHOICES, required=False)
        comment = serializers.CharField(required=False, allow_blank=True)
        sales_manager_id = serializers.IntegerField(required=False)
        is_new_customer = serializers.BooleanField(required=False)

        def validate(self, data):
            # Handle attachment field - can be file upload or string command
            if 'attachment' in self.initial_data:
                attachment_value = self.initial_data['attachment']

                # Handle file uploads (multipart requests)
                if hasattr(attachment_value, 'read'):
                    data['attachment'] = attachment_value
                # Handle string commands (JSON requests)
                elif isinstance(attachment_value, str):
                    if attachment_value == 'DELETE':
                        data['attachment'] = None  # Signal for deletion
                    elif attachment_value == '':
                        data.pop('attachment', None)  # Remove from data = no change
                    else:
                        raise serializers.ValidationError(
                            {"attachment": "Invalid value. Use 'DELETE' to remove attachment or upload a file."}
                        )
                else:
                    raise serializers.ValidationError(
                        {"attachment": "Must be a file or 'DELETE' string."}
                    )

            return data




    class InquiryUpdateResponseSerializer(serializers.Serializer):
        id = serializers.IntegerField(read_only=True)
        client = serializers.CharField(read_only=True)
        text = serializers.CharField(read_only=True, allow_null=True)
        attachment_url = serializers.CharField(read_only=True, allow_null=True)
        attachment_name = serializers.CharField(read_only=True, allow_null=True)
        has_attachment = serializers.BooleanField(read_only=True)
        status = serializers.CharField(read_only=True)
        status_display = serializers.CharField(read_only=True)
        sales_manager = inline_serializer(
            fields={
                "id": serializers.IntegerField(read_only=True),
                "username": serializers.CharField(read_only=True),
                "email": serializers.EmailField(read_only=True),
            },
            allow_null=True,
        )
        is_new_customer = serializers.BooleanField(read_only=True)
        comment = serializers.CharField(read_only=True, allow_blank=True)
        created_at = serializers.DateTimeField(read_only=True)
        updated_at = serializers.DateTimeField(read_only=True)

    @extend_schema(
        tags=["Inquiries"],
        summary="Update Inquiry",
        request=InquiryUpdateSerializer,
        responses={200: InquiryUpdateResponseSerializer},
    )
    def put(self, request, inquiry_id):
        serializer = self.InquiryUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            inquiry = InquirySelectors.get_inquiry_instance_by_id(inquiry_id=inquiry_id)

            # Prepare update kwargs, only include fields that were provided
            update_kwargs = {
                "inquiry": inquiry,
            }

            # Only include fields that were explicitly provided in the request
            for field in ["client", "text", "status", "comment", "sales_manager_id", "is_new_customer"]:
                if field in serializer.validated_data:
                    update_kwargs[field] = serializer.validated_data[field]

            # Handle attachment separately to distinguish between None and not provided
            if "attachment" in serializer.validated_data:
                update_kwargs["attachment"] = serializer.validated_data["attachment"]

            updated_inquiry = InquiryServices.update_inquiry(**update_kwargs)

            # Get formatted data directly from updated inquiry
            data = InquirySelectors.get_inquiry_by_id(inquiry_id=updated_inquiry.id)
            return Response(
                self.InquiryUpdateResponseSerializer(data).data,
                status=status.HTTP_200_OK,
            )

        except ValueError as e:
            return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Inquiry.DoesNotExist:
            return Response(
                {"message": "Inquiry not found"}, status=status.HTTP_404_NOT_FOUND
            )


class InquiryDeleteApiView(APIView):
    """
    Delete inquiry
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAdminOnly]

    class DeleteSuccessSerializer(serializers.Serializer):
        message = serializers.CharField()

    @extend_schema(
        tags=["Inquiries"],
        summary="Delete Inquiry",
        responses={200: DeleteSuccessSerializer},
    )
    def delete(self, request, inquiry_id):
        try:
            inquiry = InquirySelectors.get_inquiry_instance_by_id(inquiry_id=inquiry_id)
            InquiryServices.delete_inquiry(inquiry=inquiry)

            return Response(
                self.DeleteSuccessSerializer(
                    {"message": "Inquiry deleted successfully"}
                ).data,
                status=status.HTTP_200_OK,
            )

        except ValueError as e:
            return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Inquiry.DoesNotExist:
            return Response(
                {"message": "Inquiry not found"}, status=status.HTTP_404_NOT_FOUND
            )


class InquiryStatsApiView(APIView):
    """
    Get inquiry statistics
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class InquiryStatsOutputSerializer(serializers.Serializer):
        total_inquiries = serializers.IntegerField()
        pending_count = serializers.IntegerField()
        quoted_count = serializers.IntegerField()
        success_count = serializers.IntegerField()
        failed_count = serializers.IntegerField()
        new_customers_count = serializers.IntegerField()
        conversion_rate = serializers.FloatField()

    @extend_schema(
        tags=["Inquiries"],
        summary="Get Inquiry Statistics",
        description="Get inquiry statistics filtered by manager, year, and month. Managers can only view their own stats, admins can view all or specific managers.",
        parameters=[
            OpenApiParameter(
                "manager_id",
                OpenApiTypes.INT,
                description="Filter by sales manager ID (Admin only)",
                required=False
            ),
            OpenApiParameter(
                "year",
                OpenApiTypes.INT,
                description="Filter by year (e.g., 2024)",
                required=False
            ),
            OpenApiParameter(
                "month",
                OpenApiTypes.INT,
                description="Filter by month (1-12)",
                required=False
            ),
            OpenApiParameter(
                "date_from", OpenApiTypes.DATE,
                description="Start of date range (YYYY-MM-DD); use with date_to",
                required=False,
            ),
            OpenApiParameter(
                "date_to", OpenApiTypes.DATE,
                description="End of date range (YYYY-MM-DD); use with date_from",
                required=False,
            ),
        ],
        responses={200: InquiryStatsOutputSerializer},
    )
    def get(self, request):
        # Parse query parameters
        year = request.query_params.get('year')
        month = request.query_params.get('month')
        requested_manager_id = request.query_params.get('manager_id')

        # Validate year parameter
        if year is not None:
            try:
                year = int(year)
                if year < 1900 or year > 9999:
                    return Response(
                        {"message": "Year must be between 1900 and 9999"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except ValueError:
                return Response(
                    {"message": "Invalid year format. Must be an integer."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Validate month parameter
        if month is not None:
            try:
                month = int(month)
                if month < 1 or month > 12:
                    return Response(
                        {"message": "Month must be between 1 and 12"},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except ValueError:
                return Response(
                    {"message": "Invalid month format. Must be an integer."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Parse optional explicit date range (YYYY-MM-DD)
        date_from_raw = request.query_params.get('date_from')
        date_to_raw = request.query_params.get('date_to')
        date_from = date_to = None
        if date_from_raw:
            try:
                date_from = datetime.strptime(date_from_raw, "%Y-%m-%d").date()
            except ValueError:
                return Response(
                    {"message": "Invalid date_from format. Use YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if date_to_raw:
            try:
                date_to = datetime.strptime(date_to_raw, "%Y-%m-%d").date()
            except ValueError:
                return Response(
                    {"message": "Invalid date_to format. Use YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if date_from and date_to and date_from > date_to:
            return Response(
                {"message": "date_from must not be later than date_to."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Determine manager_id based on user role and permissions
        if request.user.user_type == 'admin':
            # Admins can filter by specific manager_id or see all
            if requested_manager_id is not None:
                try:
                    manager_id = int(requested_manager_id)
                except ValueError:
                    return Response(
                        {"message": "Invalid manager_id format. Must be an integer."},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            else:
                manager_id = None  # All managers
        else:
            # Managers can only see their own data
            manager_id = request.user.id

        # Get statistics with filters
        data = InquirySelectors.get_inquiries_stats(
            manager_id=manager_id,
            year=year,
            month=month,
            date_from=date_from,
            date_to=date_to
        )

        return Response(
            self.InquiryStatsOutputSerializer(data).data, status=status.HTTP_200_OK
        )


class ManagerKPIApiView(APIView):
    """
    Get KPI statistics for a specific manager
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class ManagerKPIOutputSerializer(serializers.Serializer):
        # Basic counts
        total_inquiries = serializers.IntegerField()
        total_pending = serializers.IntegerField()
        total_quoted = serializers.IntegerField()
        total_success = serializers.IntegerField()
        total_failed = serializers.IntegerField()
        new_customers = serializers.IntegerField()
        processed_inquiries = serializers.IntegerField()
        completed_inquiries = serializers.IntegerField()

        # KPI Grade Statistics
        quote_grade_a = serializers.IntegerField()
        quote_grade_b = serializers.IntegerField()
        quote_grade_c = serializers.IntegerField()
        completion_grade_a = serializers.IntegerField()
        completion_grade_b = serializers.IntegerField()
        completion_grade_c = serializers.IntegerField()

        # KPI Points
        total_quote_points = serializers.IntegerField()
        total_completion_points = serializers.IntegerField()
        total_kpi_points = serializers.IntegerField()
        avg_quote_points = serializers.FloatField()
        avg_completion_points = serializers.FloatField()
        avg_total_points = serializers.FloatField()

        # Conversion rates
        conversion_rate = serializers.FloatField()
        processing_conversion_rate = serializers.FloatField()
        lead_generation_rate = serializers.FloatField()

        # Grade percentages
        quote_grade_a_pct = serializers.FloatField()
        quote_grade_b_pct = serializers.FloatField()
        quote_grade_c_pct = serializers.FloatField()
        completion_grade_a_pct = serializers.FloatField()
        completion_grade_b_pct = serializers.FloatField()
        completion_grade_c_pct = serializers.FloatField()

    @extend_schema(
        tags=["KPI"],
        summary="Get Manager KPI Statistics",
        parameters=[
            OpenApiParameter(
                "date_from",
                OpenApiTypes.DATE,
                description="Filter from date (YYYY-MM-DD)",
                required=False
            ),
            OpenApiParameter(
                "date_to",
                OpenApiTypes.DATE,
                description="Filter to date (YYYY-MM-DD)",
                required=False
            ),
        ],
        responses={200: ManagerKPIOutputSerializer},
    )
    def get(self, request, manager_id):
        try:
            # Security check: Managers can only view their own KPI data
            if request.user.user_type != 'admin' and manager_id != request.user.id:
                return Response(
                    {"message": "Access denied"},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Parse date parameters
            date_from = None
            date_to = None

            if request.query_params.get('date_from'):
                try:
                    date_from = datetime.strptime(request.query_params['date_from'], '%Y-%m-%d')
                except ValueError:
                    return Response(
                        {"message": "Invalid date_from format. Use YYYY-MM-DD"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            if request.query_params.get('date_to'):
                try:
                    date_to = datetime.strptime(request.query_params['date_to'], '%Y-%m-%d')
                except ValueError:
                    return Response(
                        {"message": "Invalid date_to format. Use YYYY-MM-DD"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            # Get KPI statistics
            data = InquirySelectors.get_manager_kpi_statistics(
                manager_id=manager_id,
                date_from=date_from,
                date_to=date_to
            )

            return Response(
                self.ManagerKPIOutputSerializer(data).data,
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return Response(
                {"message": f"Error retrieving manager KPI statistics: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )


class DashboardKPIApiView(APIView):
    """
    Get overall KPI dashboard data
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class ManagerSerializer(serializers.Serializer):
        username = serializers.CharField()
        id = serializers.IntegerField()
        first_name = serializers.CharField()
        last_name = serializers.CharField()

    class InquiriesSerializer(serializers.Serializer):
        total = serializers.IntegerField()
        pending = serializers.IntegerField()
        quoted = serializers.IntegerField()
        failed = serializers.IntegerField()
        success = serializers.IntegerField()

    class KPISerializer(serializers.Serializer):
        response_time = serializers.CharField()
        follow_up = serializers.CharField()
        conversion_rate = serializers.CharField()
        new_customer = serializers.CharField()
        overall_performance = serializers.CharField()

    class ManagerPerformanceSerializer(serializers.Serializer):
        def to_representation(self, instance):
            return {
                'manager': DashboardKPIApiView.ManagerSerializer(instance.get('manager', {})).data,
                'inquiries': DashboardKPIApiView.InquiriesSerializer(instance.get('inquiries', {})).data,
                'kpi': DashboardKPIApiView.KPISerializer(instance.get('kpi', {})).data
            }

    class DashboardKPIOutputSerializer(serializers.Serializer):
        def to_representation(self, instance):
            return instance

    @extend_schema(
        tags=["KPI"],
        summary="Get Dashboard KPI Data",
        description="Get KPI dashboard data. Admins see all managers' data, managers see only their own data.",
        parameters=[
            OpenApiParameter(
                "date_from",
                OpenApiTypes.DATE,
                description="Filter from date (YYYY-MM-DD)",
                required=False
            ),
            OpenApiParameter(
                "date_to",
                OpenApiTypes.DATE,
                description="Filter to date (YYYY-MM-DD)",
                required=False
            ),
        ],
        responses={200: DashboardKPIOutputSerializer},
    )
    def get(self, request):
        try:
            # Parse date parameters
            date_from = None
            date_to = None

            if request.query_params.get('date_from'):
                try:
                    date_from = datetime.strptime(request.query_params['date_from'], '%Y-%m-%d')
                except ValueError:
                    return Response(
                        {"message": "Invalid date_from format. Use YYYY-MM-DD"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            if request.query_params.get('date_to'):
                try:
                    date_to = datetime.strptime(request.query_params['date_to'], '%Y-%m-%d')
                except ValueError:
                    return Response(
                        {"message": "Invalid date_to format. Use YYYY-MM-DD"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            # Admins see all data, managers see only their own data
            manager_id = None if request.user.user_type == 'admin' else request.user.id

            # Get dashboard KPI data
            data = InquirySelectors.get_kpi_dashboard_data(
                date_from=date_from,
                date_to=date_to,
                manager_id=manager_id
            )

            # Convert managers_performance to API format
            restructured_data = []
            for manager_data in data['managers_performance']:
                # Get performance grade for this manager
                manager_grade = PerformanceTargetServices.get_performance_grade(
                    manager_id=manager_data['sales_manager']['id'],
                    date_from=date_from,
                    date_to=date_to
                )
                manager_data['performance_grade'] = manager_grade.get('grade', 'unknown')
                restructured_manager = {
                    "manager": {
                        "username": manager_data['sales_manager']['username'],
                        "id": manager_data['sales_manager']['id'],
                        "first_name": manager_data['sales_manager']['name'].split()[0] if ' ' in manager_data['sales_manager']['name'] else manager_data['sales_manager']['name'],
                        "last_name": manager_data['sales_manager']['name'].split()[1] if ' ' in manager_data['sales_manager']['name'] else ""
                    },
                    "inquiries": {
                        "total": manager_data['manager_total'],
                        "pending": manager_data['manager_pending'],
                        "quoted": manager_data['manager_quoted'],
                        "failed": manager_data['manager_failed'],
                        "success": manager_data['manager_success']
                    },
                    "kpi": {
                        "response_time": f"{manager_data['response_time_percentage']}",
                        "follow_up": f"{manager_data['follow_up_percentage']}",
                        "conversion_rate": f"{manager_data['conversion_rate']}",
                        "new_customer": f"{manager_data['new_customers_percentage']}",
                        "overall_performance": f"{manager_data['overall_performance']}",
                        "performance_grade": manager_data.get('performance_grade', 'unknown')
                    }
                }
                restructured_data.append(restructured_manager)

            return Response(
                restructured_data,
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return Response(
                {"message": f"Error retrieving dashboard KPI data: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )


class InquiryQuoteApiView(APIView):
    """
    Quote an inquiry (triggers KPI calculation)
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class QuoteInputSerializer(serializers.Serializer):
        pass  # No input needed - backend uses timezone.now()

    class QuoteOutputSerializer(serializers.Serializer):
        id = serializers.IntegerField()
        status = serializers.CharField()
        quoted_at = serializers.DateTimeField()
        quote_time = serializers.DurationField()
        quote_grade = serializers.CharField()
        message = serializers.CharField()

    @extend_schema(
        tags=["KPI Actions"],
        summary="Quote Inquiry",
        description="Mark inquiry as quoted and calculate KPI metrics",
        request=QuoteInputSerializer,
        responses={200: QuoteOutputSerializer},
    )
    def post(self, request, inquiry_id):
        try:
            inquiry = InquirySelectors.get_inquiry_instance_by_id(inquiry_id=inquiry_id)

            serializer = self.QuoteInputSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            quoted_at = serializer.validated_data.get('quoted_at')

            # Quote the inquiry
            updated_inquiry = InquiryKPIServices.quote_inquiry(
                inquiry=inquiry,
                quoted_at=quoted_at
            )

            return Response({
                "id": updated_inquiry.id,
                "status": updated_inquiry.status,
                "quoted_at": updated_inquiry.quoted_at,
                "quote_time": updated_inquiry.quote_time,
                "quote_grade": updated_inquiry.quote_grade,
                "message": "Inquiry quoted successfully"
            }, status=status.HTTP_200_OK)

        except Inquiry.DoesNotExist:
            return Response(
                {"message": "Inquiry not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except ValueError as e:
            return Response(
                {"message": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class InquirySuccessApiView(APIView):
    """
    Mark inquiry as successful (triggers completion KPI)
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class SuccessInputSerializer(serializers.Serializer):
        pass  # No input needed - backend uses timezone.now()

    class SuccessOutputSerializer(serializers.Serializer):
        id = serializers.IntegerField()
        status = serializers.CharField()
        success_at = serializers.DateTimeField()
        resolution_time = serializers.DurationField()
        completion_grade = serializers.CharField()
        message = serializers.CharField()

    @extend_schema(
        tags=["KPI Actions"],
        summary="Mark Inquiry as Successful",
        description="Mark inquiry as successful and calculate completion KPI metrics",
        request=SuccessInputSerializer,
        responses={200: SuccessOutputSerializer},
    )
    def post(self, request, inquiry_id):
        try:
            inquiry = InquirySelectors.get_inquiry_instance_by_id(inquiry_id=inquiry_id)

            serializer = self.SuccessInputSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            success_at = serializer.validated_data.get('success_at')

            # Mark as successful
            updated_inquiry = InquiryKPIServices.complete_inquiry_success(
                inquiry=inquiry,
                success_at=success_at
            )

            return Response({
                "id": updated_inquiry.id,
                "status": updated_inquiry.status,
                "success_at": updated_inquiry.success_at,
                "resolution_time": updated_inquiry.resolution_time,
                "completion_grade": updated_inquiry.completion_grade,
                "message": "Inquiry marked as successful"
            }, status=status.HTTP_200_OK)

        except Inquiry.DoesNotExist:
            return Response(
                {"message": "Inquiry not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except ValueError as e:
            return Response(
                {"message": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )




class InquiryFailedApiView(APIView):
    """
    Mark inquiry as failed (triggers completion KPI)
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class FailedInputSerializer(serializers.Serializer):
        pass  # No input needed - backend uses timezone.now()

    class FailedOutputSerializer(serializers.Serializer):
        id = serializers.IntegerField()
        status = serializers.CharField()
        failed_at = serializers.DateTimeField()
        resolution_time = serializers.DurationField()
        completion_grade = serializers.CharField()
        message = serializers.CharField()

    @extend_schema(
        tags=["KPI Actions"],
        summary="Mark Inquiry as Failed",
        description="Mark inquiry as failed and calculate completion KPI metrics",
        request=FailedInputSerializer,
        responses={200: FailedOutputSerializer},
    )
    def post(self, request, inquiry_id):
        try:
            inquiry = InquirySelectors.get_inquiry_instance_by_id(inquiry_id=inquiry_id)

            serializer = self.FailedInputSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            failed_at = serializer.validated_data.get("failed_at")

            # Mark as failed
            updated_inquiry = InquiryKPIServices.complete_inquiry_failed(
                inquiry=inquiry,
                failed_at=failed_at
            )

            return Response({
                "id": updated_inquiry.id,
                "status": updated_inquiry.status,
                "failed_at": updated_inquiry.failed_at,
                "resolution_time": updated_inquiry.resolution_time,
                "completion_grade": updated_inquiry.completion_grade,
                "message": "Inquiry marked as failed"
            }, status=status.HTTP_200_OK)

        except Inquiry.DoesNotExist:
            return Response(
                {"message": "Inquiry not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except ValueError as e:
            return Response(
                {"message": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class InquiryKPILockApiView(APIView):
    """
    Lock/unlock KPI recalculation for an inquiry
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class KPILockInputSerializer(serializers.Serializer):
        lock = serializers.BooleanField(
            help_text="True to lock KPI, False to unlock"
        )

    class KPILockOutputSerializer(serializers.Serializer):
        id = serializers.IntegerField()
        is_locked = serializers.BooleanField()
        message = serializers.CharField()

    @extend_schema(
        tags=["KPI Actions"],
        summary="Lock/Unlock KPI Recalculation",
        description="Lock or unlock KPI recalculation for an inquiry",
        request=KPILockInputSerializer,
        responses={200: KPILockOutputSerializer},
    )
    def post(self, request, inquiry_id):
        try:
            inquiry = InquirySelectors.get_inquiry_instance_by_id(inquiry_id=inquiry_id)

            serializer = self.KPILockInputSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)

            lock = serializer.validated_data["lock"]

            if lock:
                updated_inquiry = InquiryKPIServices.lock_inquiry_kpi(inquiry=inquiry)
                message = "KPI locked successfully"
            else:
                updated_inquiry = InquiryKPIServices.unlock_inquiry_kpi(inquiry=inquiry)
                message = "KPI unlocked successfully"

            return Response({
                "id": updated_inquiry.id,
                "is_locked": updated_inquiry.is_locked,
                "message": message
            }, status=status.HTTP_200_OK)

        except Inquiry.DoesNotExist:
            return Response(
                {"message": "Inquiry not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except ValueError as e:
            return Response(
                {"message": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class KPIWeightsApiView(APIView):
    """
    Get current KPI weights configuration
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class KPIWeightsOutputSerializer(serializers.Serializer):
        response_time_weight = serializers.FloatField()
        follow_up_weight = serializers.FloatField()
        conversion_rate_weight = serializers.FloatField()
        new_customer_weight = serializers.FloatField()
        total_weight = serializers.FloatField(read_only=True)
        created_at = serializers.DateTimeField(read_only=True)
        created_by = inline_serializer(
            fields={
                "id": serializers.IntegerField(read_only=True),
                "username": serializers.CharField(read_only=True),
                "email": serializers.EmailField(read_only=True),
            },
            allow_null=True,
            read_only=True
        )

    @extend_schema(
        tags=["KPI Weights"],
        summary="Get Current KPI Weights",
        description="Get the current KPI weights configuration",
        responses={200: KPIWeightsOutputSerializer},
    )
    def get(self, request):
        weights_instance = KPIWeightsServices.get_current_weights_instance()

        if weights_instance:
            return Response(
                self.KPIWeightsOutputSerializer(weights_instance).data,
                status=status.HTTP_200_OK
            )
        else:
            # Return default weights if no configuration exists
            default_weights = KPIWeights.get_default_weights()
            default_response = {
                **default_weights,
                "total_weight": 100.0,
                "created_at": None,
                "created_by": None
            }
            return Response(default_response, status=status.HTTP_200_OK)


class ManagerSelfKPIApiView(APIView):
    """
    Get KPI metrics for the current authenticated manager
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class ManagerSelfKPIOutputSerializer(serializers.Serializer):
        response_time = serializers.FloatField()
        follow_up = serializers.FloatField()
        conversion_rate = serializers.FloatField()
        new_customer = serializers.FloatField()
        overall_performance = serializers.FloatField()
        performance_grade = serializers.CharField()
        inquiry_count = serializers.IntegerField()
        target_bracket = serializers.CharField()

    @extend_schema(
        tags=["My KPI"],
        summary="Get My KPI Performance Metrics",
        description="Get KPI performance metrics for the current authenticated manager",
        parameters=[
            OpenApiParameter(
                "date_from",
                OpenApiTypes.DATE,
                description="Filter from date (YYYY-MM-DD)",
                required=False
            ),
            OpenApiParameter(
                "date_to",
                OpenApiTypes.DATE,
                description="Filter to date (YYYY-MM-DD)",
                required=False
            ),
        ],
        responses={200: ManagerSelfKPIOutputSerializer},
    )
    def get(self, request):
        try:
            # Parse date parameters
            date_from = None
            date_to = None

            if request.query_params.get('date_from'):
                try:
                    date_from = datetime.strptime(request.query_params['date_from'], '%Y-%m-%d')
                except ValueError:
                    return Response(
                        {"message": "Invalid date_from format. Use YYYY-MM-DD"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            if request.query_params.get('date_to'):
                try:
                    date_to = datetime.strptime(request.query_params['date_to'], '%Y-%m-%d')
                except ValueError:
                    return Response(
                        {"message": "Invalid date_to format. Use YYYY-MM-DD"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            # Get KPI statistics for current manager only
            current_manager_id = request.user.id
            manager_stats = InquirySelectors.get_manager_kpi_statistics(
                manager_id=current_manager_id,
                date_from=date_from,
                date_to=date_to
            )

            # If no inquiries found for this manager, return zeros with grade
            if not manager_stats or manager_stats['total_inquiries'] == 0:
                grade_data = PerformanceTargetServices.get_performance_grade(
                    manager_id=current_manager_id,
                    date_from=date_from,
                    date_to=date_to
                )

                return Response({
                    "response_time": 0.00,
                    "follow_up": 0.00,
                    "conversion_rate": 0.00,
                    "new_customer": 0.00,
                    "overall_performance": 0.00,
                    "performance_grade": grade_data.get('grade', 'unknown'),
                    "inquiry_count": grade_data.get('inquiry_count', 0),
                    "target_bracket": grade_data.get('target_bracket', 'not_configured')
                }, status=status.HTTP_200_OK)

            # Calculate performance percentages similar to dashboard logic
            # Response time percentage (quote efficiency)
            max_quote_points = manager_stats['total_inquiries'] * 3
            response_time_percentage = (
                (manager_stats['total_quote_points'] / max_quote_points * 100)
                if max_quote_points > 0 else 0.0
            )

            # Follow-up percentage (completion efficiency)
            max_completion_points = manager_stats['completed_inquiries'] * 3
            follow_up_percentage = (
                (manager_stats['total_completion_points'] / max_completion_points * 100)
                if max_completion_points > 0 else 0.0
            )

            # Get weighted overall performance
            from .services import KPIWeightsServices
            overall_performance = KPIWeightsServices.calculate_weighted_kpi_score(
                response_time_percentage=response_time_percentage,
                follow_up_percentage=follow_up_percentage,
                conversion_rate=manager_stats['conversion_rate'],
                new_customer_percentage=manager_stats['lead_generation_rate']
            )

            # Get performance grade
            grade_data = PerformanceTargetServices.get_performance_grade(
                manager_id=current_manager_id,
                date_from=date_from,
                date_to=date_to
            )

            # Format response to match KPISerializer structure with decimal values
            response_data = {
                "response_time": round(response_time_percentage or 0, 2),
                "follow_up": round(follow_up_percentage or 0, 2),
                "conversion_rate": round(manager_stats.get('conversion_rate') or 0, 2),
                "new_customer": round(manager_stats.get('lead_generation_rate') or 0, 2),
                "overall_performance": round(overall_performance or 0, 2),
                "performance_grade": grade_data.get('grade', 'unknown'),
                "inquiry_count": grade_data.get('inquiry_count', 0),
                "target_bracket": grade_data.get('target_bracket', 'not_configured')
            }

            return Response(
                self.ManagerSelfKPIOutputSerializer(response_data).data,
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return Response(
                {"message": f"Error retrieving KPI metrics: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )


class KPIWeightsUpdateApiView(APIView):
    """
    Update KPI weights configuration (Admin only)
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAdminOnly]

    class KPIWeightsUpdateSerializer(serializers.Serializer):
        response_time_weight = serializers.DecimalField(
            max_digits=5,
            decimal_places=2,
            min_value=0,
            help_text="Weight for response time KPI (0-100)"
        )
        follow_up_weight = serializers.DecimalField(
            max_digits=5,
            decimal_places=2,
            min_value=0,
            help_text="Weight for follow-up KPI (0-100)"
        )
        conversion_rate_weight = serializers.DecimalField(
            max_digits=5,
            decimal_places=2,
            min_value=0,
            help_text="Weight for conversion rate KPI (0-100)"
        )
        new_customer_weight = serializers.DecimalField(
            max_digits=5,
            decimal_places=2,
            min_value=0,
            help_text="Weight for new customer KPI (0-100)"
        )

        def validate(self, data):
            # Validate that weights sum to 100%
            total = (
                data["response_time_weight"] +
                data["follow_up_weight"] +
                data["conversion_rate_weight"] +
                data["new_customer_weight"]
            )

            if abs(total - 100) > 0.01:  # Allow small floating point differences
                raise serializers.ValidationError(
                    f"Weights must sum to 100%. Current total: {total}%"
                )

            return data

    class KPIWeightsUpdateOutputSerializer(serializers.Serializer):
        id = serializers.IntegerField()
        response_time_weight = serializers.FloatField()
        follow_up_weight = serializers.FloatField()
        conversion_rate_weight = serializers.FloatField()
        new_customer_weight = serializers.FloatField()
        total_weight = serializers.FloatField()
        created_at = serializers.DateTimeField()
        created_by = inline_serializer(
            fields={
                "id": serializers.IntegerField(),
                "username": serializers.CharField(),
                "email": serializers.EmailField(),
            },
            allow_null=True
        )
        message = serializers.CharField()

    @extend_schema(
        tags=["KPI Weights"],
        summary="Update KPI Weights",
        description="Update the KPI weights configuration (replaces existing config)",
        request=KPIWeightsUpdateSerializer,
        responses={200: KPIWeightsUpdateOutputSerializer},
    )
    def put(self, request):
        serializer = self.KPIWeightsUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            # Create new weights configuration (replaces existing)
            weights = KPIWeightsServices.create_weights_configuration(
                response_time_weight=float(serializer.validated_data["response_time_weight"]),
                follow_up_weight=float(serializer.validated_data["follow_up_weight"]),
                conversion_rate_weight=float(serializer.validated_data["conversion_rate_weight"]),
                new_customer_weight=float(serializer.validated_data["new_customer_weight"]),
                created_by=request.user
            )

            response_data = {
                "id": weights.id,
                "response_time_weight": float(weights.response_time_weight),
                "follow_up_weight": float(weights.follow_up_weight),
                "conversion_rate_weight": float(weights.conversion_rate_weight),
                "new_customer_weight": float(weights.new_customer_weight),
                "total_weight": float(weights.total_weight),
                "created_at": weights.created_at,
                "created_by": {
                    "id": weights.created_by.id if weights.created_by else None,
                    "username": weights.created_by.username if weights.created_by else None,
                    "email": weights.created_by.email if weights.created_by else None,
                } if weights.created_by else None,
                "message": "KPI weights updated successfully"
            }

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"message": f"Error updating KPI weights: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )


# Performance Target Management APIs

class PerformanceTargetListApiView(APIView):
    """
    List all performance target configurations
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAdminOnly]

    class TargetListOutputSerializer(serializers.Serializer):
        id = serializers.IntegerField(read_only=True)
        volume_range = serializers.CharField(read_only=True)
        min_inquiries = serializers.IntegerField(read_only=True)
        max_inquiries = serializers.IntegerField(read_only=True, allow_null=True)
        excellent_threshold = serializers.FloatField()
        is_active = serializers.BooleanField(read_only=True)
        created_at = serializers.DateTimeField(read_only=True)
        updated_at = serializers.DateTimeField(read_only=True)

    @extend_schema(
        tags=["Performance Targets"],
        summary="List Performance Targets",
        description="Get all performance target configurations (Admin only)",
        parameters=[
            OpenApiParameter(
                "include_inactive",
                OpenApiTypes.BOOL,
                description="Include inactive targets (default: false)",
                required=False
            ),
        ],
        responses={200: TargetListOutputSerializer(many=True)},
    )
    def get(self, request):
        include_inactive = request.query_params.get('include_inactive', 'false').lower() == 'true'

        try:
            targets = PerformanceTargetSelectors.get_all_targets(include_inactive=include_inactive)

            # Format the data
            targets_data = []
            for target in targets:
                target_data = {
                    'id': target.id,
                    'volume_range': target.volume_display,
                    'min_inquiries': target.min_inquiries,
                    'max_inquiries': target.max_inquiries,
                    'excellent_threshold': target.excellent_threshold,
                    'is_active': target.is_active,
                    'created_at': target.created_at,
                    'updated_at': target.updated_at,
                }
                targets_data.append(target_data)

            return Response(
                self.TargetListOutputSerializer(targets_data, many=True).data,
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return Response(
                {"message": f"Error retrieving targets: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )


class PerformanceTargetCreateApiView(APIView):
    """
    Create a new performance target configuration
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAdminOnly]

    class TargetCreateInputSerializer(serializers.Serializer):
        min_inquiries = serializers.IntegerField(min_value=0)
        max_inquiries = serializers.IntegerField(min_value=0, required=False, allow_null=True)
        excellent_threshold = serializers.FloatField(min_value=0, max_value=100)

        def validate(self, data):
            # Validate volume range
            if data.get('max_inquiries') is not None and data['max_inquiries'] < data['min_inquiries']:
                raise serializers.ValidationError(
                    "max_inquiries must be greater than or equal to min_inquiries"
                )

            return data

    class TargetCreateOutputSerializer(serializers.Serializer):
        id = serializers.IntegerField(read_only=True)
        volume_range = serializers.CharField(read_only=True)
        min_inquiries = serializers.IntegerField(read_only=True)
        max_inquiries = serializers.IntegerField(read_only=True, allow_null=True)
        excellent_threshold = serializers.FloatField()
        is_active = serializers.BooleanField(read_only=True)
        created_at = serializers.DateTimeField(read_only=True)
        message = serializers.CharField(read_only=True)

    @extend_schema(
        tags=["Performance Targets"],
        summary="Create Performance Target",
        description="Create new performance target configuration (Admin only)",
        request=TargetCreateInputSerializer,
        responses={201: TargetCreateOutputSerializer},
    )
    def post(self, request):
        serializer = self.TargetCreateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            target = PerformanceTargetServices.create_target(
                min_inquiries=serializer.validated_data['min_inquiries'],
                max_inquiries=serializer.validated_data.get('max_inquiries'),
                excellent_threshold=serializer.validated_data['excellent_threshold']
            )

            response_data = {
                'id': target.id,
                'volume_range': target.volume_display,
                'min_inquiries': target.min_inquiries,
                'max_inquiries': target.max_inquiries,
                'excellent_threshold': target.excellent_threshold,
                'is_active': target.is_active,
                'created_at': target.created_at,
                'message': 'Performance target created successfully'
            }

            return Response(
                self.TargetCreateOutputSerializer(response_data).data,
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            return Response(
                {"message": f"Error creating target: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )


class PerformanceTargetUpdateApiView(APIView):
    """
    Bulk create/update performance target configurations
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAdminOnly]

    class TargetItemInputSerializer(serializers.Serializer):
        id = serializers.IntegerField(required=False)
        min_inquiries = serializers.IntegerField(min_value=0)
        max_inquiries = serializers.IntegerField(min_value=0, required=False, allow_null=True)
        excellent_kpi = serializers.FloatField(min_value=0, max_value=100)
        is_active = serializers.BooleanField(required=False, default=True)

    class TargetBulkInputSerializer(serializers.Serializer):
        def to_internal_value(self, data):
            if not isinstance(data, list):
                raise serializers.ValidationError("Expected a list of targets")

            validated_items = []
            for i, item in enumerate(data):
                item_serializer = PerformanceTargetUpdateApiView.TargetItemInputSerializer(data=item)
                try:
                    item_serializer.is_valid(raise_exception=True)
                    validated_items.append(item_serializer.validated_data)
                except serializers.ValidationError as e:
                    raise serializers.ValidationError({f"item_{i}": e.detail})

            return validated_items

    class TargetItemOutputSerializer(serializers.Serializer):
        id = serializers.IntegerField(read_only=True)
        volume_range = serializers.CharField(read_only=True)
        min_inquiries = serializers.IntegerField(read_only=True)
        max_inquiries = serializers.IntegerField(read_only=True, allow_null=True)
        excellent_threshold = serializers.FloatField()
        is_active = serializers.BooleanField(read_only=True)
        updated_at = serializers.DateTimeField(read_only=True)

    class TargetBulkOutputSerializer(serializers.Serializer):
        targets = serializers.ListField(read_only=True)
        message = serializers.CharField(read_only=True)

    @extend_schema(
        tags=["Performance Targets"],
        summary="Bulk Create/Update Performance Targets",
        description="Bulk create or update performance target configurations. If 'id' is present, update existing target; otherwise create new one (Admin only)",
        request=TargetBulkInputSerializer,
        responses={200: TargetBulkOutputSerializer},
        examples=[
            OpenApiExample(
                'Bulk Create/Update Example',
                value=[
                    {
                        "min_inquiries": 0,
                        "max_inquiries": 25,
                        "excellent_kpi": 90
                    },
                    {
                        "id": 1,
                        "min_inquiries": 26,
                        "max_inquiries": 50,
                        "excellent_kpi": 85
                    }
                ]
            )
        ]
    )
    def put(self, request, target_id=None):
        serializer = self.TargetBulkInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            targets = PerformanceTargetServices.bulk_create_update_targets(
                targets_data=serializer.validated_data
            )

            targets_data = []
            for target in targets:
                targets_data.append({
                    'id': target.id,
                    'volume_range': target.volume_display,
                    'min_inquiries': target.min_inquiries,
                    'max_inquiries': target.max_inquiries,
                    'excellent_threshold': target.excellent_threshold,
                    'is_active': target.is_active,
                    'updated_at': target.updated_at,
                })

            response_data = {
                'targets': targets_data,
                'message': f'Successfully processed {len(targets)} performance targets'
            }

            return Response(
                self.TargetBulkOutputSerializer(response_data).data,
                status=status.HTTP_200_OK
            )

        except PerformanceTarget.DoesNotExist:
            return Response(
                {"message": "One or more performance targets not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"message": f"Error processing targets: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )


class PerformanceTargetDeleteApiView(APIView):
    """
    Delete performance target configuration
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAdminOnly]

    class DeleteSuccessSerializer(serializers.Serializer):
        message = serializers.CharField()

    @extend_schema(
        tags=["Performance Targets"],
        summary="Delete Performance Target",
        description="Delete performance target configuration (Admin only)",
        responses={200: DeleteSuccessSerializer},
    )
    def delete(self, request, target_id):
        try:
            PerformanceTargetServices.delete_target(target_id=target_id)

            return Response(
                self.DeleteSuccessSerializer(
                    {"message": "Performance target deleted successfully"}
                ).data,
                status=status.HTTP_200_OK,
            )

        except PerformanceTarget.DoesNotExist:
            return Response(
                {"message": "Performance target not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"message": f"Error deleting target: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )


class ManagerPerformanceGradeApiView(APIView):
    """
    Get performance grade for the current manager
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class PerformanceGradeOutputSerializer(serializers.Serializer):
        grade = serializers.CharField(read_only=True)
        performance = serializers.FloatField(read_only=True)
        inquiry_count = serializers.IntegerField(read_only=True)
        target_bracket = serializers.CharField(read_only=True)
        thresholds = inline_serializer(
            fields={
                "excellent": serializers.FloatField(),
                "good": serializers.FloatField(),
                "average": serializers.FloatField(),
            }
        )

    @extend_schema(
        tags=["My Performance"],
        summary="Get My Performance Grade",
        description="Get current month's performance grade for authenticated manager",
        parameters=[
            OpenApiParameter(
                "date_from",
                OpenApiTypes.DATE,
                description="Filter from date (YYYY-MM-DD) - defaults to current month start",
                required=False
            ),
            OpenApiParameter(
                "date_to",
                OpenApiTypes.DATE,
                description="Filter to date (YYYY-MM-DD) - defaults to current month end",
                required=False
            ),
        ],
        responses={200: PerformanceGradeOutputSerializer},
    )
    def get(self, request):
        try:
            # Parse date parameters
            date_from = None
            date_to = None

            if request.query_params.get('date_from'):
                try:
                    date_from = datetime.strptime(request.query_params['date_from'], '%Y-%m-%d')
                except ValueError:
                    return Response(
                        {"message": "Invalid date_from format. Use YYYY-MM-DD"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            if request.query_params.get('date_to'):
                try:
                    date_to = datetime.strptime(request.query_params['date_to'], '%Y-%m-%d')
                except ValueError:
                    return Response(
                        {"message": "Invalid date_to format. Use YYYY-MM-DD"},
                        status=status.HTTP_400_BAD_REQUEST
                    )

            # Get performance grade for current manager
            grade_data = PerformanceTargetServices.get_performance_grade(
                manager_id=request.user.id,
                date_from=date_from,
                date_to=date_to
            )

            # Return formatted response
            return Response(
                self.PerformanceGradeOutputSerializer({
                    'grade': grade_data['grade'],
                    'performance': grade_data['performance'],
                    'inquiry_count': grade_data['inquiry_count'],
                    'target_bracket': grade_data['target_bracket'],
                    'thresholds': grade_data['thresholds']
                }).data,
                status=status.HTTP_200_OK
            )

        except Exception as e:
            return Response(
                {"message": f"Error retrieving performance grade: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST
            )
