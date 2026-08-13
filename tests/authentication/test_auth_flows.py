"""
Authentication business logic tests.
Focus on JWT flows, user types, and security requirements.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


@pytest.mark.django_db
class TestAuthenticationFlows:
    """Test core authentication business flows."""

    @pytest.fixture
    def login_url(self):
        return reverse("authentication:login")

    @pytest.fixture
    def register_url(self):
        return reverse("authentication:register")

    @pytest.fixture
    def test_user(self):
        return User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpassword123",
            user_type="customer",
            telegram_id="123456789",
        )

    def test_successful_login_flow(self, api_client, login_url, test_user):
        """Test complete successful login with JWT tokens."""
        data = {"username": "testuser", "password": "testpassword123"}

        response = api_client.post(login_url, data)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["success"] is True
        assert "access_token" in response.cookies
        assert "refresh_token" in response.cookies

    def test_login_with_invalid_credentials(self, api_client, login_url):
        """Test login failure with wrong credentials."""
        data = {"username": "nonexistent", "password": "wrongpassword"}

        response = api_client.post(login_url, data)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["success"] is False
        assert "access_token" not in response.cookies

    def test_login_with_inactive_user(self, api_client, login_url):
        """Test login failure with inactive user account."""
        User.objects.create_user(
            username="inactive",
            email="inactive@example.com",
            password="testpassword123",
            is_active=False,
        )

        data = {"username": "inactive", "password": "testpassword123"}
        response = api_client.post(login_url, data)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["success"] is False

    def test_successful_registration_flow(self, api_client, register_url):
        """Test complete user registration with JWT generation."""
        data = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password": "newpassword123",
            "user_type": "customer",
            "telegram_id": "987654321",
        }

        response = api_client.post(register_url, data)

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["success"] is True

        # Verify user was created with correct attributes
        user_data = response.data["data"]["user"]
        assert user_data["username"] == "newuser"
        assert user_data["user_type"] == "customer"

        # Verify JWT tokens contain custom claims
        from rest_framework_simplejwt.tokens import AccessToken

        access_token = AccessToken(response.data["data"]["access_token"])
        assert access_token["user_type"] == "customer"
        assert access_token["telegram_id"] == "987654321"

    def test_registration_with_duplicate_username(
        self, api_client, register_url, test_user
    ):
        """Test registration failure with existing username."""
        data = {
            "username": "testuser",  # Already exists
            "email": "different@example.com",
            "password": "newpassword123",
        }

        response = api_client.post(register_url, data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["success"] is False

    def test_registration_defaults_to_customer_type(self, api_client, register_url):
        """Test registration defaults to customer user type."""
        data = {
            "username": "defaultuser",
            "email": "default@example.com",
            "password": "testpassword123",
        }

        response = api_client.post(register_url, data)

        assert response.status_code == status.HTTP_201_CREATED
        user_info = response.data["data"]["user"]
        assert user_info["user_type"] == "customer"


@pytest.mark.django_db
class TestTokenManagement:
    """Test JWT token lifecycle and management."""

    @pytest.fixture
    def verify_url(self):
        return reverse("authentication:verify-token")

    @pytest.fixture
    def refresh_url(self):
        return reverse("authentication:refresh")

    @pytest.fixture
    def logout_url(self):
        return reverse("authentication:logout")

    @pytest.fixture
    def test_user_with_token(self):
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpassword123",
            user_type="customer",
            telegram_id="123456789",
        )
        refresh = RefreshToken.for_user(user)
        access_token = refresh.access_token
        access_token["user_type"] = user.user_type
        access_token["telegram_id"] = user.telegram_id

        return user, str(access_token)

    def test_token_verification_success(
        self, api_client, verify_url, test_user_with_token
    ):
        """Test successful JWT token verification."""
        user, access_token = test_user_with_token
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")

        response = api_client.post(verify_url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["user"]["username"] == user.username
        assert response.data["user"]["user_type"] == user.user_type

    def test_refresh_token_flow(self, api_client, refresh_url):
        """Test JWT refresh token workflow."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpassword123",
            user_type="customer",
        )
        refresh_token = RefreshToken.for_user(user)
        api_client.cookies["refresh_token"] = str(refresh_token)

        response = api_client.post(refresh_url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["success"] is True
        assert "access_token" in response.cookies
        assert "refresh_token" in response.cookies

    def test_refresh_token_missing_cookie(self, api_client, refresh_url):
        """Test refresh token failure when cookie is missing."""
        response = api_client.post(refresh_url)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["success"] is False

    def test_logout_clears_tokens(self, api_client, logout_url):
        """Test logout clears authentication tokens."""
        user = User.objects.create_user(
            username="testuser", email="test@example.com", password="testpassword123"
        )
        refresh_token = RefreshToken.for_user(user)
        api_client.cookies["refresh_token"] = str(refresh_token)

        response = api_client.post(logout_url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["success"] is True


@pytest.mark.django_db
class TestUserProfile:
    """Test user profile and permissions business logic."""

    @pytest.fixture
    def profile_url(self):
        return reverse("authentication:profile")

    @pytest.fixture
    def change_password_url(self):
        return reverse("authentication:change-password")

    def test_profile_returns_user_data_and_permissions(self, api_client, profile_url):
        """Test profile endpoint returns user data with correct permissions."""
        user = User.objects.create_user(
            username="manager",
            email="manager@example.com",
            password="testpassword123",
            user_type="manager",
            first_name="John",
            last_name="Doe",
        )

        refresh = RefreshToken.for_user(user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        response = api_client.get(profile_url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["success"] is True

        # Check profile data
        profile = response.data["data"]["profile"]
        assert profile["username"] == user.username
        assert profile["user_type"] == "manager"

        # Check permissions based on user type
        permissions = response.data["data"]["permissions"]
        assert isinstance(permissions, dict)
        assert "can_manage_routes" in permissions

    def test_password_change_flow(self, api_client, change_password_url):
        """Test successful password change workflow."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="oldpassword123",
        )

        refresh = RefreshToken.for_user(user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        data = {"old_password": "oldpassword123", "new_password": "newpassword456"}

        response = api_client.post(change_password_url, data)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["success"] is True

        # Verify password was actually changed
        user.refresh_from_db()
        assert user.check_password("newpassword456")
        assert not user.check_password("oldpassword123")

    def test_password_change_with_wrong_old_password(
        self, api_client, change_password_url
    ):
        """Test password change failure with incorrect old password."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="oldpassword123",
        )

        refresh = RefreshToken.for_user(user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        data = {"old_password": "wrongpassword", "new_password": "newpassword456"}

        response = api_client.post(change_password_url, data)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["success"] is False

        # Verify password was not changed
        user.refresh_from_db()
        assert user.check_password("oldpassword123")


@pytest.mark.django_db
class TestUserTypeValidation:
    """Test user type validation in authentication flows."""

    @pytest.fixture
    def register_url(self):
        return reverse("authentication:register")

    def test_valid_user_types_accepted(self, api_client, register_url):
        """Test that valid user types are accepted during registration."""
        valid_types = ["customer", "manager", "admin"]

        for user_type in valid_types:
            data = {
                "username": f"{user_type}_user",
                "email": f"{user_type}@example.com",
                "password": "testpassword123",
                "user_type": user_type,
            }

            response = api_client.post(register_url, data)
            assert response.status_code == status.HTTP_201_CREATED
            assert response.data["data"]["user"]["user_type"] == user_type

    def test_invalid_user_type_rejected(self, api_client, register_url):
        """Test that invalid user types are rejected."""
        data = {
            "username": "invaliduser",
            "email": "invalid@example.com",
            "password": "testpassword123",
            "user_type": "invalid_type",
        }

        response = api_client.post(register_url, data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestTokenTypeEnforcement:
    """A refresh token must not be usable as an API credential.

    The rejected responses are 403, not 401: CookieJWTAuthentication extends
    BaseAuthentication without an authenticate_header(), and DRF downgrades to
    403 when no authenticator offers a WWW-Authenticate challenge. That is
    pre-existing API behaviour, asserted here as-is rather than changed.
    """

    @pytest.fixture
    def profile_url(self):
        return reverse("authentication:profile")

    @pytest.fixture
    def test_user(self):
        return User.objects.create_user(
            username="tokentypeuser",
            email="tokentype@example.com",
            password="testpassword123",
            user_type="manager",
        )

    def test_access_token_authenticates(self, api_client, profile_url, test_user):
        """Baseline: the access token is accepted, both as cookie and as Bearer."""
        access = str(RefreshToken.for_user(test_user).access_token)

        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        assert api_client.get(profile_url).status_code == status.HTTP_200_OK

        api_client.credentials()
        api_client.cookies["access_token"] = access
        assert api_client.get(profile_url).status_code == status.HTTP_200_OK

    def test_refresh_token_is_rejected_as_bearer(
        self, api_client, profile_url, test_user
    ):
        """A refresh token carries a different token_type and must not authenticate."""
        refresh = str(RefreshToken.for_user(test_user))

        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh}")
        response = api_client.get(profile_url)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_refresh_token_is_rejected_in_cookie(
        self, api_client, profile_url, test_user
    ):
        """Same via the cookie the browser actually sends."""
        refresh = str(RefreshToken.for_user(test_user))

        api_client.cookies["access_token"] = refresh
        response = api_client.get(profile_url)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_blacklisted_refresh_token_cannot_mint_a_new_access_token(
        self, api_client, test_user
    ):
        """Logout must actually revoke: the blacklisted token buys nothing at /refresh/.

        Asserting it against a protected endpoint would prove nothing — AccessToken
        turns away every refresh token on token_type alone, blacklisted or not. The
        refresh endpoint is where the blacklist is the only thing standing in the way.
        """
        refresh = RefreshToken.for_user(test_user)
        refresh.blacklist()

        api_client.cookies["refresh_token"] = str(refresh)
        response = api_client.post(reverse("authentication:refresh"))

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
