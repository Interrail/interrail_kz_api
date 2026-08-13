"""
Limits on the one endpoint an anonymous caller can write through.

POST /api/inquiries/create/ has no authentication by design — @my_interrail_bot
posts here for Telegram users and holds no credentials. That makes it the only
way in for anonymous writes and file storage, so it carries a rate limit, and
uploads are restricted to document types.
"""

import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts.models import CustomUser
from apps.inquiries.models import Inquiry
from apps.inquiries.services import InquiryServices


@pytest.fixture
def anonymous_client():
    return APIClient()


@pytest.fixture
def sales_manager():
    return CustomUser.objects.create_user(
        username="limits_manager",
        email="limits@example.com",
        password="testpass123",
        user_type="manager",
    )


@pytest.fixture
def create_url():
    return reverse("inquiries:inquiry-create")


@pytest.fixture(autouse=True)
def clear_throttle_history():
    """Throttle counters live in the cache and would leak between tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
class TestAttachmentTypes:
    @pytest.mark.parametrize("name", ["report.pdf", "scan.png", "list.xlsx"])
    def test_document_uploads_are_accepted(
        self, anonymous_client, sales_manager, create_url, name
    ):
        response = anonymous_client.post(
            create_url,
            {
                "client": "Acme",
                "attachment": SimpleUploadedFile(name, b"payload"),
                "sales_manager_id": sales_manager.id,
            },
            format="multipart",
        )

        assert response.status_code == status.HTTP_201_CREATED

    @pytest.mark.parametrize("name", ["payload.html", "payload.svg", "payload.js"])
    def test_browser_executable_uploads_are_rejected(
        self, anonymous_client, sales_manager, create_url, name
    ):
        """These would run on the API's own origin: /media/ is served unauthenticated."""
        response = anonymous_client.post(
            create_url,
            {
                "client": "Acme",
                "attachment": SimpleUploadedFile(name, b"<script>alert(1)</script>"),
                "sales_manager_id": sales_manager.id,
            },
            format="multipart",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestCreateThrottle:
    def test_anonymous_creates_are_rate_limited(
        self, anonymous_client, sales_manager, create_url, monkeypatch
    ):
        """Two through, the third refused — the rate itself is a setting, the gate is not."""
        monkeypatch.setattr(
            ScopedRateThrottle, "THROTTLE_RATES", {"inquiry-create": "2/hour"}
        )
        cache.clear()

        def post():
            return anonymous_client.post(
                create_url,
                {
                    "client": "Acme",
                    "text": "please quote",
                    "sales_manager_id": sales_manager.id,
                },
                format="json",
            )

        assert post().status_code == status.HTTP_201_CREATED
        assert post().status_code == status.HTTP_201_CREATED
        assert post().status_code == status.HTTP_429_TOO_MANY_REQUESTS

    def test_uploads_answer_to_the_tighter_rate(
        self, anonymous_client, sales_manager, create_url, monkeypatch
    ):
        """A file-carrying request is limited harder than a plain one.

        Both go through the same view, and the frontend posts multipart either
        way, so the split has to key on the attachment actually being there.
        """
        monkeypatch.setattr(
            ScopedRateThrottle,
            "THROTTLE_RATES",
            {"inquiry-create": "10/hour", "inquiry-create-upload": "1/hour"},
        )
        cache.clear()

        def post_with_file():
            return anonymous_client.post(
                create_url,
                {
                    "client": "Acme",
                    "attachment": SimpleUploadedFile("doc.pdf", b"payload"),
                    "sales_manager_id": sales_manager.id,
                },
                format="multipart",
            )

        def post_without_file():
            return anonymous_client.post(
                create_url,
                {
                    "client": "Acme",
                    "text": "quote",
                    "sales_manager_id": sales_manager.id,
                },
                format="multipart",
            )

        assert post_with_file().status_code == status.HTTP_201_CREATED
        assert post_with_file().status_code == status.HTTP_429_TOO_MANY_REQUESTS
        # The text quota is untouched by the upload ceiling.
        assert post_without_file().status_code == status.HTTP_201_CREATED

    def test_throttle_key_cannot_be_forged_via_x_forwarded_for(
        self, anonymous_client, sales_manager, create_url, monkeypatch
    ):
        """NUM_PROXIES=1 makes DRF read the address the ingress appended.

        Without it DRF keys on the whole X-Forwarded-For header, so a caller
        could vary the part it writes and get a fresh quota every request.
        """
        monkeypatch.setattr(
            ScopedRateThrottle, "THROTTLE_RATES", {"inquiry-create": "1/hour"}
        )
        cache.clear()

        def post(spoofed):
            return anonymous_client.post(
                create_url,
                {
                    "client": "Acme",
                    "text": "please quote",
                    "sales_manager_id": sales_manager.id,
                },
                format="json",
                HTTP_X_FORWARDED_FOR=f"{spoofed}, 10.0.0.1",
            )

        assert post("1.1.1.1").status_code == status.HTTP_201_CREATED
        assert post("2.2.2.2").status_code == status.HTTP_429_TOO_MANY_REQUESTS


@pytest.mark.django_db
class TestRejectedReplacementKeepsTheOldFile:
    def test_failed_update_does_not_destroy_the_stored_attachment(self, sales_manager):
        """A rejected replacement must leave the existing file intact.

        update_inquiry() used to delete the old file before full_clean() ran, so
        a refused update answered 400 while the row pointed at a file that no
        longer existed. Reachable through the size limit too, not just the new
        extension check.
        """
        inquiry = InquiryServices.create_inquiry(
            client="Acme",
            attachment=SimpleUploadedFile("original.pdf", b"the real document"),
            sales_manager_id=sales_manager.id,
        )
        stored_name = inquiry.attachment.name
        assert inquiry.attachment.storage.exists(stored_name)

        with pytest.raises(ValidationError):
            InquiryServices.update_inquiry(
                inquiry=inquiry,
                attachment=SimpleUploadedFile("replacement.svg", b"<svg/>"),
            )

        fresh = Inquiry.objects.get(pk=inquiry.pk)
        assert fresh.attachment.name == stored_name
        assert fresh.attachment.storage.exists(stored_name), (
            "the original file was deleted even though the replacement was refused"
        )
