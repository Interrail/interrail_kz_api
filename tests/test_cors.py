"""
CORS is a credential boundary here, not a convenience setting: the browser
attaches the auth cookie cross-site (SameSite=None), so whoever gets
Access-Control-Allow-Origin can read this API as the logged-in user.
"""

import pytest
from django.test import override_settings
from django.urls import reverse

ALLOWED = "https://systemkz.interrail.uz"
FOREIGN = "https://evil.example.com"


@pytest.fixture
def health_url():
    return reverse("core:health-check")


@pytest.mark.django_db
class TestCorsAllowlist:
    def test_allowed_origin_is_echoed_with_credentials(self, api_client, health_url):
        response = api_client.get(health_url, HTTP_ORIGIN=ALLOWED)

        assert response["Access-Control-Allow-Origin"] == ALLOWED
        assert response["Access-Control-Allow-Credentials"] == "true"

    def test_foreign_origin_gets_no_cors_headers(self, api_client, health_url):
        response = api_client.get(health_url, HTTP_ORIGIN=FOREIGN)

        assert "Access-Control-Allow-Origin" not in response

    def test_foreign_preflight_is_not_granted(self, api_client, health_url):
        response = api_client.options(
            health_url,
            HTTP_ORIGIN=FOREIGN,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        )

        assert "Access-Control-Allow-Origin" not in response

    @override_settings(CORS_ALLOW_ALL_ORIGINS=True)
    def test_allow_all_origins_would_reopen_the_hole(self, api_client, health_url):
        """Guards the reason the allowlist exists.

        With CORS_ALLOW_ALL_ORIGINS on, django-cors-headers never consults the
        allowlist, and because credentials are enabled it echoes the caller's
        Origin instead of '*'. This test documents that behaviour so switching
        the flag back on cannot look harmless.
        """
        response = api_client.get(health_url, HTTP_ORIGIN=FOREIGN)

        assert response["Access-Control-Allow-Origin"] == FOREIGN
        assert response["Access-Control-Allow-Credentials"] == "true"
