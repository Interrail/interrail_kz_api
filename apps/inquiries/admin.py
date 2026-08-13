from django.contrib import admin
from django.utils.html import format_html

from .models import Inquiry, KPIWeights, PerformanceTarget


@admin.register(Inquiry)
class InquiryAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "client",
        "colored_status",
        "attachment_display",
        "sales_manager",
        "is_new_customer",
        "created_at",
        "updated_at",
    ]
    list_filter = [
        "status",
        "is_new_customer",
        "created_at",
        "updated_at",
        "sales_manager__user_type",
    ]
    search_fields = [
        "client",
        "text",
        "comment",
        "sales_manager__username",
        "sales_manager__email",
    ]
    readonly_fields = ["created_at", "updated_at"]
    list_per_page = 25
    ordering = ["-created_at"]

    fieldsets = (
        ("Basic Information", {"fields": ("client", "text", "attachment", "comment")}),
        (
            "Status & Assignment",
            {"fields": ("status", "sales_manager", "is_new_customer")},
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    def colored_status(self, obj):
        colors = {
            "pending": "orange",
            "quoted": "blue",
            "success": "green",
            "failed": "red",
        }
        return format_html(
            '<span style="color: {};">{}</span>',
            colors.get(obj.status, "black"),
            obj.get_status_display(),
        )

    colored_status.short_description = "Status"

    def attachment_display(self, obj):
        if obj.attachment:
            return format_html(
                '<a href="{}" target="_blank">📎 View</a>', obj.attachment.url
            )
        return "-"

    attachment_display.short_description = "Attachment"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("sales_manager")


@admin.register(KPIWeights)
class KPIWeightsAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "response_time_weight",
        "follow_up_weight",
        "conversion_rate_weight",
        "new_customer_weight",
        "total_weight_display",
        "created_at",
        "created_by",
    ]
    list_filter = ["created_at", "created_by"]
    search_fields = ["created_by__username"]
    readonly_fields = ["created_at", "updated_at", "total_weight_display"]
    list_per_page = 20
    ordering = ["-created_at"]

    fieldsets = (
        (
            "KPI Weights Configuration",
            {
                "fields": (
                    "response_time_weight",
                    "follow_up_weight",
                    "conversion_rate_weight",
                    "new_customer_weight",
                    "total_weight_display",
                )
            },
        ),
        (
            "Metadata",
            {
                "fields": ("created_by", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def total_weight_display(self, obj):
        total = obj.total_weight
        color = "green" if abs(total - 100) < 0.01 else "red"
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}%</span>',
            color,
            f"{total:.2f}",
        )

    total_weight_display.short_description = "Total Weight"

    def save_model(self, request, obj, form, change):
        # Set created_by to current user if not already set
        if not change and not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("created_by")

    class Media:
        css = {"all": ("admin/css/custom_admin.css",)}
        js = ("admin/js/kpi_weights_validation.js",)


admin.site.register(PerformanceTarget)
