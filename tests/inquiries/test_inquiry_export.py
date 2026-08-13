"""Inquiry Excel export endpoint tests."""

import io

import pandas as pd
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CustomUser
from apps.inquiries.models import Inquiry

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _auth_client(user):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    return client


def _read_xlsx(response):
    return pd.read_excel(io.BytesIO(response.content), engine="openpyxl")


@pytest.mark.django_db
class TestInquiryExport:
    @pytest.fixture
    def admin_user(self):
        return CustomUser.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="testpass123",
            user_type="admin",
        )

    @pytest.fixture
    def manager_user(self):
        return CustomUser.objects.create_user(
            username="manager",
            email="manager@example.com",
            password="testpass123",
            user_type="manager",
        )

    def test_export_requires_auth(self):
        url = reverse("inquiries:inquiry-export")
        response = APIClient().get(url)
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

    def test_export_returns_xlsx_with_all_rows_for_admin(self, admin_user):
        Inquiry.objects.create(client="Alpha", status="success", text="<p>hi</p>")
        # Beta has no text; the model requires text OR attachment, so attach a file.
        Inquiry.objects.create(
            client="Beta",
            status="pending",
            text=None,
            attachment=SimpleUploadedFile("beta.pdf", b"%PDF-1.4"),
        )

        url = reverse("inquiries:inquiry-export")
        response = _auth_client(admin_user).get(url)

        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == XLSX_CONTENT_TYPE
        assert "attachment;" in response["Content-Disposition"]
        assert ".xlsx" in response["Content-Disposition"]

        df = _read_xlsx(response)
        assert list(df.columns) == [
            "ID",
            "Sales Manager",
            "Client",
            "Status",
            "New Customer",
            "Text",
            "File",
            "Created At",
        ]
        assert set(df["Client"]) == {"Alpha", "Beta"}
        assert "hi" in set(df["Text"])
        assert "<p>" not in "".join(str(v) for v in df["Text"])

    def test_export_respects_status_filter(self, admin_user):
        Inquiry.objects.create(client="Win", status="success", text="win")
        Inquiry.objects.create(client="Lose", status="failed", text="lose")

        url = reverse("inquiries:inquiry-export")
        response = _auth_client(admin_user).get(url, {"status[]": "success"})

        df = _read_xlsx(response)
        assert set(df["Client"]) == {"Win"}

    def test_export_limits_non_admin_to_own_inquiries(self, manager_user):
        other = CustomUser.objects.create_user(
            username="other",
            email="other@example.com",
            password="testpass123",
            user_type="manager",
        )
        Inquiry.objects.create(client="Mine", sales_manager=manager_user, text="mine")
        Inquiry.objects.create(client="Theirs", sales_manager=other, text="theirs")

        url = reverse("inquiries:inquiry-export")
        response = _auth_client(manager_user).get(url)

        df = _read_xlsx(response)
        assert set(df["Client"]) == {"Mine"}
