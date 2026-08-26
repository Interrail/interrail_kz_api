from django.contrib import admin

from .models import Order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "client",
        "departure",
        "destination",
        "transport_type",
        "units_count",
        "total_price",
        "currency",
        "created_at",
    )
    search_fields = ("client", "departure", "destination")
    list_filter = ("transport_type", "currency")
