"""URL routing for Exhibition Leads API"""

from django.urls import path

from .apis import (
    ExhibitionLeadDetailAPI,
    ExhibitionLeadListAPI,
    ExhibitionReferenceDataAPI,
)

urlpatterns = [
    # Lead CRUD endpoints
    path("", ExhibitionLeadListAPI.as_view(), name="exhibition-lead-list"),
    path(
        "<int:lead_id>/",
        ExhibitionLeadDetailAPI.as_view(),
        name="exhibition-lead-detail",
    ),
    # Reference data
    path(
        "reference-data/",
        ExhibitionReferenceDataAPI.as_view(),
        name="exhibition-reference-data",
    ),
]
