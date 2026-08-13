"""JWT Authentication Manager for Munich Exhibition API"""

import logging
from datetime import datetime, timedelta

import requests
from django.conf import settings
from django.core.cache import cache

from .exceptions import MunichAPIConnectionError, MunichAuthenticationError

logger = logging.getLogger(__name__)


class MunichAuthManager:
    """Manages JWT authentication with Munich Exhibition API"""

    # Cache keys (not actual passwords, just cache key names)
    ACCESS_TOKEN_KEY = "munich_api_access_token"  # nosec B105
    REFRESH_TOKEN_KEY = "munich_api_refresh_token"  # nosec B105
    TOKEN_EXPIRY_KEY = "munich_api_token_expiry"  # nosec B105

    def __init__(self):
        self.base_url = settings.MUNICH_API_BASE_URL.rstrip("/")
        self.email = settings.MUNICH_API_USERNAME  # Munich API uses email for login
        self.password = settings.MUNICH_API_PASSWORD
        self.timeout = settings.MUNICH_API_TIMEOUT

    def get_access_token(self):
        """Get valid access token, refresh if needed"""
        access_token = cache.get(self.ACCESS_TOKEN_KEY)

        if access_token and not self._is_token_expired():
            return access_token

        # Try to refresh token first
        refresh_token = cache.get(self.REFRESH_TOKEN_KEY)
        if refresh_token:
            try:
                return self._refresh_access_token(refresh_token)
            except MunichAuthenticationError:
                logger.warning("Token refresh failed, re-authenticating")

        # If refresh fails or no refresh token, authenticate
        return self._authenticate()

    def _authenticate(self):
        """Authenticate and get new tokens"""
        url = f"{self.base_url}/api/accounts/generate-token/"

        try:
            response = requests.post(
                url,
                json={"email": self.email, "password": self.password},
                timeout=self.timeout,
            )

            if response.status_code == 200:
                data = response.json()
                self._store_tokens(
                    access_token=data["access"], refresh_token=data["refresh"]
                )
                logger.info("Successfully authenticated with Munich API")
                return data["access"]
            else:
                raise MunichAuthenticationError(
                    f"Authentication failed: {response.status_code} - {response.text}"
                )

        except requests.exceptions.RequestException as e:
            raise MunichAPIConnectionError(
                f"Connection error during authentication: {str(e)}"
            )

    def _refresh_access_token(self, refresh_token):
        """Refresh access token using refresh token"""
        url = f"{self.base_url}/api/accounts/refresh-token/"

        try:
            response = requests.post(
                url, json={"refresh": refresh_token}, timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                access_token = data["access"]

                # Store new access token
                cache.set(self.ACCESS_TOKEN_KEY, access_token, timeout=3600)  # 1 hour
                self._update_token_expiry()

                logger.info("Successfully refreshed Munich API token")
                return access_token
            else:
                raise MunichAuthenticationError(
                    f"Token refresh failed: {response.status_code}"
                )

        except requests.exceptions.RequestException as e:
            raise MunichAPIConnectionError(
                f"Connection error during token refresh: {str(e)}"
            )

    def _store_tokens(self, access_token, refresh_token):
        """Store tokens in cache"""
        # Access token expires in 1 hour (adjust based on Munich API settings)
        cache.set(self.ACCESS_TOKEN_KEY, access_token, timeout=3600)
        # Refresh token expires in 7 days (adjust based on Munich API settings)
        cache.set(self.REFRESH_TOKEN_KEY, refresh_token, timeout=604800)
        self._update_token_expiry()

    def _update_token_expiry(self):
        """Update token expiry timestamp"""
        # Set expiry to 55 minutes from now (5 min buffer before actual expiry)
        expiry = datetime.now() + timedelta(minutes=55)
        cache.set(self.TOKEN_EXPIRY_KEY, expiry.isoformat(), timeout=3600)

    def _is_token_expired(self):
        """Check if token is expired"""
        expiry_str = cache.get(self.TOKEN_EXPIRY_KEY)
        if not expiry_str:
            return True

        expiry = datetime.fromisoformat(expiry_str)
        return datetime.now() >= expiry

    def clear_tokens(self):
        """Clear stored tokens (useful for testing)"""
        cache.delete(self.ACCESS_TOKEN_KEY)
        cache.delete(self.REFRESH_TOKEN_KEY)
        cache.delete(self.TOKEN_EXPIRY_KEY)
