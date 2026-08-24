"""URL routes for the minimal application shell and health probes."""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("health/live", views.live, name="health-live"),
    path("health/ready", views.ready, name="health-ready"),
]
