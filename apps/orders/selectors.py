from django.db.models import Q, QuerySet

from apps.accounts.models import CustomUser
from apps.inquiries.models import Inquiry

from .models import Order


def _is_admin(user) -> bool:
    return user is not None and user.user_type == "admin"


class OrderSelectors:
    """
    Selectors for order-related data queries.

    Ownership mirrors inquiries: a non-admin manager only ever sees orders
    whose inquiry they manage. user=None means "no scoping" (internal use).
    """

    @staticmethod
    def get_orders_list(
        *, search: str = "", user: CustomUser = None
    ) -> QuerySet[Order]:
        qs = Order.objects.select_related("inquiry", "created_by").all()
        if user is not None and not _is_admin(user):
            qs = qs.filter(inquiry__sales_manager=user)
        if search:
            qs = qs.filter(
                Q(client__icontains=search)
                | Q(departure__icontains=search)
                | Q(destination__icontains=search)
            )
        return qs

    @staticmethod
    def get_order_by_id(*, order_id: int, user: CustomUser = None) -> Order:
        qs = Order.objects.select_related("inquiry", "created_by")
        if user is not None and not _is_admin(user):
            qs = qs.filter(inquiry__sales_manager=user)
        return qs.get(id=order_id)

    @staticmethod
    def order_exists_for_inquiry(inquiry: Inquiry) -> bool:
        return Order.objects.filter(inquiry=inquiry).exists()

    @staticmethod
    def get_client_suggestions(
        *, search: str = "", limit: int = 20, user: CustomUser = None
    ) -> list[str]:
        """Distinct client names across inquiries and orders.

        Case-insensitive dedup keeps the first spelling seen; inquiry names come
        first since that is where nearly all history lives. Non-admin managers
        only get names from their own inquiries/orders — the same visibility
        the list endpoints give them.
        """
        scope_managers = user is not None and not _is_admin(user)

        seen: dict[str, str] = {}
        for model, owner_filter in (
            (Inquiry, {"sales_manager": user}),
            (Order, {"inquiry__sales_manager": user}),
        ):
            qs = model.objects.exclude(client="")
            if scope_managers:
                qs = qs.filter(**owner_filter)
            if search:
                qs = qs.filter(client__icontains=search)
            # order_by() clears Meta.ordering, which would otherwise join
            # created_at into SELECT DISTINCT and defeat the dedup in SQL
            for name in qs.order_by().values_list("client", flat=True).distinct():
                key = name.strip().lower()
                if key and key not in seen:
                    seen[key] = name.strip()

        return sorted(seen.values(), key=str.lower)[:limit]
