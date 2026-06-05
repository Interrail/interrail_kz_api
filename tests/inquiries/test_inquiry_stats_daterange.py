"""Inquiry stats endpoint date-range filtering tests."""

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
    # created_at is auto_now_add; .update() bypasses it
    Inquiry.objects.filter(id=inquiry.id).update(created_at=timezone.make_aware(dt))


@pytest.mark.django_db
class TestInquiryStatsDateRange:
    @pytest.fixture
    def admin_user(self):
        return CustomUser.objects.create_user(
            username="admin", email="admin@example.com",
            password="testpass123", user_type="admin",
        )

    def test_stats_respects_date_range(self, admin_user):
        in_range = Inquiry.objects.create(
            client="InRange", status="success", text="x", sales_manager=admin_user
        )
        out_range = Inquiry.objects.create(
            client="OutRange", status="pending", text="y", sales_manager=admin_user
        )
        _set_created(in_range, datetime.datetime(2026, 6, 5, 10, 0))
        _set_created(out_range, datetime.datetime(2026, 1, 1, 10, 0))

        url = reverse("inquiries:inquiry-stats")
        resp = _auth_client(admin_user).get(
            url, {"date_from": "2026-06-01", "date_to": "2026-06-30"}
        )

        assert resp.status_code == status.HTTP_200_OK
        assert resp.data["total_inquiries"] == 1
        assert resp.data["success_count"] == 1
        assert resp.data["pending_count"] == 0

    def test_stats_invalid_date_returns_400(self, admin_user):
        url = reverse("inquiries:inquiry-stats")
        resp = _auth_client(admin_user).get(url, {"date_from": "not-a-date"})
        assert resp.status_code == status.HTTP_400_BAD_REQUEST

    def test_stats_no_date_returns_all(self, admin_user):
        Inquiry.objects.create(client="A", status="success", text="x", sales_manager=admin_user)
        Inquiry.objects.create(client="B", status="pending", text="y", sales_manager=admin_user)
        url = reverse("inquiries:inquiry-stats")
        resp = _auth_client(admin_user).get(url)
        assert resp.data["total_inquiries"] == 2
