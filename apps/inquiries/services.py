from django.db import transaction
from django.utils import timezone

from apps.accounts.models import CustomUser

from .models import Inquiry, KPIWeights, PerformanceTarget
from .utils import (
    calculate_completion_grade,
    calculate_quote_grade,
    get_business_hours_between,
)


class InquiryServices:
    """
    Services for inquiry-related business logic
    """

    @staticmethod
    def create_inquiry(
        *,
        client: str,
        text: str = None,
        attachment=None,
        comment: str = "",
        sales_manager_id: int = None,
        is_new_customer: bool = False,
        status: str = "pending",
        **kwargs,
    ) -> Inquiry:
        """
        Create new inquiry with validation
        Requires at least text or attachment (or both)
        """
        # Validate that at least one content type is provided
        has_text = bool(text and text.strip())
        has_attachment = bool(attachment)

        if not has_text and not has_attachment:
            raise ValueError("Must provide either text or attachment (or both).")

        # Handle sales manager resolution
        sales_manager = None
        if sales_manager_id is not None:
            from .selectors import InquirySelectors

            try:
                sales_manager = InquirySelectors.get_sales_manager_by_id_or_telegram(
                    manager_id=sales_manager_id
                )
            except CustomUser.DoesNotExist:
                raise ValueError("Sales manager not found")

        # Business logic validation
        if sales_manager and sales_manager.user_type not in ["manager", "admin"]:
            raise ValueError("Sales manager must be a manager or admin user")

        with transaction.atomic():
            inquiry = Inquiry(
                client=client.strip(),
                text=text.strip() if text else None,
                attachment=attachment,
                comment=comment.strip(),
                sales_manager=sales_manager,
                is_new_customer=is_new_customer,
                status=status,
                **kwargs,
            )
            # Run validation before saving
            inquiry.full_clean()
            inquiry.save()

        return inquiry

    @staticmethod
    def update_inquiry(
        *,
        inquiry: Inquiry,
        client: str = None,
        text: str = None,
        attachment=...,  # Use Ellipsis to distinguish between None and not provided
        status: str = None,
        comment: str = None,
        sales_manager_id: int = None,
        is_new_customer: bool = None,
        **kwargs,
    ) -> Inquiry:
        """
        Update inquiry with validation
        Supports text, attachment, or both
        """
        update_fields = []
        sales_manager = None

        # Handle content updates (text and/or attachment)
        content_updated = False
        if text is not None:
            inquiry.text = text.strip() if text else None
            update_fields.append("text")
            content_updated = True

        # Held until the replacement is validated and saved. Deleting it here, as
        # this used to, destroys the stored file before full_clean() has a say —
        # a rejected replacement then leaves the row pointing at nothing.
        superseded_attachment = None

        if attachment is not ...:  # Only update if attachment was explicitly provided
            if inquiry.attachment:
                superseded_attachment = inquiry.attachment
            inquiry.attachment = attachment
            update_fields.append("attachment")
            content_updated = True

        # Validate that at least one content type remains after update
        if content_updated:
            has_text = bool(inquiry.text and inquiry.text.strip())
            has_attachment = bool(inquiry.attachment)

            if not has_text and not has_attachment:
                raise ValueError("Must provide either text or attachment (or both).")

        # Handle sales manager resolution
        if sales_manager_id is not None:
            from .selectors import InquirySelectors

            try:
                sales_manager = InquirySelectors.get_sales_manager_by_id_or_telegram(
                    manager_id=sales_manager_id
                )
            except CustomUser.DoesNotExist:
                raise ValueError("Sales manager not found")

        if client is not None:
            if not client.strip():
                raise ValueError("Client name cannot be empty")
            inquiry.client = client.strip()
            update_fields.append("client")

        if comment is not None:
            inquiry.comment = comment.strip()
            update_fields.append("comment")

        if sales_manager is not None:
            if sales_manager.user_type not in ["manager", "admin"]:
                raise ValueError("Sales manager must be a manager or admin user")
            inquiry.sales_manager = sales_manager
            update_fields.append("sales_manager")

        if status is not None:
            inquiry.status = status
            update_fields.append("status")

        if is_new_customer is not None:
            inquiry.is_new_customer = is_new_customer
            update_fields.append("is_new_customer")

        if update_fields:
            with transaction.atomic():
                # Run validation before saving
                inquiry.full_clean()
                inquiry.save(update_fields=update_fields)

            # Only now is the old file genuinely unreferenced.
            if superseded_attachment is not None:
                superseded_attachment.delete(save=False)

        return inquiry

    @staticmethod
    def delete_inquiry(*, inquiry: Inquiry) -> None:
        """
        Delete inquiry with validation
        Also cleans up attached files
        """
        if inquiry.status in ["success", "quoted"]:
            raise ValueError("Cannot delete inquiry with success or quoted status")

        # Clean up attachment file if exists
        if inquiry.attachment:
            inquiry.attachment.delete(save=False)

        inquiry.delete()


class InquiryKPIServices:
    """
    KPI-specific services for inquiry management
    Handles automatic KPI calculation and status management
    """

    @staticmethod
    def quote_inquiry(
        *, inquiry: Inquiry, quoted_at: timezone.datetime = None
    ) -> Inquiry:
        """
        Mark inquiry as quoted and calculate quote KPI metrics

        Args:
            inquiry: Inquiry instance to quote
            quoted_at: Custom quote timestamp (defaults to now)

        Returns:
            Updated inquiry with quote KPI data
        """
        if inquiry.is_locked:
            raise ValueError("Cannot update locked inquiry")

        if inquiry.status not in ["pending"]:
            raise ValueError(f"Cannot quote inquiry with status '{inquiry.status}'")

        quote_timestamp = quoted_at or timezone.now()

        with transaction.atomic():
            # Calculate quote time and grade
            quote_time = get_business_hours_between(inquiry.created_at, quote_timestamp)
            quote_grade = calculate_quote_grade(quote_time)

            # Update inquiry
            inquiry.status = "quoted"
            inquiry.quoted_at = quote_timestamp
            inquiry.quote_time = quote_time
            inquiry.quote_grade = quote_grade

            inquiry.save(
                update_fields=["status", "quoted_at", "quote_time", "quote_grade"]
            )

        return inquiry

    @staticmethod
    def complete_inquiry_success(
        *, inquiry: Inquiry, success_at: timezone.datetime = None
    ) -> Inquiry:
        """
        Mark inquiry as successful and calculate completion KPI metrics

        Args:
            inquiry: Inquiry instance to mark as successful
            success_at: Custom success timestamp (defaults to now)

        Returns:
            Updated inquiry with completion KPI data
        """
        if inquiry.is_locked:
            raise ValueError("Cannot update locked inquiry")

        if inquiry.status not in ["quoted"]:
            raise ValueError(
                f"Cannot mark inquiry as successful with status '{inquiry.status}'"
            )

        if not inquiry.quoted_at:
            raise ValueError("Cannot mark as successful without quote timestamp")

        success_timestamp = success_at or timezone.now()

        with transaction.atomic():
            # Calculate resolution time and grade
            resolution_time = get_business_hours_between(
                inquiry.quoted_at, success_timestamp
            )
            completion_grade = calculate_completion_grade(resolution_time)

            # Update inquiry
            inquiry.status = "success"
            inquiry.success_at = success_timestamp
            inquiry.resolution_time = resolution_time
            inquiry.completion_grade = completion_grade

            inquiry.save(
                update_fields=[
                    "status",
                    "success_at",
                    "resolution_time",
                    "completion_grade",
                ]
            )

        return inquiry

    @staticmethod
    def complete_inquiry_failed(
        *, inquiry: Inquiry, failed_at: timezone.datetime = None
    ) -> Inquiry:
        """
        Mark inquiry as failed and calculate completion KPI metrics

        Args:
            inquiry: Inquiry instance to mark as failed
            failed_at: Custom failed timestamp (defaults to now)

        Returns:
            Updated inquiry with completion KPI data
        """
        if inquiry.is_locked:
            raise ValueError("Cannot update locked inquiry")

        if inquiry.status not in ["quoted"]:
            raise ValueError(
                f"Cannot mark inquiry as failed with status '{inquiry.status}'"
            )

        if not inquiry.quoted_at:
            raise ValueError("Cannot mark as failed without quote timestamp")

        failed_timestamp = failed_at or timezone.now()

        with transaction.atomic():
            # Calculate resolution time and grade
            resolution_time = get_business_hours_between(
                inquiry.quoted_at, failed_timestamp
            )
            completion_grade = calculate_completion_grade(resolution_time)

            # Update inquiry
            inquiry.status = "failed"
            inquiry.failed_at = failed_timestamp
            inquiry.resolution_time = resolution_time
            inquiry.completion_grade = completion_grade

            inquiry.save(
                update_fields=[
                    "status",
                    "failed_at",
                    "resolution_time",
                    "completion_grade",
                ]
            )

        return inquiry

    @staticmethod
    def recalculate_kpi_metrics(*, inquiry: Inquiry, force: bool = False) -> Inquiry:
        """
        Recalculate KPI metrics for an inquiry

        Args:
            inquiry: Inquiry instance to recalculate
            force: Force recalculation even if inquiry is locked

        Returns:
            Updated inquiry with recalculated KPI data
        """
        if inquiry.is_locked and not force:
            raise ValueError(
                "Cannot recalculate metrics for locked inquiry (use force=True to override)"
            )

        if inquiry.auto_completion and not force:
            return inquiry  # Skip auto-completion inquiries unless forced

        update_fields = []

        with transaction.atomic():
            # Recalculate quote metrics if quoted
            if inquiry.quoted_at and inquiry.created_at:
                quote_time = get_business_hours_between(
                    inquiry.created_at, inquiry.quoted_at
                )
                quote_grade = calculate_quote_grade(quote_time)

                if inquiry.quote_time != quote_time:
                    inquiry.quote_time = quote_time
                    update_fields.append("quote_time")

                if inquiry.quote_grade != quote_grade:
                    inquiry.quote_grade = quote_grade
                    update_fields.append("quote_grade")

            # Recalculate completion metrics if completed
            completion_timestamp = inquiry.success_at or inquiry.failed_at
            if completion_timestamp and inquiry.quoted_at:
                resolution_time = get_business_hours_between(
                    inquiry.quoted_at, completion_timestamp
                )
                completion_grade = calculate_completion_grade(resolution_time)

                if inquiry.resolution_time != resolution_time:
                    inquiry.resolution_time = resolution_time
                    update_fields.append("resolution_time")

                if inquiry.completion_grade != completion_grade:
                    inquiry.completion_grade = completion_grade
                    update_fields.append("completion_grade")

            # Save only if there are changes
            if update_fields:
                inquiry.save(update_fields=update_fields)

        return inquiry

    @staticmethod
    def lock_inquiry_kpi(*, inquiry: Inquiry) -> Inquiry:
        """Lock inquiry to prevent KPI recalculation"""
        if not inquiry.is_locked:
            inquiry.is_locked = True
            inquiry.save(update_fields=["is_locked"])
        return inquiry

    @staticmethod
    def unlock_inquiry_kpi(*, inquiry: Inquiry) -> Inquiry:
        """Unlock inquiry to allow KPI recalculation"""
        if inquiry.is_locked:
            inquiry.is_locked = False
            inquiry.save(update_fields=["is_locked"])
        return inquiry

    @staticmethod
    def set_auto_completion(
        *, inquiry: Inquiry, auto_completion: bool = True
    ) -> Inquiry:
        """Set auto-completion flag to skip automatic KPI calculations"""
        if inquiry.auto_completion != auto_completion:
            inquiry.auto_completion = auto_completion
            inquiry.save(update_fields=["auto_completion"])
        return inquiry


class KPIWeightsServices:
    """
    Services for managing KPI weights configuration
    """

    @staticmethod
    def get_current_weights() -> dict:
        """
        Get the currently active KPI weights configuration

        Returns:
            Dictionary with current weights, fallback to defaults if none active
        """
        return KPIWeights.get_current_weights_dict()

    @staticmethod
    def get_current_weights_instance() -> KPIWeights | None:
        """
        Get the current KPIWeights instance

        Returns:
            Current KPIWeights instance or None if no configuration exists
        """
        return KPIWeights.get_current_weights()

    @staticmethod
    def create_weights_configuration(
        *,
        response_time_weight: float,
        follow_up_weight: float,
        conversion_rate_weight: float,
        new_customer_weight: float,
        created_by: "CustomUser" = None,
    ) -> KPIWeights:
        """
        Create new KPI weights configuration (replaces existing)

        Args:
            response_time_weight: Weight for response time KPI
            follow_up_weight: Weight for follow-up KPI
            conversion_rate_weight: Weight for conversion rate KPI
            new_customer_weight: Weight for new customer KPI
            created_by: User creating this configuration

        Returns:
            Created KPIWeights instance

        Raises:
            ValueError: If weights are invalid
        """
        with transaction.atomic():
            weights = KPIWeights(
                response_time_weight=response_time_weight,
                follow_up_weight=follow_up_weight,
                conversion_rate_weight=conversion_rate_weight,
                new_customer_weight=new_customer_weight,
                created_by=created_by,
            )

            # This will trigger validation and replace existing configuration
            weights.full_clean()
            weights.save()

        return weights

    @staticmethod
    def update_weights_configuration(
        *,
        weights_instance: KPIWeights,
        response_time_weight: float = None,
        follow_up_weight: float = None,
        conversion_rate_weight: float = None,
        new_customer_weight: float = None,
    ) -> KPIWeights:
        """
        Update existing KPI weights configuration

        Args:
            weights_instance: KPIWeights instance to update
            response_time_weight: New response time weight
            follow_up_weight: New follow-up weight
            conversion_rate_weight: New conversion rate weight
            new_customer_weight: New new customer weight

        Returns:
            Updated KPIWeights instance
        """
        update_fields = []

        if response_time_weight is not None:
            weights_instance.response_time_weight = response_time_weight
            update_fields.append("response_time_weight")

        if follow_up_weight is not None:
            weights_instance.follow_up_weight = follow_up_weight
            update_fields.append("follow_up_weight")

        if conversion_rate_weight is not None:
            weights_instance.conversion_rate_weight = conversion_rate_weight
            update_fields.append("conversion_rate_weight")

        if new_customer_weight is not None:
            weights_instance.new_customer_weight = new_customer_weight
            update_fields.append("new_customer_weight")

        if update_fields:
            with transaction.atomic():
                # This will trigger validation
                weights_instance.full_clean()
                weights_instance.save(update_fields=update_fields)

        return weights_instance

    @staticmethod
    def delete_weights_configuration(*, weights_instance: KPIWeights) -> None:
        """
        Delete the weights configuration

        Args:
            weights_instance: KPIWeights instance to delete
        """
        weights_instance.delete()

    @staticmethod
    def calculate_weighted_kpi_score(
        *,
        response_time_percentage: float,
        follow_up_percentage: float,
        conversion_rate: float,
        new_customer_percentage: float,
        weights: dict = None,
    ) -> float:
        """
        Calculate weighted KPI score using current or provided weights

        Args:
            response_time_percentage: Response time performance (0-100)
            follow_up_percentage: Follow-up performance (0-100)
            conversion_rate: Conversion rate (0-100)
            new_customer_percentage: New customer acquisition rate (0-100)
            weights: Optional custom weights dict, uses current if not provided

        Returns:
            Weighted KPI score (0-100)
        """
        if weights is None:
            weights = KPIWeightsServices.get_current_weights()

        # Calculate weighted score
        weighted_score = (
            (response_time_percentage * weights["response_time_weight"] / 100)
            + (follow_up_percentage * weights["follow_up_weight"] / 100)
            + (conversion_rate * weights["conversion_rate_weight"] / 100)
            + (new_customer_percentage * weights["new_customer_weight"] / 100)
        )

        return round(weighted_score, 2)


class PerformanceTargetServices:
    """
    Services for performance target-related business logic
    """

    @staticmethod
    def get_performance_grade(
        *,
        manager_id: int,
        date_from: timezone.datetime = None,
        date_to: timezone.datetime = None,
    ) -> dict:
        """
        Calculate manager's performance grade based on volume and targets

        Args:
            manager_id: Manager's user ID
            date_from: Start date for calculation (defaults to current month start)
            date_to: End date for calculation (defaults to current month end)

        Returns:
            dict: {
                'grade': str,           # 'excellent' or 'average'
                'performance': float,   # Overall performance percentage
                'inquiry_count': int,   # Number of inquiries in period
                'target_bracket': str,  # e.g., '31-60' or '101+'
                'excellent_threshold': float,  # Excellent grade threshold
                'target_info': dict     # Complete target information
            }
        """
        from .selectors import InquirySelectors

        # Default to current month if no dates provided
        if date_from is None or date_to is None:
            now = timezone.now()
            date_from = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            # Get last day of current month
            if now.month == 12:
                next_month = now.replace(year=now.year + 1, month=1, day=1)
            else:
                next_month = now.replace(month=now.month + 1, day=1)
            date_to = next_month - timezone.timedelta(days=1)
            date_to = date_to.replace(hour=23, minute=59, second=59, microsecond=999999)

        # Get inquiry count for the manager in the period
        inquiry_count = InquirySelectors.get_manager_inquiry_count(
            manager_id=manager_id, date_from=date_from, date_to=date_to
        )

        # Find applicable target configuration
        target = PerformanceTarget.get_target_for_volume(inquiry_count)

        if not target:
            # No target configured - return default values
            return {
                "grade": "unknown",
                "performance": 0.0,
                "inquiry_count": inquiry_count,
                "target_bracket": "not_configured",
                "thresholds": {},
                "target_info": None,
                "error": "No target configuration found for this volume",
            }

        # Get manager's KPI statistics
        manager_stats = InquirySelectors.get_manager_kpi_statistics(
            manager_id=manager_id, date_from=date_from, date_to=date_to
        )

        # Calculate overall performance using existing KPI logic
        overall_performance = 0.0
        if manager_stats and manager_stats.get("total_inquiries", 0) > 0:
            # Calculate performance percentages similar to dashboard logic
            # Response time percentage (quote efficiency)
            max_quote_points = manager_stats["total_inquiries"] * 3
            response_time_percentage = (
                (manager_stats["total_quote_points"] / max_quote_points * 100)
                if max_quote_points > 0
                else 0.0
            )

            # Follow-up percentage (completion efficiency)
            max_completion_points = manager_stats["completed_inquiries"] * 3
            follow_up_percentage = (
                (manager_stats["total_completion_points"] / max_completion_points * 100)
                if max_completion_points > 0
                else 0.0
            )

            # Get weighted overall performance
            overall_performance = KPIWeightsServices.calculate_weighted_kpi_score(
                response_time_percentage=response_time_percentage,
                follow_up_percentage=follow_up_percentage,
                conversion_rate=manager_stats["conversion_rate"],
                new_customer_percentage=manager_stats["lead_generation_rate"],
            )

        # Determine grade based on performance and target thresholds
        grade = target.get_grade_for_performance(overall_performance)

        return {
            "grade": grade,
            "performance": overall_performance,
            "inquiry_count": inquiry_count,
            "target_bracket": target.volume_display,
            "excellent_threshold": target.excellent_threshold,
            "target_info": {
                "id": target.id,
                "min_inquiries": target.min_inquiries,
                "max_inquiries": target.max_inquiries,
                "is_active": target.is_active,
            },
        }

    @staticmethod
    def create_target(
        *, min_inquiries: int, max_inquiries: int = None, excellent_threshold: float
    ) -> PerformanceTarget:
        """
        Create a new performance target configuration

        Args:
            min_inquiries: Minimum inquiries for this bracket
            max_inquiries: Maximum inquiries (None for unlimited)
            excellent_threshold: Minimum percentage for excellent grade

        Returns:
            Created PerformanceTarget instance

        Raises:
            ValueError: If validation fails
        """
        target = PerformanceTarget(
            min_inquiries=min_inquiries,
            max_inquiries=max_inquiries,
            excellent_threshold=excellent_threshold,
        )

        # This will trigger validation
        target.full_clean()
        target.save()

        return target

    @staticmethod
    def update_target(
        *,
        target_id: int,
        min_inquiries: int = None,
        max_inquiries: int = None,
        excellent_threshold: float = None,
        is_active: bool = None,
    ) -> PerformanceTarget:
        """
        Update existing performance target configuration

        Args:
            target_id: ID of target to update
            min_inquiries: New minimum inquiries
            max_inquiries: New maximum inquiries
            excellent_threshold: New excellent threshold
            is_active: New active status

        Returns:
            Updated PerformanceTarget instance

        Raises:
            PerformanceTarget.DoesNotExist: If target not found
            ValueError: If validation fails
        """
        target = PerformanceTarget.objects.get(id=target_id)

        update_fields = []

        if min_inquiries is not None:
            target.min_inquiries = min_inquiries
            update_fields.append("min_inquiries")

        if max_inquiries is not None:
            target.max_inquiries = max_inquiries
            update_fields.append("max_inquiries")

        if excellent_threshold is not None:
            target.excellent_threshold = excellent_threshold
            update_fields.append("excellent_threshold")

        if is_active is not None:
            target.is_active = is_active
            update_fields.append("is_active")

        if update_fields:
            # This will trigger validation
            target.full_clean()
            target.save(update_fields=update_fields + ["updated_at"])

        return target

    @staticmethod
    def delete_target(*, target_id: int) -> None:
        """
        Delete a performance target configuration

        Args:
            target_id: ID of target to delete

        Raises:
            PerformanceTarget.DoesNotExist: If target not found
        """
        target = PerformanceTarget.objects.get(id=target_id)
        target.delete()

    @staticmethod
    def bulk_create_update_targets(*, targets_data: list) -> list:
        """
        Bulk create/update performance targets based on array payload

        Args:
            targets_data: List of dicts containing target data
                         If 'id' present - update existing, otherwise create new

        Returns:
            List of created/updated PerformanceTarget instances

        Raises:
            ValueError: If validation fails
            PerformanceTarget.DoesNotExist: If target ID not found
            ValidationError: If ranges overlap or coverage is incomplete
        """
        results = []

        with transaction.atomic():
            # Step 1: Validate the entire set of targets before making any changes
            PerformanceTargetServices._validate_target_set(targets_data)

            # Step 2: Process each target
            for target_data in targets_data:
                target_id = target_data.get("id")

                # Map frontend field names to model field names
                model_data = {
                    "min_inquiries": target_data.get("min_inquiries"),
                    "max_inquiries": target_data.get("max_inquiries"),
                    "excellent_threshold": target_data.get("excellent_kpi"),
                    "is_active": target_data.get("is_active", True),
                }

                # Remove None values
                model_data = {k: v for k, v in model_data.items() if v is not None}

                if target_id:
                    # Update existing target
                    target = PerformanceTargetServices.update_target(
                        target_id=target_id, **model_data
                    )
                else:
                    # Create new target - extract is_active for separate handling
                    create_data = {
                        k: v for k, v in model_data.items() if k != "is_active"
                    }
                    target = PerformanceTargetServices.create_target(**create_data)

                    # Handle is_active separately for new targets
                    if (
                        "is_active" in model_data
                        and model_data["is_active"] != target.is_active
                    ):
                        target.is_active = model_data["is_active"]
                        target.save(update_fields=["is_active"])

                results.append(target)

        return results

    @staticmethod
    def _validate_target_set(targets_data: list):
        """
        Validate the entire set of targets for overlaps and coverage

        Args:
            targets_data: List of target data dicts

        Raises:
            ValidationError: If validation fails
        """
        from django.core.exceptions import ValidationError

        if not targets_data:
            return

        # Convert frontend data to ranges for validation
        ranges = []
        for i, data in enumerate(targets_data):
            try:
                min_val = data.get("min_inquiries")
                max_val = data.get("max_inquiries")

                if min_val is None:
                    raise ValidationError(f"Item {i + 1}: min_inquiries is required")

                if min_val < 0:
                    raise ValidationError(
                        f"Item {i + 1}: min_inquiries cannot be negative"
                    )

                if max_val is not None and max_val < min_val:
                    raise ValidationError(
                        f"Item {i + 1}: max_inquiries must be >= min_inquiries"
                    )

                ranges.append(
                    {"index": i, "min": min_val, "max": max_val, "id": data.get("id")}
                )

            except (TypeError, ValueError) as e:
                raise ValidationError(
                    f"Item {i + 1}: Invalid numeric values - {str(e)}"
                )

        # Sort ranges by min_inquiries for validation
        ranges.sort(key=lambda x: x["min"])

        # Check for overlaps within the submitted data
        for i in range(len(ranges)):
            for j in range(i + 1, len(ranges)):
                range1 = ranges[i]
                range2 = ranges[j]

                if PerformanceTargetServices._ranges_overlap_validation(
                    range1["min"], range1["max"], range2["min"], range2["max"]
                ):
                    range1_display = (
                        f"{range1['min']}-{range1['max']}"
                        if range1["max"]
                        else f"{range1['min']}+"
                    )
                    range2_display = (
                        f"{range2['min']}-{range2['max']}"
                        if range2["max"]
                        else f"{range2['min']}+"
                    )

                    raise ValidationError(
                        f"Target ranges overlap: {range1_display} (item {range1['index'] + 1}) "
                        f"and {range2_display} (item {range2['index'] + 1}). "
                        "Target ranges cannot overlap."
                    )

        # Check for gaps in coverage (optional - can be enabled if needed)
        # This ensures complete coverage from 0 to infinity
        if PerformanceTargetServices._should_validate_coverage():
            PerformanceTargetServices._validate_range_coverage(ranges)

    @staticmethod
    def _ranges_overlap_validation(min1, max1, min2, max2):
        """
        Check if two ranges overlap (validation version)

        Args:
            min1, max1: First range (max1 can be None for unlimited)
            min2, max2: Second range (max2 can be None for unlimited)

        Returns:
            bool: True if ranges overlap
        """
        # Handle unlimited ranges (max is None)
        if max1 is None and max2 is None:
            # Both unlimited - they always overlap
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

    @staticmethod
    def _should_validate_coverage():
        """
        Determine if range coverage validation should be enforced
        Can be made configurable later if needed

        For now, we'll be more flexible and only validate coverage within
        the submitted set, not requiring complete coverage from 0 to infinity
        """
        return False  # Disable strict coverage validation for flexibility

    @staticmethod
    def _validate_range_coverage(ranges: list):
        """
        Validate that ranges provide complete coverage from 0 to infinity

        Args:
            ranges: List of sorted range dicts

        Raises:
            ValidationError: If coverage is incomplete
        """
        from django.core.exceptions import ValidationError

        if not ranges:
            return

        # Check if first range starts at 0
        if ranges[0]["min"] > 0:
            raise ValidationError(
                f"Coverage gap: No target defined for 0-{ranges[0]['min'] - 1} inquiries. "
                "First target should start at 0."
            )

        # Check for gaps between ranges
        for i in range(len(ranges) - 1):
            current_range = ranges[i]
            next_range = ranges[i + 1]

            if current_range["max"] is None:
                # Current range is unlimited, so no more ranges should follow
                raise ValidationError(
                    f"Invalid configuration: Range {current_range['min']}+ is unlimited "
                    f"but another range {next_range['min']}-{next_range['max'] or '∞'} follows it."
                )

            # Check for gap between current max and next min
            if current_range["max"] + 1 < next_range["min"]:
                gap_start = current_range["max"] + 1
                gap_end = next_range["min"] - 1
                raise ValidationError(
                    f"Coverage gap: No target defined for {gap_start}-{gap_end} inquiries. "
                    f"Gap between range {current_range['min']}-{current_range['max']} "
                    f"and {next_range['min']}-{next_range['max'] or '∞'}."
                )

        # Check if the last range covers infinity
        last_range = ranges[-1]
        if last_range["max"] is not None:
            raise ValidationError(
                f"Coverage incomplete: Last range {last_range['min']}-{last_range['max']} "
                "should be unlimited (no max_inquiries) to cover all higher volumes."
            )

    @staticmethod
    def create_default_targets() -> list:
        """
        Create default target configurations if none exist

        Returns:
            List of created PerformanceTarget instances
        """
        return PerformanceTarget.create_default_targets()

    @staticmethod
    def activate_target(*, target_id: int) -> PerformanceTarget:
        """
        Activate a performance target

        Args:
            target_id: ID of target to activate

        Returns:
            Updated PerformanceTarget instance
        """
        return PerformanceTargetServices.update_target(
            target_id=target_id, is_active=True
        )

    @staticmethod
    def deactivate_target(*, target_id: int) -> PerformanceTarget:
        """
        Deactivate a performance target

        Args:
            target_id: ID of target to deactivate

        Returns:
            Updated PerformanceTarget instance
        """
        return PerformanceTargetServices.update_target(
            target_id=target_id, is_active=False
        )
