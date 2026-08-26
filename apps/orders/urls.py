from django.urls import path

from .apis import (
    ClientSuggestionsApiView,
    OrderCreateApiView,
    OrderDeleteApiView,
    OrderDetailApiView,
    OrderListApiView,
    OrderUpdateApiView,
)

app_name = "orders"

urlpatterns = [
    path("", OrderListApiView.as_view(), name="order-list"),
    path("create/", OrderCreateApiView.as_view(), name="order-create"),
    path("clients/", ClientSuggestionsApiView.as_view(), name="client-suggestions"),
    path("<int:order_id>/", OrderDetailApiView.as_view(), name="order-detail"),
    path("<int:order_id>/update/", OrderUpdateApiView.as_view(), name="order-update"),
    path("<int:order_id>/delete/", OrderDeleteApiView.as_view(), name="order-delete"),
]
