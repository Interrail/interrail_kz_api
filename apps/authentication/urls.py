from django.urls import path

from .apis import (
    ChangePasswordApiView,
    LoginApiView,
    LogoutApiView,
    RefreshTokenApiView,
    RegisterApiView,
    TelegramAuthApiView,
    TelegramPhoneAuthApiView,
    UserProfileApiView,
    VerifyTokenApiView,
)

app_name = "authentication"

urlpatterns = [
    path("login/", LoginApiView.as_view(), name="login"),
    path("register/", RegisterApiView.as_view(), name="register"),
    path("refresh/", RefreshTokenApiView.as_view(), name="refresh"),
    path("logout/", LogoutApiView.as_view(), name="logout"),
    path("profile/", UserProfileApiView.as_view(), name="profile"),
    path("change-password/", ChangePasswordApiView.as_view(), name="change-password"),
    path("verify-token/", VerifyTokenApiView.as_view(), name="verify-token"),
    path("telegram/", TelegramAuthApiView.as_view(), name="telegram-auth"),
    path(
        "telegram/phone/",
        TelegramPhoneAuthApiView.as_view(),
        name="telegram-phone-auth",
    ),
]
