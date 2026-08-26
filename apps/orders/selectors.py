from django.db.models import Q, QuerySet

from .models import Order


class OrderSelectors:
    """
    Selectors for order-related data queries
    """

    @staticmethod
    def get_orders_list(*, search: str = "") -> QuerySet[Order]:
        qs = Order.objects.select_related("inquiry", "created_by").all()
        if search:
            qs = qs.filter(
                Q(client__icontains=search)
                | Q(departure__icontains=search)
                | Q(destination__icontains=search)
            )
        return qs

    @staticmethod
    def get_order_by_id(*, order_id: int) -> Order:
        return Order.objects.select_related("inquiry", "created_by").get(id=order_id)

    @staticmethod
    def get_client_suggestions(*, search: str = "", limit: int = 20) -> list[str]:
        """Distinct client names across inquiries and orders.

        Case-insensitive dedup keeps the first spelling seen; inquiry names come
        first since that is where nearly all history lives.
        """
        from apps.inquiries.models import Inquiry

        seen: dict[str, str] = {}
        for model in (Inquiry, Order):
            qs = model.objects.exclude(client="")
            if search:
                qs = qs.filter(client__icontains=search)
            for name in qs.values_list("client", flat=True).distinct():
                key = name.strip().lower()
                if key and key not in seen:
                    seen[key] = name.strip()

        return sorted(seen.values(), key=str.lower)[:limit]
