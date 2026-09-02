from decimal import Decimal

from django.db import IntegrityError, transaction

from apps.accounts.models import CustomUser
from apps.inquiries.models import Inquiry

from .models import Order
from .selectors import OrderSelectors


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
        A non-admin creator may only order against their own inquiry.
        """
        try:
            with transaction.atomic():
                # Lock the inquiry row so a concurrent status change and this
                # create serialize instead of interleaving
                try:
                    inquiry = Inquiry.objects.select_for_update().get(id=inquiry_id)
                except Inquiry.DoesNotExist:
                    raise ValueError("Inquiry not found")

                if (
                    created_by is not None
                    and created_by.user_type != "admin"
                    and inquiry.sales_manager_id != created_by.id
                ):
                    # Same answer as a missing inquiry: don't confirm foreign
                    # inquiries exist
                    raise ValueError("Inquiry not found")

                if inquiry.status != "success":
                    raise ValueError("Order can only be created from a success inquiry")

                if OrderSelectors.order_exists_for_inquiry(inquiry):
                    raise ValueError("Order already exists for this inquiry")

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
                # inquiry is set internally, not user input; its uniqueness is
                # enforced by the exists() pre-check plus the DB constraint
                # (mapped to ValueError below), keeping the race path handled
                order.full_clean(exclude=["inquiry"])
                order.save()
        except IntegrityError:
            # Loser of a concurrent create: the exists() check passed for both,
            # the one-to-one constraint stopped the second insert
            raise ValueError("Order already exists for this inquiry")

        return order

    @staticmethod
    def update_order(*, order: Order, **fields) -> Order:
        """Partially update order fields; writes only what was passed."""
        update_fields = []
        for field, value in fields.items():
            if value is None:
                continue
            if field == "client":
                value = _normalize_client(value)
            elif isinstance(value, str):
                value = value.strip()
            setattr(order, field, value)
            update_fields.append(field)

        if not update_fields:
            return order

        order.full_clean()
        order.save(update_fields=update_fields + ["updated_at"])
        return order

    @staticmethod
    def delete_order(*, order: Order) -> None:
        order.delete()
