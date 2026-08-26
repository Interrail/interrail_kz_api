from decimal import Decimal

from django.db import transaction

from apps.accounts.models import CustomUser
from apps.inquiries.models import Inquiry

from .models import Order


def _normalize_client(name: str) -> str:
    """Collapse whitespace so 'ACME  LLP ' and 'ACME LLP' stay one client."""
    return " ".join(name.split())


class OrderServices:
    """
    Services for order-related business logic
    """

    @staticmethod
    def create_order(
        *,
        inquiry_id: int,
        departure: str,
        destination: str,
        transport_type: str,
        units_count: int,
        total_price: Decimal,
        currency: str = "USD",
        client: str = "",
        created_by: CustomUser = None,
    ) -> Order:
        """
        Create an order from a successful inquiry.
        Client defaults to the inquiry's client when not given.
        """
        try:
            inquiry = Inquiry.objects.get(id=inquiry_id)
        except Inquiry.DoesNotExist:
            raise ValueError("Inquiry not found")

        if inquiry.status != "success":
            raise ValueError("Order can only be created from a success inquiry")

        if Order.objects.filter(inquiry=inquiry).exists():
            raise ValueError("Order already exists for this inquiry")

        with transaction.atomic():
            order = Order(
                inquiry=inquiry,
                client=_normalize_client(client or inquiry.client),
                departure=departure.strip(),
                destination=destination.strip(),
                transport_type=transport_type,
                units_count=units_count,
                total_price=total_price,
                currency=currency,
                created_by=created_by,
            )
            order.full_clean()
            order.save()

        return order

    @staticmethod
    def update_order(*, order: Order, **fields) -> Order:
        """Partially update editable order fields."""
        editable = [
            "client",
            "departure",
            "destination",
            "transport_type",
            "units_count",
            "total_price",
            "currency",
        ]
        for field in editable:
            if field in fields and fields[field] is not None:
                value = fields[field]
                if field == "client":
                    value = _normalize_client(value)
                elif isinstance(value, str):
                    value = value.strip()
                setattr(order, field, value)

        order.full_clean()
        order.save()
        return order

    @staticmethod
    def delete_order(*, order: Order) -> None:
        order.delete()
