"""URL routes for the application, authentication, admin, and health probes."""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from . import views
from .users.forms import EmailAuthenticationForm

urlpatterns = [
    path("", views.home, name="home"),
    path("accounts/", include("penni_more.accounts.urls")),
    path(
        "login/",
        auth_views.LoginView.as_view(authentication_form=EmailAuthenticationForm),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
    path("health/live", views.live, name="health-live"),
    path("health/ready", views.ready, name="health-ready"),
]
