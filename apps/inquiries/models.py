from datetime import timedelta

from ckeditor.fields import RichTextField
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from apps.accounts.models import CustomUser
from apps.core.models import TimeStampModel


# File size validation
def validate_file_size(value):
    """Validate file size limit (10MB)"""
    max_size = 10 * 1024 * 1024  # 10MB
    if value.size > max_size:
        raise ValidationError(
            f"File too large. Maximum size is {max_size / (1024 * 1024):.0f}MB"
        )


class Inquiry(TimeStampModel):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("quoted", "Quoted"),
        ("success", "Success"),
        ("failed", "Failed"),
    )

    GRADE_CHOICES = (
        ("A", "Excellent"),
        ("B", "Good"),
        ("C", "Average"),
    )

    client = models.CharField(max_length=255, blank=True, default="")
    text = RichTextField(blank=True, null=True)
    attachment = models.FileField(
        upload_to="inquiry_attachments/%Y/%m/%d/",
        null=True,
        blank=True,
        validators=[validate_file_size],
    )
    comment = RichTextField(blank=True, default="")
    sales_manager = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        related_name="sales_inquiries",
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_CHOICES[0][0]
    )
    is_new_customer = models.BooleanField(default=False)

    # KPI Tracking Fields
    quoted_at = models.DateTimeField(
        null=True, blank=True, help_text="When inquiry was quoted"
    )
    success_at = models.DateTimeField(
        null=True, blank=True, help_text="When inquiry was successful"
    )
    failed_at = models.DateTimeField(
        null=True, blank=True, help_text="When inquiry failed"
    )

    # KPI Durations (calculated automatically)
    quote_time = models.DurationField(
        default=timedelta(), help_text="Business hours from creation to quote"
    )
    resolution_time = models.DurationField(
        default=timedelta(), help_text="Business hours from quote to resolution"
    )

    # KPI Grades (calculated automatically)
    quote_grade = models.CharField(
        max_length=1,
        choices=GRADE_CHOICES,
        null=True,
        blank=True,
        help_text="Response time grade: A (≤60hrs), B (≤84hrs), C (>84hrs)",
    )
    completion_grade = models.CharField(
        max_length=1,
        choices=GRADE_CHOICES,
        null=True,
        blank=True,
        help_text="Completion time grade: A (≤120hrs), B (≤168hrs), C (>168hrs)",
    )

    # KPI Control Fields
    auto_completion = models.BooleanField(
        default=False, help_text="Skip automatic KPI calculation for this inquiry"
    )
    is_locked = models.BooleanField(
        default=False, help_text="Lock inquiry from KPI recalculation"
    )

    class Meta:
        verbose_name = "Inquiry"
        verbose_name_plural = "Inquiries"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["client"]),
            # KPI-related indexes
            models.Index(fields=["sales_manager", "-created_at"]),
            models.Index(fields=["quoted_at"]),
            models.Index(fields=["success_at"]),
            models.Index(fields=["failed_at"]),
            models.Index(fields=["is_new_customer"]),
            models.Index(fields=["quote_grade"]),
            models.Index(fields=["completion_grade"]),
        ]

    def clean(self):
        """Validate that at least text or attachment is provided."""
        super().clean()

        has_text = bool(self.text and self.text.strip())
        has_attachment = bool(self.attachment)

        if not has_text and not has_attachment:
            raise ValidationError("Must provide either text or attachment (or both).")

    def save(self, *args, **kwargs):
        """Override save to call clean validation."""
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        has_text = bool(self.text and self.text.strip())
        has_attachment = bool(self.attachment)

        if has_text and has_attachment:
            content_type = "text + file"
        elif has_attachment:
            content_type = "file"
        else:
            content_type = "text"

        return f"Inquiry from {self.client} - {self.status} ({content_type})"

    # KPI Business Logic Methods
    def quote(self, quoted_at: timezone.datetime = None) -> None:
        """Mark inquiry as quoted and calculate KPI metrics"""
        from .services import InquiryKPIServices

        InquiryKPIServices.quote_inquiry(inquiry=self, quoted_at=quoted_at)
        self.refresh_from_db()

    def mark_success(self, success_at: timezone.datetime = None) -> None:
        """Mark inquiry as successful and calculate KPI metrics"""
        from .services import InquiryKPIServices

        InquiryKPIServices.complete_inquiry_success(inquiry=self, success_at=success_at)
        self.refresh_from_db()

    def mark_failed(self, failed_at: timezone.datetime = None) -> None:
        """Mark inquiry as failed and calculate KPI metrics"""
        from .services import InquiryKPIServices

        InquiryKPIServices.complete_inquiry_failed(inquiry=self, failed_at=failed_at)
        self.refresh_from_db()

    def recalculate_kpi(self, force: bool = False) -> None:
        """Recalculate KPI metrics for this inquiry"""
        from .services import InquiryKPIServices

        InquiryKPIServices.recalculate_kpi_metrics(inquiry=self, force=force)
        self.refresh_from_db()

    def lock_kpi(self) -> None:
        """Lock inquiry from KPI recalculation"""
        from .services import InquiryKPIServices

        InquiryKPIServices.lock_inquiry_kpi(inquiry=self)
        self.refresh_from_db()

    def unlock_kpi(self) -> None:
        """Unlock inquiry to allow KPI recalculation"""
        from .services import InquiryKPIServices

        InquiryKPIServices.unlock_inquiry_kpi(inquiry=self)
        self.refresh_from_db()

    def set_auto_completion(self, enabled: bool = True) -> None:
        """Enable/disable auto-completion to skip KPI calculations"""
        from .services import InquiryKPIServices

        InquiryKPIServices.set_auto_completion(inquiry=self, auto_completion=enabled)
        self.refresh_from_db()

    @property
    def kpi_quote_points(self) -> int:
        """Get KPI points for quote grade"""
        from .utils import get_grade_points

        return get_grade_points(self.quote_grade)

    @property
    def kpi_completion_points(self) -> int:
        """Get KPI points for completion grade"""
        from .utils import get_grade_points

        return get_grade_points(self.completion_grade)

    @property
    def total_kpi_points(self) -> int:
        """Get total KPI points (quote + completion)"""
        return self.kpi_quote_points + self.kpi_completion_points

    @property
    def is_completed(self) -> bool:
        """Check if inquiry is in a completed state"""
        return self.status in ["success", "failed"]

    @property
    def is_processed(self) -> bool:
        """Check if inquiry has been processed (not pending)"""
        return self.status != "pending"

    @property
    def kpi_status_display(self) -> str:
        """Get human-readable KPI status"""
        if self.is_locked:
            return "🔒 Locked"
        elif self.auto_completion:
            return "⚡ Auto-completion"
        elif not self.is_processed:
            return "⏳ Pending"
        else:
            quote_display = f"Quote: {self.quote_grade or 'N/A'}"
            completion_display = f"Completion: {self.completion_grade or 'N/A'}"
            return f"{quote_display}, {completion_display}"


# KPI Signal Handlers for automatic calculation
@receiver(pre_save, sender=Inquiry)
def update_inquiry_kpi_on_status_change(sender, instance, **kwargs):
    """
    Signal handler to automatically update KPI metrics when inquiry status changes
    """
    # Skip if inquiry is locked or auto_completion is enabled
    if instance.is_locked or instance.auto_completion:
        return

    # Import here to avoid circular imports
    from .utils import (
        calculate_completion_grade,
        calculate_quote_grade,
        get_business_hours_between,
    )

    # Only process if this is an existing instance (has pk)
    if instance.pk is not None:
        try:
            old_instance = Inquiry.objects.get(pk=instance.pk)
        except Inquiry.DoesNotExist:
            # Instance doesn't exist yet, treat as new
            old_instance = None
    else:
        old_instance = None

    current_time = timezone.now()

    # Handle status change from pending to quoted
    if instance.status == "quoted" and (
        old_instance is None or old_instance.status != "quoted"
    ):
        # Set quoted timestamp if not already set
        if not instance.quoted_at:
            instance.quoted_at = current_time

        # Calculate quote time and grade
        if instance.created_at and instance.quoted_at:
            instance.quote_time = get_business_hours_between(
                instance.created_at, instance.quoted_at
            )
            instance.quote_grade = calculate_quote_grade(instance.quote_time)

    # Handle status change from quoted to success
    elif instance.status == "success" and (
        old_instance is None or old_instance.status != "success"
    ):
        # Set success timestamp if not already set
        if not instance.success_at:
            instance.success_at = current_time

        # Calculate resolution time and completion grade
        if instance.quoted_at and instance.success_at:
            instance.resolution_time = get_business_hours_between(
                instance.quoted_at, instance.success_at
            )
            instance.completion_grade = calculate_completion_grade(
                instance.resolution_time
            )

        # Clear failed_at if previously set
        instance.failed_at = None

    # Handle status change from quoted to failed
    elif instance.status == "failed" and (
        old_instance is None or old_instance.status != "failed"
    ):
        # Set failed timestamp if not already set
        if not instance.failed_at:
            instance.failed_at = current_time

        # Calculate resolution time and completion grade
        if instance.quoted_at and instance.failed_at:
            instance.resolution_time = get_business_hours_between(
                instance.quoted_at, instance.failed_at
            )
            instance.completion_grade = calculate_completion_grade(
                instance.resolution_time
            )

        # Clear success_at if previously set
        instance.success_at = None


@receiver(post_save, sender=Inquiry)
def finalize_inquiry_kpi_calculation(sender, instance, created, **kwargs):
    """
    Post-save signal to finalize KPI calculations and handle any cleanup
    """
    # Skip if inquiry is locked or auto_completion is enabled
    if instance.is_locked or instance.auto_completion:
        return

    # For new inquiries created directly with quoted/success/failed status
    # The pre_save signal handles most cases, this is for edge cases
    if created and instance.status != "pending":
        from .utils import (
            calculate_completion_grade,
            calculate_quote_grade,
            get_business_hours_between,
        )

        needs_update = False
        update_fields = []

        # Handle directly created quoted inquiry
        if (
            instance.status == "quoted"
            and not instance.quote_grade
            and instance.created_at
        ):
            if not instance.quoted_at:
                instance.quoted_at = instance.created_at
                update_fields.append("quoted_at")

            instance.quote_time = get_business_hours_between(
                instance.created_at, instance.quoted_at
            )
            instance.quote_grade = calculate_quote_grade(instance.quote_time)
            update_fields.extend(["quote_time", "quote_grade"])
            needs_update = True

        # Handle directly created completed inquiry
        elif instance.status in ["success", "failed"] and not instance.completion_grade:
            if instance.status == "success" and not instance.success_at:
                instance.success_at = instance.created_at
                update_fields.append("success_at")
            elif instance.status == "failed" and not instance.failed_at:
                instance.failed_at = instance.created_at
                update_fields.append("failed_at")

            # Ensure quote data exists
            if not instance.quoted_at:
                instance.quoted_at = instance.created_at
                update_fields.append("quoted_at")

            if not instance.quote_grade:
                instance.quote_time = timedelta()  # Same day quote
                instance.quote_grade = calculate_quote_grade(instance.quote_time)
                update_fields.extend(["quote_time", "quote_grade"])

            # Calculate completion metrics
            completion_timestamp = instance.success_at or instance.failed_at
            if completion_timestamp and instance.quoted_at:
                instance.resolution_time = get_business_hours_between(
                    instance.quoted_at, completion_timestamp
                )
                instance.completion_grade = calculate_completion_grade(
                    instance.resolution_time
                )
                update_fields.extend(["resolution_time", "completion_grade"])
                needs_update = True

        # Update if needed (avoid infinite recursion with update_fields)
        if needs_update and update_fields:
            Inquiry.objects.filter(pk=instance.pk).update(
                **{field: getattr(instance, field) for field in update_fields}
            )


class KPIWeights(TimeStampModel):
    """
    Model to store configurable KPI weights for performance calculations.
    Only one weights configuration exists and is always active.
    """

    # KPI Weight Fields (as percentages, should sum to 100)
    response_time_weight = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=25.00,
        help_text="Weight for response time KPI (quote efficiency). Value in percentage.",
    )
    follow_up_weight = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=25.00,
        help_text="Weight for follow-up KPI (completion efficiency). Value in percentage.",
    )
    conversion_rate_weight = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=25.00,
        help_text="Weight for conversion rate KPI (success rate). Value in percentage.",
    )
    new_customer_weight = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=25.00,
        help_text="Weight for new customer acquisition KPI. Value in percentage.",
    )

    # Metadata
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User who created this configuration",
    )

    class Meta:
        verbose_name = "KPI Weights Configuration"
        verbose_name_plural = "KPI Weights Configurations"
        ordering = ["-created_at"]

    def clean(self):
        """Validate that weights are positive and optionally sum to 100"""
        super().clean()

        weights = [
            self.response_time_weight,
            self.follow_up_weight,
            self.conversion_rate_weight,
            self.new_customer_weight,
        ]

        # Ensure all weights are positive
        if any(weight < 0 for weight in weights):
            raise ValidationError("All weights must be positive values.")

        # Optional: Validate that weights sum to 100%
        total_weight = sum(weights)
        if abs(total_weight - 100) > 0.01:  # Allow small floating point differences
            raise ValidationError(
                f"Weights must sum to 100%. Current total: {total_weight}%"
            )

    def save(self, *args, **kwargs):
        """Override save to ensure only one configuration exists"""
        self.clean()

        # Delete all existing configurations to maintain single instance
        if not self.pk:
            KPIWeights.objects.all().delete()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"KPI Weights ({self.created_at.strftime('%Y-%m-%d')})"

    @classmethod
    def get_current_weights(cls):
        """Get the current KPI weights configuration"""
        return cls.objects.first()

    @classmethod
    def get_default_weights(cls):
        """Get default weights if no active configuration exists"""
        return {
            "response_time_weight": 25.00,
            "follow_up_weight": 25.00,
            "conversion_rate_weight": 25.00,
            "new_customer_weight": 25.00,
        }

    @classmethod
    def get_current_weights_dict(cls):
        """Get current weights as dictionary, fallback to defaults"""
        current_weights = cls.get_current_weights()
        if current_weights:
            return {
                "response_time_weight": float(current_weights.response_time_weight),
                "follow_up_weight": float(current_weights.follow_up_weight),
                "conversion_rate_weight": float(current_weights.conversion_rate_weight),
                "new_customer_weight": float(current_weights.new_customer_weight),
            }
        return cls.get_default_weights()

    def get_weights_dict(self):
        """Get this instance's weights as dictionary"""
        return {
            "response_time_weight": float(self.response_time_weight),
            "follow_up_weight": float(self.follow_up_weight),
            "conversion_rate_weight": float(self.conversion_rate_weight),
            "new_customer_weight": float(self.new_customer_weight),
        }

    @property
    def total_weight(self):
        """Calculate total weight percentage"""
        return (
            self.response_time_weight
            + self.follow_up_weight
            + self.conversion_rate_weight
            + self.new_customer_weight
        )


class PerformanceTarget(TimeStampModel):
    """
    Volume-based performance targets for managers.
    Defines performance grade thresholds based on inquiry volume brackets.

    Example:
    - 0-30 inquiries need 90% overall performance for 'Excellent'
    - 31-60 inquiries need 85% overall performance for 'Excellent'
    - 101+ inquiries (no max) need 75% overall performance for 'Excellent'
    """

    GRADE_CHOICES = (
        ("excellent", "Excellent"),
        ("average", "Average"),
    )

    # Volume bracket definition
    min_inquiries = models.IntegerField(
        help_text="Minimum inquiries in this bracket (inclusive)"
    )
    max_inquiries = models.IntegerField(
        null=True,
        blank=True,
        help_text="Maximum inquiries in bracket (inclusive). Leave null for unlimited.",
    )

    # Performance threshold (as percentage)
    excellent_threshold = models.FloatField(
        help_text="Minimum overall performance percentage for Excellent grade. Below this is considered average performance."
    )

    is_active = models.BooleanField(
        default=True, help_text="Whether this target configuration is active"
    )

    class Meta:
        verbose_name = "Performance Target"
        verbose_name_plural = "Performance Targets"
        ordering = ["min_inquiries"]
        indexes = [
            models.Index(fields=["is_active"]),
            models.Index(fields=["min_inquiries"]),
        ]

    def clean(self):
        """Validate target configuration"""
        super().clean()

        # Validate percentage range
        if not (0 <= self.excellent_threshold <= 100):
            raise ValidationError("Excellent threshold must be between 0 and 100")

        # Validate volume bracket
        if self.max_inquiries is not None and self.max_inquiries < self.min_inquiries:
            raise ValidationError(
                "max_inquiries must be greater than or equal to min_inquiries"
            )

        # Validate minimum inquiries is not negative
        if self.min_inquiries < 0:
            raise ValidationError("min_inquiries cannot be negative")

        # Validate range overlaps with existing targets (excluding self)
        self._validate_range_overlaps()

    def _validate_range_overlaps(self):
        """Validate that this target's range doesn't overlap with existing active targets"""
        # Get all other active targets (excluding self if updating)
        other_targets = PerformanceTarget.objects.filter(is_active=True)
        if self.pk:
            other_targets = other_targets.exclude(pk=self.pk)

        current_min = self.min_inquiries
        current_max = self.max_inquiries

        for target in other_targets:
            other_min = target.min_inquiries
            other_max = target.max_inquiries

            # Check if ranges overlap
            if self._ranges_overlap(current_min, current_max, other_min, other_max):
                other_range = target.volume_display
                current_range = (
                    f"{current_min}-{current_max}" if current_max else f"{current_min}+"
                )
                raise ValidationError(
                    f"Volume range {current_range} overlaps with existing target range {other_range}. "
                    "Target ranges cannot overlap."
                )

    def _ranges_overlap(self, min1, max1, min2, max2):
        """
        Check if two ranges overlap

        Args:
            min1, max1: First range (max1 can be None for unlimited)
            min2, max2: Second range (max2 can be None for unlimited)

        Returns:
            bool: True if ranges overlap
        """
        # Handle unlimited ranges (max is None)
        if max1 is None and max2 is None:
            # Both unlimited - they overlap if either min falls within the other's range
            return True
        elif max1 is None:
            # First range is unlimited - overlaps if min1 <= max2
            return min1 <= max2 if max2 is not None else True
        elif max2 is None:
            # Second range is unlimited - overlaps if min2 <= max1
            return min2 <= max1
        else:
            # Both ranges are limited - standard overlap check
            return not (max1 < min2 or max2 < min1)

    def save(self, *args, **kwargs):
        """Override save to call clean validation"""
        self.clean()
        super().save(*args, **kwargs)

    def applies_to_volume(self, inquiry_count):
        """
        Check if this target configuration applies to given inquiry count

        Args:
            inquiry_count (int): Number of inquiries for the manager

        Returns:
            bool: True if this target applies to the given volume
        """
        if self.max_inquiries is None:
            # No upper limit - applies to all counts >= min_inquiries
            return inquiry_count >= self.min_inquiries
        else:
            # Has upper limit - check range
            return self.min_inquiries <= inquiry_count <= self.max_inquiries

    def get_grade_for_performance(self, performance_percentage):
        """
        Determine the grade for given performance percentage

        Args:
            performance_percentage (float): Overall performance percentage

        Returns:
            str: Grade ('excellent' or 'average')
        """
        if performance_percentage >= self.excellent_threshold:
            return "excellent"
        else:
            return "average"

    def __str__(self):
        if self.max_inquiries is None:
            volume_range = f"{self.min_inquiries}+ inquiries"
        else:
            volume_range = f"{self.min_inquiries}-{self.max_inquiries} inquiries"

        return f"Target: {volume_range} (Excellent: {self.excellent_threshold}%)"

    @property
    def volume_display(self):
        """Human-readable volume range"""
        if self.max_inquiries is None:
            return f"{self.min_inquiries}+"
        else:
            return f"{self.min_inquiries}-{self.max_inquiries}"

    @classmethod
    def get_target_for_volume(cls, inquiry_count):
        """
        Get the applicable target configuration for given inquiry volume

        Args:
            inquiry_count (int): Number of inquiries

        Returns:
            PerformanceTarget or None: Matching active target configuration
        """
        targets = cls.objects.filter(is_active=True).order_by("min_inquiries")

        for target in targets:
            if target.applies_to_volume(inquiry_count):
                return target

        return None

    @classmethod
    def create_default_targets(cls):
        """
        Create default target configurations
        Only creates if no targets exist

        Returns:
            list: Created target instances
        """
        if cls.objects.exists():
            return []

        default_configs = [
            {
                "min_inquiries": 0,
                "max_inquiries": 30,
                "excellent_threshold": 90.0,
            },
            {
                "min_inquiries": 31,
                "max_inquiries": 60,
                "excellent_threshold": 85.0,
            },
            {
                "min_inquiries": 61,
                "max_inquiries": 100,
                "excellent_threshold": 80.0,
            },
            {
                "min_inquiries": 101,
                "max_inquiries": None,  # Unlimited
                "excellent_threshold": 75.0,
            },
        ]

        created_targets = []
        for config in default_configs:
            target = cls.objects.create(**config)
            created_targets.append(target)

        return created_targets
