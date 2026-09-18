"""HTML routes for transaction management."""

from django.urls import path

from . import views

app_name = "transactions"

urlpatterns = [
    path("", views.transaction_list, name="list"),
    path("filters/", views.transaction_filters, name="filters"),
    path("filters/clear/", views.transaction_filters_clear, name="filters-clear"),
    path("new/", views.transaction_create, name="create"),
    path("import/", views.transaction_import, name="import"),
    path("import/confirm/", views.transaction_import_confirm, name="import-confirm"),
    path("<int:pk>/", views.transaction_detail, name="detail"),
    path("<int:pk>/edit/", views.transaction_update, name="update"),
    path("<int:pk>/delete/", views.transaction_delete, name="delete"),
]
