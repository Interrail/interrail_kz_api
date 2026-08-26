"""
Client-name suggestions for order/inquiry entry — the anti-duplication helper.
"""

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CustomUser
from apps.inquiries.models import Inquiry
from apps.orders.models import Order


@pytest.fixture
def manager_user(db):
    return CustomUser.objects.create_user(
        username="manager",
        email="manager@example.com",
        password="testpass123",
        user_type="manager",
    )


def auth(api_client, user):
    refresh = RefreshToken.for_user(user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


@pytest.mark.django_db
class TestClientSuggestions:
    def test_merges_inquiry_and_order_clients_dedup_case_insensitive(
        self, api_client, manager_user
    ):
        i1 = Inquiry.objects.create(
            client="EURASIA LOGISTICS JSC", text="x", status="success"
        )
        Inquiry.objects.create(client="eurasia logistics jsc", text="x")
        Inquiry.objects.create(client="InterRail Europe GmbH", text="x")
        Order.objects.create(
            inquiry=i1,
            client="Fresh Logistics LLP",
            departure="Almaty",
            destination="Riga",
            transport_type="wagon",
            units_count=1,
            total_price=Decimal("1.00"),
        )

        auth(api_client, manager_user)
        response = api_client.get(reverse("orders:client-suggestions"))

        assert response.status_code == status.HTTP_200_OK
        names = response.data["results"]
        # Case-insensitive dedup: one EURASIA entry, both sources merged
        lowered = [n.lower() for n in names]
        assert lowered.count("eurasia logistics jsc") == 1
        assert "interrail europe gmbh" in lowered
        assert "fresh logistics llp" in lowered

    def test_search_filters_case_insensitively(self, api_client, manager_user):
        Inquiry.objects.create(client="EURASIA LOGISTICS JSC", text="x")
        Inquiry.objects.create(client="InterRail Europe GmbH", text="x")

        auth(api_client, manager_user)
        response = api_client.get(
            reverse("orders:client-suggestions"), {"search": "eur"}
        )

        assert response.status_code == status.HTTP_200_OK
        names = response.data["results"]
        assert all("eur" in n.lower() for n in names)
        assert any("EURASIA" in n for n in names)

    def test_requires_manager(self, api_client):
        customer = CustomUser.objects.create_user(
            username="customer",
            email="c@example.com",
            password="testpass123",
            user_type="customer",
        )
        auth(api_client, customer)
        response = api_client.get(reverse("orders:client-suggestions"))
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestClientNormalization:
    def test_create_order_collapses_inner_whitespace(self, manager_user):
        from apps.orders.services import OrderServices

        inquiry = Inquiry.objects.create(
            client="ACME", text="x", status="success", sales_manager=manager_user
        )
        order = OrderServices.create_order(
            inquiry_id=inquiry.id,
            client="  ACME   Logistics  LLP ",
            departure="A",
            destination="B",
            transport_type="wagon",
            units_count=1,
            total_price=Decimal("1.00"),
            currency="USD",
            created_by=manager_user,
        )
        assert order.client == "ACME Logistics LLP"
