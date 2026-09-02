"""
Order business logic tests.
An order is created from a successful inquiry only, one order per inquiry.
"""

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CustomUser
from apps.inquiries.models import Inquiry
from apps.orders.models import Order
from apps.orders.services import OrderServices


@pytest.fixture
def manager_user(db):
    return CustomUser.objects.create_user(
        username="manager",
        email="manager@example.com",
        password="testpass123",
        user_type="manager",
    )


@pytest.fixture
def success_inquiry(db, manager_user):
    return Inquiry.objects.create(
        client="Business Corp",
        text="Freight from Almaty to Riga",
        status="success",
        sales_manager=manager_user,
    )


def order_payload(inquiry, **overrides):
    payload = {
        "inquiry_id": inquiry.id,
        "departure": "Almaty",
        "destination": "Riga",
        "transport_type": "container",
        "units_count": 4,
        "total_price": "12500.00",
        "currency": "USD",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
class TestOrderService:
    def test_create_order_from_success_inquiry(self, success_inquiry, manager_user):
        order = OrderServices.create_order(
            inquiry_id=success_inquiry.id,
            departure="Almaty",
            destination="Riga",
            transport_type="container",
            units_count=4,
            total_price=Decimal("12500.00"),
            currency="USD",
            created_by=manager_user,
        )

        assert order.inquiry == success_inquiry
        # Client defaults to the inquiry's client when not given
        assert order.client == "Business Corp"
        assert order.departure == "Almaty"
        assert order.destination == "Riga"
        assert order.transport_type == "container"
        assert order.units_count == 4
        assert order.total_price == Decimal("12500.00")
        assert order.currency == "USD"
        assert order.created_by == manager_user

    def test_create_order_client_override(self, success_inquiry, manager_user):
        order = OrderServices.create_order(
            inquiry_id=success_inquiry.id,
            client="Other Client LLC",
            departure="Almaty",
            destination="Riga",
            transport_type="wagon",
            units_count=1,
            total_price=Decimal("100.00"),
            currency="EUR",
            created_by=manager_user,
        )
        assert order.client == "Other Client LLC"

    def test_rejects_non_success_inquiry(self, manager_user):
        inquiry = Inquiry.objects.create(
            client="Pending Co", text="x", status="pending", sales_manager=manager_user
        )
        with pytest.raises(ValueError, match="success"):
            OrderServices.create_order(
                inquiry_id=inquiry.id,
                departure="A",
                destination="B",
                transport_type="wagon",
                units_count=1,
                total_price=Decimal("1.00"),
                currency="USD",
                created_by=manager_user,
            )

    def test_rejects_second_order_for_same_inquiry(self, success_inquiry, manager_user):
        OrderServices.create_order(
            inquiry_id=success_inquiry.id,
            departure="A",
            destination="B",
            transport_type="wagon",
            units_count=1,
            total_price=Decimal("1.00"),
            currency="USD",
            created_by=manager_user,
        )
        with pytest.raises(ValueError, match="[Oo]rder"):
            OrderServices.create_order(
                inquiry_id=success_inquiry.id,
                departure="A",
                destination="B",
                transport_type="wagon",
                units_count=1,
                total_price=Decimal("1.00"),
                currency="USD",
                created_by=manager_user,
            )

    def test_rejects_missing_inquiry(self, manager_user):
        with pytest.raises(ValueError, match="not found"):
            OrderServices.create_order(
                inquiry_id=999999,
                departure="A",
                destination="B",
                transport_type="wagon",
                units_count=1,
                total_price=Decimal("1.00"),
                currency="USD",
                created_by=manager_user,
            )


@pytest.mark.django_db
class TestOrderApi:
    def auth(self, api_client, user):
        refresh = RefreshToken.for_user(user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def test_create_order_api(self, api_client, success_inquiry, manager_user):
        self.auth(api_client, manager_user)
        response = api_client.post(
            reverse("orders:order-create"),
            order_payload(success_inquiry),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert response.data["client"] == "Business Corp"
        assert Order.objects.filter(inquiry=success_inquiry).exists()

    def test_create_order_api_rejects_pending(self, api_client, manager_user):
        inquiry = Inquiry.objects.create(
            client="Pending Co", text="x", status="pending", sales_manager=manager_user
        )
        self.auth(api_client, manager_user)
        response = api_client.post(
            reverse("orders:order-create"), order_payload(inquiry), format="json"
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_create_order_api_requires_manager(self, api_client, success_inquiry):
        customer = CustomUser.objects.create_user(
            username="customer",
            email="customer@example.com",
            password="testpass123",
            user_type="customer",
        )
        self.auth(api_client, customer)
        response = api_client.post(
            reverse("orders:order-create"),
            order_payload(success_inquiry),
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_create_order_api_rejects_zero_units(
        self, api_client, success_inquiry, manager_user
    ):
        self.auth(api_client, manager_user)
        response = api_client.post(
            reverse("orders:order-create"),
            order_payload(success_inquiry, units_count=0),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_list_orders_api(self, api_client, success_inquiry, manager_user):
        OrderServices.create_order(
            inquiry_id=success_inquiry.id,
            departure="Almaty",
            destination="Riga",
            transport_type="container",
            units_count=4,
            total_price=Decimal("12500.00"),
            currency="USD",
            created_by=manager_user,
        )
        self.auth(api_client, manager_user)
        response = api_client.get(reverse("orders:order-list"))
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1
        row = response.data["results"][0]
        assert row["departure"] == "Almaty"
        assert row["inquiry_id"] == success_inquiry.id

    def test_inquiry_list_exposes_order_id(
        self, api_client, success_inquiry, manager_user
    ):
        order = OrderServices.create_order(
            inquiry_id=success_inquiry.id,
            departure="A",
            destination="B",
            transport_type="wagon",
            units_count=1,
            total_price=Decimal("1.00"),
            currency="USD",
            created_by=manager_user,
        )
        self.auth(api_client, manager_user)
        response = api_client.get(reverse("inquiries:inquiry-list"))
        assert response.status_code == status.HTTP_200_OK
        row = next(r for r in response.data["results"] if r["id"] == success_inquiry.id)
        assert row["order_id"] == order.id

    def test_update_order_api(self, api_client, success_inquiry, manager_user):
        order = OrderServices.create_order(
            inquiry_id=success_inquiry.id,
            departure="A",
            destination="B",
            transport_type="wagon",
            units_count=1,
            total_price=Decimal("1.00"),
            currency="USD",
            created_by=manager_user,
        )
        self.auth(api_client, manager_user)
        response = api_client.put(
            reverse("orders:order-update", kwargs={"order_id": order.id}),
            {"units_count": 7, "total_price": "999.50"},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        order.refresh_from_db()
        assert order.units_count == 7
        assert order.total_price == Decimal("999.50")
        # Untouched fields survive a partial update
        assert order.departure == "A"

    def test_delete_order_api_admin_only(
        self, api_client, success_inquiry, manager_user
    ):
        # Deletion follows the repo convention: destructive delete is admin-only.
        admin = CustomUser.objects.create_user(
            username="admin2",
            email="admin2@example.com",
            password="testpass123",
            user_type="admin",
        )
        order = OrderServices.create_order(
            inquiry_id=success_inquiry.id,
            departure="A",
            destination="B",
            transport_type="wagon",
            units_count=1,
            total_price=Decimal("1.00"),
            currency="USD",
            created_by=manager_user,
        )
        self.auth(api_client, manager_user)
        response = api_client.delete(
            reverse("orders:order-delete", kwargs={"order_id": order.id})
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

        self.auth(api_client, admin)
        response = api_client.delete(
            reverse("orders:order-delete", kwargs={"order_id": order.id})
        )
        assert response.status_code == status.HTTP_200_OK
        assert not Order.objects.filter(id=order.id).exists()
