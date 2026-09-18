"""Django admin management for transaction categories."""

from django.contrib import admin

from .models import Category


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Manage the category catalog with ordinary Django permissions."""

    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    ordering = ("name",)
    search_fields = ("name",)
