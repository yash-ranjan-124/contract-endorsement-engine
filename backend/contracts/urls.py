from django.urls import path

from contracts import views

urlpatterns = [
    path("contracts/", views.contract_list, name="contract-list"),
    path("contracts/<str:reference>/", views.contract_detail, name="contract-detail"),
    path(
        "contracts/<str:reference>/position/",
        views.contract_position,
        name="contract-position",
    ),
]
