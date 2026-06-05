from django.urls import path

from .apis import (
    DashboardKPIApiView,
    InquiryCreateApiView,
    InquiryDeleteApiView,
    InquiryDetailApiView,
    InquiryExportApiView,
    InquiryFailedApiView,
    InquiryKPILockApiView,
    InquiryListApiView,
    # KPI Actions
    InquiryQuoteApiView,
    InquiryStatsApiView,
    InquirySuccessApiView,
    InquiryUpdateApiView,
    # KPI Weights APIs
    KPIWeightsApiView,
    KPIWeightsUpdateApiView,
    # KPI APIs
    ManagerKPIApiView,
    # Performance Target APIs
    ManagerPerformanceGradeApiView,
    ManagerSelfKPIApiView,
    PerformanceTargetCreateApiView,
    PerformanceTargetDeleteApiView,
    PerformanceTargetListApiView,
    PerformanceTargetUpdateApiView,
)

app_name = "inquiries"

# Django Styleguide compliant URL patterns
# Following the pattern: 1 URL per API operation
inquiry_patterns = [
    # Inquiry list and create operations
    path("", InquiryListApiView.as_view(), name="inquiry-list"),
    path("create/", InquiryCreateApiView.as_view(), name="inquiry-create"),
    # Inquiry detail operations
    path("<int:inquiry_id>/", InquiryDetailApiView.as_view(), name="inquiry-detail"),
    path(
        "<int:inquiry_id>/update/",
        InquiryUpdateApiView.as_view(),
        name="inquiry-update",
    ),
    path(
        "<int:inquiry_id>/delete/",
        InquiryDeleteApiView.as_view(),
        name="inquiry-delete",
    ),
    # Inquiry utility operations
    path("stats/", InquiryStatsApiView.as_view(), name="inquiry-stats"),
    path("export/", InquiryExportApiView.as_view(), name="inquiry-export"),

    # KPI Statistics APIs
    path("kpi/manager/<int:manager_id>/", ManagerKPIApiView.as_view(), name="manager-kpi"),
    path("kpi/dashboard/", DashboardKPIApiView.as_view(), name="dashboard-kpi"),
    path("kpi/my-performance/", ManagerSelfKPIApiView.as_view(), name="my-kpi"),

    # KPI Action APIs
    path("<int:inquiry_id>/quote/", InquiryQuoteApiView.as_view(), name="inquiry-quote"),
    path("<int:inquiry_id>/success/", InquirySuccessApiView.as_view(), name="inquiry-success"),
    path("<int:inquiry_id>/failed/", InquiryFailedApiView.as_view(), name="inquiry-failed"),
    path("<int:inquiry_id>/kpi-lock/", InquiryKPILockApiView.as_view(), name="inquiry-kpi-lock"),

    # KPI Weights Management APIs
    path("kpi/weights/", KPIWeightsApiView.as_view(), name="kpi-weights"),
    path("kpi/weights/update/", KPIWeightsUpdateApiView.as_view(), name="kpi-weights-update"),

    # Performance Target Management APIs
    path("targets/", PerformanceTargetListApiView.as_view(), name="targets-list"),
    path("targets/create/", PerformanceTargetCreateApiView.as_view(), name="targets-create"),
    path("targets/bulk-update/", PerformanceTargetUpdateApiView.as_view(), name="targets-bulk-update"),
    path("targets/<int:target_id>/delete/", PerformanceTargetDeleteApiView.as_view(), name="targets-delete"),

    # Performance Grade API
    path("targets/my-grade/", ManagerPerformanceGradeApiView.as_view(), name="my-performance-grade"),
]

urlpatterns = inquiry_patterns
