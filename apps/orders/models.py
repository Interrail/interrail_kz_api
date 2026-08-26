from django.core.validators import MinValueValidator
from django.db import models

from apps.accounts.models import CustomUser
from apps.core.models import TimeStampModel
from apps.inquiries.models import Inquiry


class Order(TimeStampModel):
    """A shipment order created from a successful inquiry (one per inquiry)."""

    TRANSPORT_TYPE_CHOICES = (
        ("wagon", "Wagon"),
        ("container", "Container"),
    )

    CURRENCY_CHOICES = (
        ("USD", "USD"),
        ("EUR", "EUR"),
        ("KZT", "KZT"),
        ("RUB", "RUB"),
    )

    # PROTECT: an inquiry with an order must not disappear silently — the order
    # is the business record of the deal.
    inquiry = models.OneToOneField(
        Inquiry, on_delete=models.PROTECT, related_name="order"
    )
    client = models.CharField(max_length=255)
    departure = models.CharField(max_length=255)
    destination = models.CharField(max_length=255)
    transport_type = models.CharField(max_length=20, choices=TRANSPORT_TYPE_CHOICES)
    units_count = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    total_price = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default="USD")
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        related_name="created_orders",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Order"
        verbose_name_plural = "Orders"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return (
            f"Order #{self.id} — {self.client} ({self.departure} → {self.destination})"
        )
