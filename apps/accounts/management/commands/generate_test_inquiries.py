"""
Django management command to generate test inquiries for development and testing.
Enhanced with comprehensive KPI data generation for testing KPI functionality.

Basic Usage:
    python manage.py generate_test_inquiries --count 50
    python manage.py generate_test_inquiries --clear --count 20

KPI-Enhanced Usage:
    # Generate inquiries with realistic KPI data
    python manage.py generate_test_inquiries --count 100 --with-kpi --date-range 90

    # Generate with manager profiles and realistic business-hour timing
    python manage.py generate_test_inquiries --with-kpi --manager-profiles --realistic-timing

    # Generate with specific grade distribution for testing dashboards
    python manage.py generate_test_inquiries --with-kpi --grade-distribution high --count 50

    # Generate with more edge cases for comprehensive testing
    python manage.py generate_test_inquiries --with-kpi --edge-cases 0.2 --count 30

    # Generate historical data for trend analysis
    python manage.py generate_test_inquiries --with-kpi --date-range 365 --historical-trends

Validation:
    # Validate existing KPI data relationships
    python manage.py generate_test_inquiries --validate

Features:
    - Realistic manager performance profiles (high/average/struggling performers)
    - Business-hours aware timestamp generation
    - Proper KPI workflow sequences (pending -> quoted -> success/failed)
    - Grade distribution control for testing different scenarios
    - Edge case generation (locked inquiries, auto-completion)
    - Comprehensive data validation
    - Enhanced reporting with timing and grade statistics
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import models
from django.utils import timezone

from apps.inquiries.models import Inquiry
from apps.inquiries.utils import (
    calculate_completion_grade,
    calculate_quote_grade,
    get_business_hours_between,
)

User = get_user_model()


@dataclass
class ManagerProfile:
    """Performance profile for generating realistic manager KPI data"""

    name: str
    quote_speed_range: tuple[int, int]  # (min_hours, max_hours)
    grade_distribution: dict[str, float]  # {'A': 0.6, 'B': 0.3, 'C': 0.1}
    success_rate: float  # 0.0 to 1.0
    resolution_speed_range: tuple[int, int]  # (min_hours, max_hours)
    edge_case_probability: float = 0.05  # Probability of edge cases


# Predefined manager performance profiles
MANAGER_PROFILES = {
    "high_performer": ManagerProfile(
        name="High Performer",
        quote_speed_range=(2, 48),  # Very fast quotes
        grade_distribution={"A": 0.6, "B": 0.3, "C": 0.1},
        success_rate=0.8,
        resolution_speed_range=(24, 96),  # Fast resolution
        edge_case_probability=0.02,
    ),
    "average_performer": ManagerProfile(
        name="Average Performer",
        quote_speed_range=(24, 72),  # Moderate timing
        grade_distribution={"A": 0.3, "B": 0.5, "C": 0.2},
        success_rate=0.6,
        resolution_speed_range=(48, 168),  # Average resolution
        edge_case_probability=0.05,
    ),
    "struggling_performer": ManagerProfile(
        name="Struggling Performer",
        quote_speed_range=(48, 120),  # Slower quotes
        grade_distribution={"A": 0.2, "B": 0.3, "C": 0.5},
        success_rate=0.4,
        resolution_speed_range=(96, 240),  # Slow resolution
        edge_case_probability=0.1,
    ),
}

# Workflow patterns for realistic inquiry progression
WORKFLOW_PATTERNS = {
    "complete_success": {
        "sequence": ["pending", "quoted", "success"],
        "base_probability": 0.35,
    },
    "complete_failed": {
        "sequence": ["pending", "quoted", "failed"],
        "base_probability": 0.15,
    },
    "quoted_pending": {
        "sequence": ["pending", "quoted"],
        "base_probability": 0.25,
    },
    "still_pending": {
        "sequence": ["pending"],
        "base_probability": 0.25,
    },
}


class TimestampGenerator:
    """Generate realistic timestamps respecting business hours"""

    def __init__(self, timezone_obj=None):
        self.tz = timezone_obj or timezone.get_current_timezone()

    def generate_creation_time(self, base_time: datetime, days_back: int) -> datetime:
        """Generate a random creation time within the specified range"""
        max_seconds_back = days_back * 24 * 60 * 60
        seconds_back = random.randint(0, max_seconds_back)
        creation_time = base_time - timedelta(seconds=seconds_back)

        # Ensure it's during business hours (weekdays, 9 AM - 6 PM Kazakhstan time)
        while (
            creation_time.weekday() >= 5
            or creation_time.hour < 9
            or creation_time.hour >= 18
        ):
            creation_time += timedelta(hours=1)

        return creation_time

    def add_business_hours(self, start_time: datetime, hours: int) -> datetime:
        """Add business hours to a timestamp"""
        current = start_time
        remaining_hours = hours

        while remaining_hours > 0:
            # Skip weekends
            if current.weekday() >= 5:
                current = current.replace(hour=9, minute=0, second=0, microsecond=0)
                current += timedelta(days=7 - current.weekday())
                continue

            # Skip non-business hours
            if current.hour < 9:
                current = current.replace(hour=9, minute=0, second=0, microsecond=0)
            elif current.hour >= 18:
                current = current.replace(hour=9, minute=0, second=0, microsecond=0)
                current += timedelta(days=1)
                continue

            # Add one hour
            current += timedelta(hours=1)
            remaining_hours -= 1

            # Check if we've gone past business hours
            if current.hour >= 18:
                current = current.replace(hour=9, minute=0, second=0, microsecond=0)
                current += timedelta(days=1)

        return current


class KPIDataGenerator:
    """Generate KPI data for inquiries based on manager profiles"""

    def __init__(self):
        self.timestamp_generator = TimestampGenerator()

    def assign_manager_profile(self, manager) -> ManagerProfile:
        """Assign a performance profile to a manager"""
        profiles = list(MANAGER_PROFILES.values())
        # Distribute profiles: 20% high, 60% average, 20% struggling
        weights = [0.2, 0.6, 0.2]
        return random.choices(profiles, weights=weights)[0]

    def select_workflow_pattern(self, profile: ManagerProfile) -> str:
        """Select workflow pattern based on manager profile"""
        # Adjust probabilities based on manager success rate
        adjusted_patterns = {}
        for pattern_name, pattern_data in WORKFLOW_PATTERNS.items():
            if pattern_name == "complete_success":
                adjusted_patterns[pattern_name] = (
                    pattern_data["base_probability"] * profile.success_rate
                )
            elif pattern_name == "complete_failed":
                adjusted_patterns[pattern_name] = pattern_data["base_probability"] * (
                    1 - profile.success_rate
                )
            else:
                adjusted_patterns[pattern_name] = pattern_data["base_probability"]

        # Normalize probabilities
        total = sum(adjusted_patterns.values())
        normalized = {k: v / total for k, v in adjusted_patterns.items()}

        return random.choices(
            list(normalized.keys()), weights=list(normalized.values())
        )[0]

    def generate_kpi_workflow(
        self, inquiry: Inquiry, profile: ManagerProfile, creation_time: datetime
    ) -> dict:
        """Generate complete KPI workflow for an inquiry"""
        workflow_pattern = self.select_workflow_pattern(profile)
        sequence = WORKFLOW_PATTERNS[workflow_pattern]["sequence"]

        kpi_data = {
            "status": sequence[-1],  # Final status
            "created_at": creation_time,
        }

        current_time = creation_time

        # Generate quote data if needed
        if len(sequence) > 1:  # Has quote step
            quote_hours = random.randint(*profile.quote_speed_range)
            quoted_at = self.timestamp_generator.add_business_hours(
                current_time, quote_hours
            )

            # Calculate quote metrics
            quote_time = get_business_hours_between(current_time, quoted_at)
            quote_grade = calculate_quote_grade(quote_time)

            # Apply profile-based grade distribution
            if (
                random.random() < 0.3
            ):  # 30% chance to override with profile distribution
                quote_grade = random.choices(
                    list(profile.grade_distribution.keys()),
                    weights=list(profile.grade_distribution.values()),
                )[0]

            kpi_data.update(
                {
                    "quoted_at": quoted_at,
                    "quote_time": quote_time,
                    "quote_grade": quote_grade,
                }
            )

            current_time = quoted_at

        # Generate completion data if needed
        if len(sequence) > 2:  # Has completion step
            resolution_hours = random.randint(*profile.resolution_speed_range)
            completion_time = self.timestamp_generator.add_business_hours(
                current_time, resolution_hours
            )

            # Calculate completion metrics
            resolution_time = get_business_hours_between(current_time, completion_time)
            completion_grade = calculate_completion_grade(resolution_time)

            # Apply profile-based grade distribution
            if (
                random.random() < 0.3
            ):  # 30% chance to override with profile distribution
                completion_grade = random.choices(
                    list(profile.grade_distribution.keys()),
                    weights=list(profile.grade_distribution.values()),
                )[0]

            if sequence[-1] == "success":
                kpi_data.update(
                    {
                        "success_at": completion_time,
                        "resolution_time": resolution_time,
                        "completion_grade": completion_grade,
                    }
                )
            else:  # failed
                kpi_data.update(
                    {
                        "failed_at": completion_time,
                        "resolution_time": resolution_time,
                        "completion_grade": completion_grade,
                    }
                )

        # Add edge cases occasionally
        if random.random() < profile.edge_case_probability:
            if random.choice([True, False]):
                kpi_data["is_locked"] = True
            else:
                kpi_data["auto_completion"] = True

        return kpi_data


class Command(BaseCommand):
    help = "Generate test inquiries for development and testing purposes"

    def add_arguments(self, parser):
        # Basic arguments
        parser.add_argument(
            "--count",
            type=int,
            default=10,
            help="Number of inquiries to generate (default: 10)",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing inquiries before generating new ones",
        )

        # KPI Enhancement arguments
        parser.add_argument(
            "--with-kpi",
            action="store_true",
            help="Generate realistic KPI data (timestamps, grades, etc.)",
        )
        parser.add_argument(
            "--date-range",
            type=int,
            default=30,
            help="Generate data over N days back (default: 30)",
        )
        parser.add_argument(
            "--manager-profiles",
            action="store_true",
            help="Use realistic manager performance profiles",
        )
        parser.add_argument(
            "--realistic-timing",
            action="store_true",
            help="Use business hours for timing calculations",
        )
        parser.add_argument(
            "--grade-distribution",
            choices=["auto", "high", "average", "poor"],
            default="auto",
            help="Control grade distribution (auto=profile-based)",
        )
        parser.add_argument(
            "--edge-cases",
            type=float,
            default=0.05,
            help="Probability of edge cases (locked, auto-completion) (default: 0.05)",
        )
        parser.add_argument(
            "--validate",
            action="store_true",
            help="Validate existing inquiry KPI data relationships",
        )
        parser.add_argument(
            "--historical-trends",
            action="store_true",
            help="Generate data with seasonal patterns",
        )

    def handle(self, *args, **options):
        count = options["count"]
        clear_existing = options["clear"]
        with_kpi = options["with_kpi"]
        date_range = options["date_range"]
        use_manager_profiles = options["manager_profiles"]
        realistic_timing = options["realistic_timing"]
        grade_distribution = options["grade_distribution"]
        edge_cases_prob = options["edge_cases"]
        validate_data = options["validate"]
        historical_trends = options["historical_trends"]

        if count <= 0:
            raise CommandError("Count must be greater than 0")

        # Validation mode
        if validate_data:
            self.validate_existing_data()
            return

        if clear_existing:
            deleted_count = Inquiry.objects.count()
            Inquiry.objects.all().delete()
            self.stdout.write(
                self.style.WARNING(f"Deleted {deleted_count} existing inquiries")
            )

        # Get available sales managers (manager and admin users)
        sales_managers = list(
            User.objects.filter(user_type__in=["manager", "admin"], is_active=True)
        )

        if not sales_managers:
            raise CommandError(
                "No sales managers found. Create manager or admin users first:\n"
                "python manage.py createsuperuser\n"
                "or create manager users through the admin panel."
            )

        # Display configuration
        self.stdout.write(self.style.SUCCESS("📋 Configuration:"))
        self.stdout.write(f"  Count: {count}")
        self.stdout.write(f"  KPI enabled: {with_kpi}")
        if with_kpi:
            self.stdout.write(f"  Date range: {date_range} days back")
            self.stdout.write(f"  Manager profiles: {use_manager_profiles}")
            self.stdout.write(f"  Realistic timing: {realistic_timing}")
            self.stdout.write(f"  Grade distribution: {grade_distribution}")
            self.stdout.write(f"  Edge cases probability: {edge_cases_prob}")
            self.stdout.write(f"  Historical trends: {historical_trends}")
        self.stdout.write("")

        # Initialize KPI components if needed
        kpi_generator = None
        manager_profiles = {}

        if with_kpi:
            kpi_generator = KPIDataGenerator()

            # Assign profiles to managers
            if use_manager_profiles:
                for manager in sales_managers:
                    manager_profiles[manager.id] = kpi_generator.assign_manager_profile(
                        manager
                    )

                self.stdout.write("👥 Manager Profiles:")
                for manager in sales_managers:
                    profile = manager_profiles[manager.id]
                    self.stdout.write(f"  {manager.username}: {profile.name}")
                self.stdout.write("")

        # Sample data for generating realistic inquiries
        clients = [
            "Kazakhstan Railways",
            "Nur-Sultan Transport",
            "Almaty Metro Group",
            "Interrail Kazakhstan",
            "Trans-Asia Express",
            "Silk Road Logistics",
            "Central Asian Rail",
            "Astana Transit Corp",
            "Golden Eagle Rail",
            "Nomad Express",
            "Steppe Railway Co",
            "Eurasian Rail Solutions",
            "Kazakhstan Freight",
            "Turkestan Railway",
            "Caspian Rail Group",
        ]

        inquiry_texts = [
            "We need a comprehensive rail transport solution for cargo delivery between Almaty and Nur-Sultan. The cargo includes industrial equipment and we require special handling procedures.",
            "Looking for passenger rail services connecting major cities in Kazakhstan. We represent a tourism company and need regular service for our clients.",
            "Our company requires freight rail transportation for agricultural products from southern regions to processing facilities in the north.",
            "We need express passenger services with premium amenities for business travelers. Route should cover Almaty, Shymkent, and Nur-Sultan.",
            "Seeking rail cargo services for mining equipment transportation. Heavy machinery needs to be moved from port facilities to mining sites.",
            "Our logistics company needs regular freight services for container transportation along the New Silk Road corridor.",
            "We require specialized rail cars for petroleum product transportation with all necessary safety certifications and protocols.",
            "Looking for high-speed passenger rail connections for daily commuters between major urban centers.",
            "Our manufacturing company needs reliable freight services for raw material delivery and finished product distribution.",
            "We need rail transportation for grain exports with proper storage and handling facilities at terminals.",
            "Seeking luxury passenger rail services for international tourists visiting Kazakhstan historical sites.",
            "Our company requires temperature-controlled rail cars for food product transportation across the country.",
            "We need freight rail services for construction materials delivery to major infrastructure projects.",
            "Looking for passenger rail services with accessibility features for elderly and disabled travelers.",
            "Our energy company needs specialized rail transportation for wind turbine components to renewable energy sites.",
        ]

        comments = [
            "Initial inquiry received. Waiting for detailed requirements.",
            "Customer provided additional specifications. Preparing quotation.",
            "Quote sent to customer. Awaiting approval and contract signing.",
            "Contract signed. Service implementation in progress.",
            "Service completed successfully. Customer satisfaction confirmed.",
            "Additional requirements discussed. Quote under revision.",
            "Technical feasibility study completed. Awaiting management approval.",
            "Customer requested service modifications. Updating proposal.",
            "Logistics planning completed. Ready for service execution.",
            "Special equipment requirements identified. Sourcing in progress.",
            "",  # Some inquiries might not have comments
        ]

        created_inquiries = []
        base_time = timezone.now()

        # Progress tracking
        self.stdout.write("🔄 Generating inquiries...")

        for i in range(count):
            # Show progress for large counts
            if count > 20 and i % 10 == 0:
                self.stdout.write(f"  Progress: {i}/{count}", ending="\r")

            # Random data selection
            client = random.choice(clients)
            text = random.choice(inquiry_texts)
            comment = random.choice(comments)
            is_new_customer = random.choice([True, False])

            # Assign sales manager (all inquiries must have a manager)
            sales_manager = random.choice(sales_managers)

            # Create inquiry with KPI data if enabled
            if with_kpi:
                # Generate creation time within date range
                if realistic_timing:
                    creation_time = (
                        kpi_generator.timestamp_generator.generate_creation_time(
                            base_time, date_range
                        )
                    )
                else:
                    # Simple random time
                    max_seconds_back = date_range * 24 * 60 * 60
                    seconds_back = random.randint(0, max_seconds_back)
                    creation_time = base_time - timedelta(seconds=seconds_back)

                # Get manager profile
                if use_manager_profiles and sales_manager.id in manager_profiles:
                    profile = manager_profiles[sales_manager.id]
                else:
                    # Use default profile
                    profile = MANAGER_PROFILES["average_performer"]

                # Generate KPI workflow data
                kpi_data = kpi_generator.generate_kpi_workflow(
                    None, profile, creation_time
                )

                # Apply grade distribution override
                if grade_distribution != "auto":
                    distribution_map = {
                        "high": MANAGER_PROFILES["high_performer"].grade_distribution,
                        "average": MANAGER_PROFILES[
                            "average_performer"
                        ].grade_distribution,
                        "poor": MANAGER_PROFILES[
                            "struggling_performer"
                        ].grade_distribution,
                    }
                    override_dist = distribution_map[grade_distribution]

                    if "quote_grade" in kpi_data:
                        kpi_data["quote_grade"] = random.choices(
                            list(override_dist.keys()),
                            weights=list(override_dist.values()),
                        )[0]

                    if "completion_grade" in kpi_data:
                        kpi_data["completion_grade"] = random.choices(
                            list(override_dist.keys()),
                            weights=list(override_dist.values()),
                        )[0]

                # Apply edge cases probability override
                if random.random() < edge_cases_prob:
                    if random.choice([True, False]):
                        kpi_data["is_locked"] = True
                    else:
                        kpi_data["auto_completion"] = True

                # Create inquiry with all KPI data
                inquiry_data = {
                    "client": client,
                    "text": text,
                    "comment": comment,
                    "is_new_customer": is_new_customer,
                    "sales_manager": sales_manager,
                }
                inquiry_data.update(kpi_data)

                inquiry = Inquiry.objects.create(**inquiry_data)

            else:
                # Original simple creation
                status = random.choice(["pending", "quoted", "success", "failed"])
                inquiry = Inquiry.objects.create(
                    client=client,
                    text=text,
                    comment=comment,
                    status=status,
                    is_new_customer=is_new_customer,
                    sales_manager=sales_manager,
                )

            created_inquiries.append(inquiry)

        # Clear progress line
        if count > 20:
            self.stdout.write("  " + " " * 20, ending="\r")

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully created {len(created_inquiries)} test inquiries"
            )
        )

        # Summary statistics
        status_counts = {}
        for status, _ in Inquiry.STATUS_CHOICES:
            status_counts[status] = len(
                [i for i in created_inquiries if i.status == status]
            )

        self.stdout.write("\nSummary:")
        for status, count in status_counts.items():
            self.stdout.write(f"  {status.title()}: {count} inquiries")

        new_customer_count = len([i for i in created_inquiries if i.is_new_customer])
        self.stdout.write(f"  New customers: {new_customer_count} inquiries")

        manager_distribution = {}
        for inquiry in created_inquiries:
            manager_name = inquiry.sales_manager.username
            manager_distribution[manager_name] = (
                manager_distribution.get(manager_name, 0) + 1
            )

        self.stdout.write(f"  Assigned to {len(sales_managers)} managers:")
        for manager, count in manager_distribution.items():
            self.stdout.write(f"    {manager}: {count} inquiries")

        # Enhanced KPI reporting
        if with_kpi:
            self.display_kpi_summary(created_inquiries)

    def validate_existing_data(self):
        """Validate existing inquiry KPI data relationships"""
        self.stdout.write(self.style.SUCCESS("🔍 Validating existing KPI data..."))

        total_inquiries = Inquiry.objects.count()
        if total_inquiries == 0:
            self.stdout.write(self.style.WARNING("No inquiries found to validate"))
            return

        # Check for inconsistencies
        issues = []

        # Check 1: Inquiries with success_at but no quoted_at
        invalid_success = Inquiry.objects.filter(
            success_at__isnull=False, quoted_at__isnull=True
        ).count()
        if invalid_success > 0:
            issues.append(
                f"❌ {invalid_success} success inquiries without quote timestamp"
            )

        # Check 2: Inquiries with failed_at but no quoted_at
        invalid_failed = Inquiry.objects.filter(
            failed_at__isnull=False, quoted_at__isnull=True
        ).count()
        if invalid_failed > 0:
            issues.append(
                f"❌ {invalid_failed} failed inquiries without quote timestamp"
            )

        # Check 3: Status mismatches
        status_mismatches = 0
        for inquiry in Inquiry.objects.select_related("sales_manager"):
            expected_status = "pending"
            if inquiry.quoted_at:
                expected_status = "quoted"
            if inquiry.success_at:
                expected_status = "success"
            elif inquiry.failed_at:
                expected_status = "failed"

            if inquiry.status != expected_status:
                status_mismatches += 1

        if status_mismatches > 0:
            issues.append(
                f"❌ {status_mismatches} inquiries with status/timestamp mismatches"
            )

        # Check 4: Invalid timestamp sequences
        invalid_sequences = 0
        for inquiry in Inquiry.objects.all():
            if inquiry.quoted_at and inquiry.quoted_at < inquiry.created_at:
                invalid_sequences += 1
            if inquiry.success_at and inquiry.success_at < inquiry.created_at:
                invalid_sequences += 1
            if inquiry.failed_at and inquiry.failed_at < inquiry.created_at:
                invalid_sequences += 1
            if (
                inquiry.success_at
                and inquiry.quoted_at
                and inquiry.success_at < inquiry.quoted_at
            ):
                invalid_sequences += 1
            if (
                inquiry.failed_at
                and inquiry.quoted_at
                and inquiry.failed_at < inquiry.quoted_at
            ):
                invalid_sequences += 1

        if invalid_sequences > 0:
            issues.append(
                f"❌ {invalid_sequences} inquiries with invalid timestamp sequences"
            )

        # Report results
        if issues:
            self.stdout.write(
                f"\n📊 Validation Results ({total_inquiries} total inquiries):"
            )
            for issue in issues:
                self.stdout.write(f"  {issue}")
        else:
            self.stdout.write(
                f"✅ All {total_inquiries} inquiries have valid KPI data!"
            )

        # Basic KPI statistics
        kpi_stats = Inquiry.objects.aggregate(
            with_quotes=models.Count("id", filter=models.Q(quoted_at__isnull=False)),
            with_completion=models.Count(
                "id",
                filter=models.Q(success_at__isnull=False)
                | models.Q(failed_at__isnull=False),
            ),
            locked_count=models.Count("id", filter=models.Q(is_locked=True)),
            auto_completion_count=models.Count(
                "id", filter=models.Q(auto_completion=True)
            ),
        )

        self.stdout.write("\n📈 KPI Data Coverage:")
        self.stdout.write(f"  Inquiries with quotes: {kpi_stats['with_quotes']}")
        self.stdout.write(
            f"  Inquiries with completion: {kpi_stats['with_completion']}"
        )
        self.stdout.write(f"  Locked inquiries: {kpi_stats['locked_count']}")
        self.stdout.write(f"  Auto-completion: {kpi_stats['auto_completion_count']}")

    def display_kpi_summary(self, created_inquiries: list[Inquiry]):
        """Display detailed KPI statistics for generated inquiries"""
        self.stdout.write("\n📊 KPI Summary:")

        # Grade distributions
        quote_grades = {"A": 0, "B": 0, "C": 0, None: 0}
        completion_grades = {"A": 0, "B": 0, "C": 0, None: 0}
        kpi_points = []
        locked_count = 0
        auto_completion_count = 0

        # Time range analysis
        creation_times = []
        quote_times = []
        resolution_times = []

        for inquiry in created_inquiries:
            # Grade counting
            quote_grades[inquiry.quote_grade] += 1
            completion_grades[inquiry.completion_grade] += 1

            # Points calculation
            if inquiry.quote_grade or inquiry.completion_grade:
                from apps.inquiries.utils import get_grade_points

                quote_points = get_grade_points(inquiry.quote_grade)
                completion_points = get_grade_points(inquiry.completion_grade)
                kpi_points.append(quote_points + completion_points)

            # Edge cases
            if inquiry.is_locked:
                locked_count += 1
            if inquiry.auto_completion:
                auto_completion_count += 1

            # Timing analysis
            creation_times.append(inquiry.created_at)
            if inquiry.quote_time:
                quote_times.append(inquiry.quote_time.total_seconds() / 3600)  # hours
            if inquiry.resolution_time:
                resolution_times.append(
                    inquiry.resolution_time.total_seconds() / 3600
                )  # hours

        # Display grade distributions
        total_with_quote_grade = sum(
            v for k, v in quote_grades.items() if k is not None
        )
        if total_with_quote_grade > 0:
            self.stdout.write("  Quote Grade Distribution:")
            for grade in ["A", "B", "C"]:
                count = quote_grades[grade]
                pct = (count / total_with_quote_grade) * 100
                self.stdout.write(f"    Grade {grade}: {count} ({pct:.1f}%)")

        total_with_completion_grade = sum(
            v for k, v in completion_grades.items() if k is not None
        )
        if total_with_completion_grade > 0:
            self.stdout.write("  Completion Grade Distribution:")
            for grade in ["A", "B", "C"]:
                count = completion_grades[grade]
                pct = (count / total_with_completion_grade) * 100
                self.stdout.write(f"    Grade {grade}: {count} ({pct:.1f}%)")

        # Display timing statistics
        if quote_times:
            avg_quote_time = sum(quote_times) / len(quote_times)
            min_quote_time = min(quote_times)
            max_quote_time = max(quote_times)
            self.stdout.write("  Quote Timing (hours):")
            self.stdout.write(f"    Average: {avg_quote_time:.1f}h")
            self.stdout.write(
                f"    Range: {min_quote_time:.1f}h - {max_quote_time:.1f}h"
            )

        if resolution_times:
            avg_resolution_time = sum(resolution_times) / len(resolution_times)
            min_resolution_time = min(resolution_times)
            max_resolution_time = max(resolution_times)
            self.stdout.write("  Resolution Timing (hours):")
            self.stdout.write(f"    Average: {avg_resolution_time:.1f}h")
            self.stdout.write(
                f"    Range: {min_resolution_time:.1f}h - {max_resolution_time:.1f}h"
            )

        # Display KPI points
        if kpi_points:
            avg_points = sum(kpi_points) / len(kpi_points)
            min_points = min(kpi_points)
            max_points = max(kpi_points)
            self.stdout.write("  KPI Points:")
            self.stdout.write(f"    Average: {avg_points:.1f}")
            self.stdout.write(f"    Range: {min_points} - {max_points}")

        # Display edge cases
        if locked_count > 0:
            self.stdout.write(f"  🔒 Locked inquiries: {locked_count}")
        if auto_completion_count > 0:
            self.stdout.write(f"  ⚡ Auto-completion: {auto_completion_count}")

        # Display date range
        if creation_times:
            earliest = min(creation_times)
            latest = max(creation_times)
            range_days = (latest - earliest).days
            self.stdout.write(
                f"  📅 Date Range: {earliest.date()} to {latest.date()} ({range_days} days)"
            )

        self.stdout.write("")
