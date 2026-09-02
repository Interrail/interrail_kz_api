"""
Regression tests for the 2026-08-26 audit findings on the orders feature.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CustomUser
from apps.inquiries.models import Inquiry
from apps.inquiries.services import InquiryServices
from apps.orders.models import Order
from apps.orders.selectors import OrderSelectors
from apps.orders.services import OrderServices


def make_manager(username):
    return CustomUser.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="testpass123",
        user_type="manager",
    )


def make_admin(username="theadmin"):
    return CustomUser.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="testpass123",
        user_type="admin",
    )


def make_order(manager, client="ACME"):
    inquiry = Inquiry.objects.create(
        client=client, text="x", status="success", sales_manager=manager
    )
    order = OrderServices.create_order(
        inquiry_id=inquiry.id,
        departure="Almaty",
        destination="Riga",
        transport_type="wagon",
        units_count=1,
        total_price=Decimal("100.00"),
        currency="USD",
        created_by=manager,
    )
    return inquiry, order


def auth(api_client, user):
    refresh = RefreshToken.for_user(user)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


# --- P1-1: manager scoping ---------------------------------------------------


@pytest.mark.django_db
class TestOrderScoping:
    def test_manager_list_sees_only_own_orders(self, api_client):
        a, b = make_manager("mgr_a"), make_manager("mgr_b")
        make_order(a, client="A Client")

        auth(api_client, b)
        response = api_client.get(reverse("orders:order-list"))
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 0

        auth(api_client, a)
        response = api_client.get(reverse("orders:order-list"))
        assert response.data["count"] == 1

    def test_admin_list_sees_all_orders(self, api_client):
        a = make_manager("mgr_a")
        make_order(a)
        auth(api_client, make_admin())
        response = api_client.get(reverse("orders:order-list"))
        assert response.data["count"] == 1

    def test_manager_cannot_read_or_update_foreign_order(self, api_client):
        a, b = make_manager("mgr_a"), make_manager("mgr_b")
        _, order = make_order(a)

        auth(api_client, b)
        detail = api_client.get(
            reverse("orders:order-detail", kwargs={"order_id": order.id})
        )
        assert detail.status_code == status.HTTP_404_NOT_FOUND

        update = api_client.put(
            reverse("orders:order-update", kwargs={"order_id": order.id}),
            {"units_count": 9},
            format="json",
        )
        assert update.status_code == status.HTTP_404_NOT_FOUND
        order.refresh_from_db()
        assert order.units_count == 1

    def test_manager_cannot_create_order_for_foreign_inquiry(self, api_client):
        a, b = make_manager("mgr_a"), make_manager("mgr_b")
        inquiry = Inquiry.objects.create(
            client="A Client", text="x", status="success", sales_manager=a
        )
        auth(api_client, b)
        response = api_client.post(
            reverse("orders:order-create"),
            {
                "inquiry_id": inquiry.id,
                "departure": "A",
                "destination": "B",
                "transport_type": "wagon",
                "units_count": 1,
                "total_price": "1.00",
                "currency": "USD",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Order.objects.filter(inquiry=inquiry).exists()

    def test_suggestions_scoped_to_own_clients_for_managers(self, api_client):
        a, b = make_manager("mgr_a"), make_manager("mgr_b")
        Inquiry.objects.create(client="Secret A Client", text="x", sales_manager=a)
        Inquiry.objects.create(client="B Client", text="x", sales_manager=b)

        auth(api_client, b)
        response = api_client.get(reverse("orders:client-suggestions"))
        names = [n.lower() for n in response.data["results"]]
        assert "b client" in names
        assert "secret a client" not in names

        auth(api_client, make_admin())
        response = api_client.get(reverse("orders:client-suggestions"))
        names = [n.lower() for n in response.data["results"]]
        assert "secret a client" in names


# --- P1-2: status invariant + safe delete ------------------------------------


@pytest.mark.django_db
class TestOrderedInquiryInvariant:
    def test_status_cannot_leave_success_while_order_exists(self):
        manager = make_manager("mgr")
        inquiry, _ = make_order(manager)
        with pytest.raises(ValueError, match="order"):
            InquiryServices.update_inquiry(inquiry=inquiry, status="failed")
        inquiry.refresh_from_db()
        assert inquiry.status == "success"

    def test_non_status_updates_still_allowed_with_order(self):
        manager = make_manager("mgr")
        inquiry, _ = make_order(manager)
        updated = InquiryServices.update_inquiry(inquiry=inquiry, comment="still fine")
        assert updated.comment == "still fine"

    def test_delete_with_order_raises_valueerror_not_protectederror(self):
        manager = make_manager("mgr")
        inquiry, _ = make_order(manager)
        # Force the inquiry past the status guard the way stale data could
        Inquiry.objects.filter(id=inquiry.id).update(status="failed")
        inquiry.refresh_from_db()
        with pytest.raises(ValueError):
            InquiryServices.delete_inquiry(inquiry=inquiry)
        assert Inquiry.objects.filter(id=inquiry.id).exists()


# --- P1-3: price must be positive --------------------------------------------


@pytest.mark.django_db
class TestPriceValidation:
    @pytest.mark.parametrize("bad_price", ["-500.00", "0.00"])
    def test_create_rejects_non_positive_price(self, api_client, bad_price):
        manager = make_manager("mgr")
        inquiry = Inquiry.objects.create(
            client="ACME", text="x", status="success", sales_manager=manager
        )
        auth(api_client, manager)
        response = api_client.post(
            reverse("orders:order-create"),
            {
                "inquiry_id": inquiry.id,
                "departure": "A",
                "destination": "B",
                "transport_type": "wagon",
                "units_count": 1,
                "total_price": bad_price,
                "currency": "USD",
            },
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_update_rejects_non_positive_price(self, api_client):
        manager = make_manager("mgr")
        _, order = make_order(manager)
        auth(api_client, manager)
        response = api_client.put(
            reverse("orders:order-update", kwargs={"order_id": order.id}),
            {"total_price": "-1.00"},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# --- P1-4: duplicate-create race returns 400, not 500 -------------------------


@pytest.mark.django_db(transaction=True)
class TestCreateRace:
    def test_integrity_error_becomes_valueerror(self):
        manager = make_manager("mgr")
        inquiry, _ = make_order(manager)
        # Simulate the loser of the race: the exists() check misses the
        # concurrent insert, save() then hits the one-to-one constraint.
        with patch.object(
            OrderSelectors, "order_exists_for_inquiry", return_value=False
        ):
            with pytest.raises(ValueError, match="[Oo]rder"):
                OrderServices.create_order(
                    inquiry_id=inquiry.id,
                    departure="A",
                    destination="B",
                    transport_type="wagon",
                    units_count=1,
                    total_price=Decimal("1.00"),
                    currency="USD",
                    created_by=manager,
                )


# --- P2: suggestions SQL does real DISTINCT ----------------------------------


@pytest.mark.django_db
class TestSuggestionsQuery:
    def test_distinct_not_defeated_by_model_ordering(self):
        from django.db import connection

        manager = make_manager("mgr")
        for _ in range(3):
            Inquiry.objects.create(
                client="Same Client", text="x", sales_manager=manager
            )

        with CaptureQueriesContext(connection) as ctx:
            names = OrderSelectors.get_client_suggestions(user=None)
        assert names == ["Same Client"]
        for q in ctx.captured_queries:
            if "DISTINCT" in q["sql"] and "client" in q["sql"]:
                assert "created_at" not in q["sql"]


# --- P2: partial update writes only its own fields ----------------------------


@pytest.mark.django_db
class TestUpdateFields:
    def test_concurrent_partial_updates_do_not_clobber(self):
        manager = make_manager("mgr")
        _, order = make_order(manager)

        stale_one = Order.objects.get(id=order.id)
        stale_two = Order.objects.get(id=order.id)

        OrderServices.update_order(order=stale_one, destination="Tallinn")
        OrderServices.update_order(order=stale_two, units_count=7)

        fresh = Order.objects.get(id=order.id)
        assert fresh.destination == "Tallinn"
        assert fresh.units_count == 7
