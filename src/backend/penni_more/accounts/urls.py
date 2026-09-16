"""HTML routes for account management."""

from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("", views.account_list, name="list"),
    path("new/", views.account_create, name="create"),
    path("<int:pk>/", views.account_detail, name="detail"),
    path("<int:pk>/edit/", views.account_update, name="update"),
    path("<int:pk>/delete/", views.account_delete, name="delete"),
    path("<int:pk>/share/", views.account_share, name="share"),
    path(
        "<int:pk>/shares/<int:share_id>/revoke/",
        views.account_share_revoke,
        name="revoke",
    ),
]
