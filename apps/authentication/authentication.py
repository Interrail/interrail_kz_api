from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

User = get_user_model()


class CookieJWTAuthentication(BaseAuthentication):
    """
    Custom JWT authentication that reads tokens from cookies first,
    then falls back to the Authorization header.
    """

    def authenticate(self, request):
        """
        Authenticate the request and return a two-tuple of (user, token).
        """
        # Try to get token from cookies first
        raw_token = request.COOKIES.get("access_token")

        if not raw_token:
            # Try Authorization header as fallback
            auth_header = request.META.get("HTTP_AUTHORIZATION")
            if auth_header and auth_header.startswith("Bearer "):
                raw_token = auth_header.split(" ")[1]

        if not raw_token:
            return None  # No token found

        try:
            # AccessToken, not UntypedToken: UntypedToken skips the token_type
            # check, so a refresh token authenticated as an access token — and
            # since it also skips the blacklist, logout did not revoke it.
            validated_token = AccessToken(raw_token)
            user = self.get_user(validated_token)

            return (user, validated_token)

        except TokenError as e:
            raise AuthenticationFailed(f"Invalid token: {str(e)}")

    def get_user(self, validated_token):
        """
        Get the user from the validated token.
        """
        try:
            user_id = validated_token["user_id"]
            user = User.objects.get(id=user_id)

            if not user.is_active:
                raise AuthenticationFailed("User account is disabled")

            return user

        except KeyError:
            raise AuthenticationFailed(
                "Token contained no recognizable user identification"
            )
        except User.DoesNotExist:
            raise AuthenticationFailed("User not found")
