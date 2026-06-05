"""Inquiry list endpoint date-range filtering tests."""

import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CustomUser
from apps.inquiries.models import Inquiry


def _auth_client(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _set_created(inquiry, dt):
    Inquiry.objects.filter(id=inquiry.id).update(
        created_at=timezone.make_aware(dt, timezone.get_current_timezone())
    )


@pytest.mark.django_db
class TestInquiryListDateRange:
    @pytest.fixture
    def admin_user(self):
        return CustomUser.objects.create_user(
            username="admin", email="admin@example.com",
            password="testpass123", user_type="admin",
        )

    def test_list_respects_date_range(self, admin_user):
        a = Inquiry.objects.create(client="InRange", status="success", text="x", sales_manager=admin_user)
        b = Inquiry.objects.create(client="OutRange", status="pending", text="y", sales_manager=admin_user)
        _set_created(a, datetime.datetime(2026, 6, 5, 10, 0))
        _set_created(b, datetime.datetime(2026, 1, 1, 10, 0))

        url = reverse("inquiries:inquiry-list")
        resp = _auth_client(admin_user).get(url, {"date_from": "2026-06-01", "date_to": "2026-06-30"})

        assert resp.status_code == status.HTTP_200_OK
        clients = [row["client"] for row in resp.data["results"]]
        assert clients == ["InRange"]
