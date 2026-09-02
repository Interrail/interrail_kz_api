from decimal import Decimal

from drf_spectacular.openapi import OpenApiParameter, OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api_config.pagination import (
    CustomPageNumberPagination,
    get_paginated_response,
)
from apps.api_config.utils import inline_serializer
from apps.authentication.authentication import CookieJWTAuthentication
from apps.core.permissions import IsAdminOnly, IsManagerOrAdmin

from .models import Order
from .selectors import OrderSelectors
from .services import OrderServices


class OrderOutputSerializer(serializers.ModelSerializer):
    inquiry_id = serializers.IntegerField(source="inquiry.id", read_only=True)
    transport_type_display = serializers.CharField(
        source="get_transport_type_display", read_only=True
    )
    created_by = inline_serializer(
        fields={
            "id": serializers.IntegerField(read_only=True),
            "username": serializers.CharField(read_only=True),
        },
        allow_null=True,
    )

    class Meta:
        model = Order
        fields = [
            "id",
            "inquiry_id",
            "client",
            "departure",
            "destination",
            "transport_type",
            "transport_type_display",
            "units_count",
            "total_price",
            "currency",
            "created_by",
            "created_at",
            "updated_at",
        ]


class ClientSuggestionsApiView(APIView):
    """
    Distinct client names from inquiries and orders, for entry autocomplete.
    Keeps managers picking an existing spelling instead of typing a new one.
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    LIMIT = 20

    @extend_schema(
        tags=["Orders"],
        summary="Client name suggestions",
        parameters=[
            OpenApiParameter(
                "search", OpenApiTypes.STR, description="Substring, case-insensitive"
            ),
        ],
        responses={200: inline_serializer(fields={"results": serializers.ListField()})},
    )
    def get(self, request):
        search = request.query_params.get("search", "").strip()
        results = OrderSelectors.get_client_suggestions(
            search=search, limit=self.LIMIT, user=request.user
        )
        return Response({"results": results}, status=status.HTTP_200_OK)


class OrderCreateApiView(APIView):
    """
    Create an order from a successful inquiry
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class OrderCreateSerializer(serializers.Serializer):
        inquiry_id = serializers.IntegerField()
        client = serializers.CharField(
            max_length=255, required=False, allow_blank=True, default=""
        )
        departure = serializers.CharField(max_length=255)
        destination = serializers.CharField(max_length=255)
        transport_type = serializers.ChoiceField(choices=Order.TRANSPORT_TYPE_CHOICES)
        units_count = serializers.IntegerField(min_value=1)
        total_price = serializers.DecimalField(
            max_digits=14, decimal_places=2, min_value=Decimal("0.01")
        )
        currency = serializers.ChoiceField(
            choices=Order.CURRENCY_CHOICES, default="USD"
        )

    @extend_schema(
        tags=["Orders"],
        summary="Create Order",
        request=OrderCreateSerializer,
        responses={201: OrderOutputSerializer},
    )
    def post(self, request):
        serializer = self.OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            order = OrderServices.create_order(
                **serializer.validated_data, created_by=request.user
            )
        except ValueError as e:
            return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            OrderOutputSerializer(order).data, status=status.HTTP_201_CREATED
        )


class OrderListApiView(APIView):
    """
    List orders
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class Pagination(CustomPageNumberPagination):
        page_size = 10
        max_page_size = 50

    @extend_schema(
        tags=["Orders"],
        summary="List Orders",
        parameters=[
            OpenApiParameter("page", OpenApiTypes.INT, description="Page number"),
            OpenApiParameter(
                "page_size", OpenApiTypes.INT, description="Items per page"
            ),
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                description="Search by client, departure or destination",
            ),
        ],
        responses={200: OrderOutputSerializer},
    )
    def get(self, request):
        queryset = OrderSelectors.get_orders_list(
            search=request.query_params.get("search", ""), user=request.user
        )
        return get_paginated_response(
            pagination_class=self.Pagination,
            serializer_class=OrderOutputSerializer,
            queryset=queryset,
            request=request,
            view=self,
        )


class OrderDetailApiView(APIView):
    """
    Get order by id
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    @extend_schema(
        tags=["Orders"],
        summary="Get Order",
        responses={200: OrderOutputSerializer},
    )
    def get(self, request, order_id):
        try:
            order = OrderSelectors.get_order_by_id(order_id=order_id, user=request.user)
        except Order.DoesNotExist:
            return Response(
                {"message": "Order not found"}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(OrderOutputSerializer(order).data, status=status.HTTP_200_OK)


class OrderUpdateApiView(APIView):
    """
    Partially update an order
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class OrderUpdateSerializer(serializers.Serializer):
        client = serializers.CharField(max_length=255, required=False)
        departure = serializers.CharField(max_length=255, required=False)
        destination = serializers.CharField(max_length=255, required=False)
        transport_type = serializers.ChoiceField(
            choices=Order.TRANSPORT_TYPE_CHOICES, required=False
        )
        units_count = serializers.IntegerField(min_value=1, required=False)
        total_price = serializers.DecimalField(
            max_digits=14,
            decimal_places=2,
            required=False,
            min_value=Decimal("0.01"),
        )
        currency = serializers.ChoiceField(
            choices=Order.CURRENCY_CHOICES, required=False
        )

    @extend_schema(
        tags=["Orders"],
        summary="Update Order",
        request=OrderUpdateSerializer,
        responses={200: OrderOutputSerializer},
    )
    def put(self, request, order_id):
        try:
            order = OrderSelectors.get_order_by_id(order_id=order_id, user=request.user)
        except Order.DoesNotExist:
            return Response(
                {"message": "Order not found"}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = self.OrderUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            order = OrderServices.update_order(order=order, **serializer.validated_data)
        except ValueError as e:
            return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(OrderOutputSerializer(order).data, status=status.HTTP_200_OK)


class OrderDeleteApiView(APIView):
    """
    Delete an order
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAdminOnly]

    class DeleteSuccessSerializer(serializers.Serializer):
        message = serializers.CharField()

    @extend_schema(
        tags=["Orders"],
        summary="Delete Order",
        responses={200: DeleteSuccessSerializer},
    )
    def delete(self, request, order_id):
        try:
            order = OrderSelectors.get_order_by_id(order_id=order_id)
        except Order.DoesNotExist:
            return Response(
                {"message": "Order not found"}, status=status.HTTP_404_NOT_FOUND
            )

        OrderServices.delete_order(order=order)
        return Response(
            self.DeleteSuccessSerializer(
                {"message": "Order deleted successfully"}
            ).data,
            status=status.HTTP_200_OK,
        )
