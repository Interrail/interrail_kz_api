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
