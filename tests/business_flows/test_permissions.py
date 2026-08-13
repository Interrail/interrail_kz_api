"""
Business permission and authorization tests.
Focus on user type boundaries and access control.
"""

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CustomUser


@pytest.mark.django_db
class TestUserTypePermissions:
    """Test permission boundaries between user types."""

    @pytest.fixture
    def api_client(self):
        return APIClient()

    @pytest.fixture
    def customer_user(self):
        return CustomUser.objects.create_user(
            username="customer",
            email="customer@example.com",
            password="testpass123",
            user_type="customer",
        )

    @pytest.fixture
    def manager_user(self):
        return CustomUser.objects.create_user(
            username="manager",
            email="manager@example.com",
            password="testpass123",
            user_type="manager",
        )

    @pytest.fixture
    def admin_user(self):
        return CustomUser.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="testpass123",
            user_type="admin",
        )

    def test_inquiry_access_permissions(
        self, api_client, customer_user, manager_user, admin_user
    ):
        """Test who can access inquiry endpoints."""
        inquiry_urls = [
            reverse("inquiries:inquiry-list"),
            reverse("inquiries:inquiry-stats"),
        ]

        # Customer should be forbidden
        refresh = RefreshToken.for_user(customer_user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        for url in inquiry_urls:
            response = api_client.get(url)
            assert response.status_code == status.HTTP_403_FORBIDDEN, (
                f"Customer should not access {url}"
            )

        # Manager should have access
        refresh = RefreshToken.for_user(manager_user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        for url in inquiry_urls:
            response = api_client.get(url)
            assert response.status_code == status.HTTP_200_OK, (
                f"Manager should access {url}"
            )

        # Admin should have access
        refresh = RefreshToken.for_user(admin_user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        for url in inquiry_urls:
            response = api_client.get(url)
            assert response.status_code == status.HTTP_200_OK, (
                f"Admin should access {url}"
            )

    # def test_inquiry_creation_permissions(
    #     self, api_client, customer_user, manager_user
    # ):
    #     """Test who can create inquiries."""
    #     create_url = reverse("inquiries:inquiry-create")
    #     create_data = {
    #         "client": "Test Client",
    #         "text": "Test inquiry",
    #         "sales_manager_id": manager_user.id,
    #         "status": "pending",
    #     }
    #
    #     # Customer cannot create inquiries
    #     refresh = RefreshToken.for_user(customer_user)
    #     api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    #
    #     response = api_client.post(create_url, create_data, format="json")
    #     assert response.status_code == status.HTTP_403_FORBIDDEN

    # Manager can create inquiries
    # refresh = RefreshToken.for_user(manager_user)
    # api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
    #
    # response = api_client.post(create_url, create_data, format="json")
    # assert response.status_code == status.HTTP_201_CREATED

    def test_inquiry_deletion_permissions(self, api_client, manager_user, admin_user):
        """Test who can delete inquiries."""
        from apps.inquiries.models import Inquiry

        inquiry = Inquiry.objects.create(
            client="Test Client",
            text="Test inquiry",
            status="pending",
            sales_manager=manager_user,
        )

        delete_url = reverse(
            "inquiries:inquiry-delete", kwargs={"inquiry_id": inquiry.id}
        )

        # Manager cannot delete inquiries
        refresh = RefreshToken.for_user(manager_user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        response = api_client.delete(delete_url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

        # Admin can delete inquiries
        refresh = RefreshToken.for_user(admin_user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        response = api_client.delete(delete_url)
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
class TestAuthenticationRequirements:
    """Test authentication requirements for protected endpoints."""

    @pytest.fixture
    def api_client(self):
        return APIClient()

    # def test_unauthenticated_access_forbidden(self, api_client):
    #     """Test that protected endpoints require authentication."""
    #     protected_urls = [
    #         reverse("authentication:profile"),
    #         reverse("authentication:change-password"),
    #         reverse("inquiries:inquiry-list"),
    #         reverse("inquiries:inquiry-create"),
    #         reverse("inquiries:inquiry-stats"),
    #     ]
    #
    #     for url in protected_urls:
    #         response = api_client.get(url)
    #         assert response.status_code in [
    #             status.HTTP_401_UNAUTHORIZED,
    #             status.HTTP_403_FORBIDDEN,
    #         ], f"Unauthenticated access should be forbidden for {url}"

    def test_invalid_token_rejected(self, api_client):
        """Test that invalid tokens are rejected."""
        api_client.credentials(HTTP_AUTHORIZATION="Bearer invalid_token")

        protected_url = reverse("authentication:profile")
        response = api_client.get(protected_url)
        assert response.status_code in [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        ]


@pytest.mark.django_db
class TestBusinessRuleEnforcement:
    """Test business rule enforcement in permissions."""

    @pytest.fixture
    def api_client(self):
        return APIClient()

    @pytest.fixture
    def manager_user(self):
        return CustomUser.objects.create_user(
            username="manager",
            email="manager@example.com",
            password="testpass123",
            user_type="manager",
        )

    @pytest.fixture
    def customer_user(self):
        return CustomUser.objects.create_user(
            username="customer",
            email="customer@example.com",
            password="testpass123",
            user_type="customer",
        )

    def test_customer_cannot_be_sales_manager(
        self, api_client, manager_user, customer_user
    ):
        """Test that customers cannot be assigned as sales managers."""
        refresh = RefreshToken.for_user(manager_user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        create_url = reverse("inquiries:inquiry-create")
        create_data = {
            "client": "Test Client",
            "text": "Test inquiry",
            "sales_manager_id": customer_user.id,  # Customer as sales manager
        }

        response = api_client.post(create_url, create_data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_manager_permissions_in_profile(
        self, api_client, manager_user, customer_user
    ):
        """Test that user profiles reflect correct permissions."""
        profile_url = reverse("authentication:profile")

        # Manager profile should show manager permissions
        refresh = RefreshToken.for_user(manager_user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        response = api_client.get(profile_url)
        assert response.status_code == status.HTTP_200_OK
        permissions = response.data["data"]["permissions"]
        assert permissions["can_manage_routes"] is True  # Manager can manage routes

        # Customer profile should show limited permissions
        refresh = RefreshToken.for_user(customer_user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        response = api_client.get(profile_url)
        assert response.status_code == status.HTTP_200_OK
        permissions = response.data["data"]["permissions"]
        assert (
            permissions["can_manage_routes"] is False
        )  # Customer cannot manage routes
