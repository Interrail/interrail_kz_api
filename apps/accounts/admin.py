from django.contrib import admin
from django.utils.html import format_html

from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "username",
        "email",
        "colored_user_type",
        "is_active",
        "is_staff",
        "telegram_access",
        "date_joined",
        "updated_at",
    ]
    list_filter = [
        "user_type",
        "is_active",
        "is_staff",
        "is_superuser",
        "telegram_access",
        "date_joined",
        "updated_at",
    ]
    search_fields = [
        "username",
        "email",
        "first_name",
        "last_name",
        "telegram_username",
    ]
    readonly_fields = ["date_joined", "last_login", "created_at", "updated_at"]
    list_per_page = 25
    ordering = ["-date_joined"]

    fieldsets = (
        ("Basic Information", {"fields": ("username", "email", "password")}),
        ("Personal Info", {"fields": ("first_name", "last_name")}),
        (
            "User Settings",
            {"fields": ("user_type", "is_active", "is_staff", "is_superuser")},
        ),
        (
            "Telegram Integration",
            {
                "fields": (
                    "telegram_id",
                    "telegram_username",
                    "telegram_access",
                    "phone",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Important Dates",
            {
                "fields": ("date_joined", "last_login", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def colored_user_type(self, obj):
        colors = {"customer": "blue", "manager": "orange", "admin": "red"}
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.user_type, "black"),
            obj.get_user_type_display(),
        )

    colored_user_type.short_description = "User Type"
