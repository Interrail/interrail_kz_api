"""
User management business logic tests.
Focus on real integration without mocks.
"""

import pytest
from django.contrib.auth import get_user_model

from apps.accounts.selectors import UserSelectors
from apps.accounts.services import UserServices

User = get_user_model()


@pytest.mark.django_db
class TestUserServices:
    """Test user management business logic with real database operations."""

    def test_create_user_with_all_fields(self):
        """Test creating user with complete information."""
        user = UserServices.create_user(
            username="testuser",
            email="test@example.com",
            password="testpassword123",
            user_type="manager",
            first_name="John",
            last_name="Doe",
            telegram_id="123456789",
            telegram_username="johndoe_tg",
            telegram_access=True,
        )

        assert user.username == "testuser"
        assert user.email == "test@example.com"
        assert user.user_type == "manager"
        assert user.first_name == "John"
        assert user.last_name == "Doe"
        assert user.telegram_id == "123456789"
        assert user.telegram_username == "johndoe_tg"
        assert user.telegram_access is True
        assert user.check_password("testpassword123")
        assert user.is_active is True

    def test_create_user_with_minimal_fields(self):
        """Test creating user with only required fields."""
        user = UserServices.create_user(
            username="minimal",
            email="minimal@example.com",
            password="password123",
        )

        assert user.username == "minimal"
        assert user.email == "minimal@example.com"
        assert user.user_type == "customer"  # Default value
        assert user.is_active is True

    def test_create_user_duplicate_username_fails(self):
        """Test that creating user with duplicate username fails."""
        # Create first user
        UserServices.create_user(
            username="duplicate",
            email="first@example.com",
            password="password123",
        )

        # Attempt to create second user with same username
        with pytest.raises(ValueError, match="already exists"):
            UserServices.create_user(
                username="duplicate",
                email="second@example.com",
                password="password123",
            )

    def test_create_user_duplicate_email_fails(self):
        """Test that creating user with duplicate email fails."""
        # Create first user
        UserServices.create_user(
            username="first",
            email="duplicate@example.com",
            password="password123",
        )

        # Attempt to create second user with same email
        with pytest.raises(ValueError, match="already exists"):
            UserServices.create_user(
                username="second",
                email="duplicate@example.com",
                password="password123",
            )

    def test_update_user_basic_fields(self):
        """Test updating user basic information."""
        user = User.objects.create_user(
            username="original",
            email="original@example.com",
            password="password123",
        )

        updated_user = UserServices.update_user(
            user_id=user.id,
            first_name="Updated",
            last_name="Name",
            telegram_username="updated_tg",
        )

        assert updated_user.first_name == "Updated"
        assert updated_user.last_name == "Name"
        assert updated_user.telegram_username == "updated_tg"
        assert updated_user.username == "original"  # Unchanged

    def test_update_user_email(self):
        """Test updating user email address."""
        user = User.objects.create_user(
            username="testuser",
            email="old@example.com",
            password="password123",
        )

        updated_user = UserServices.update_user(
            user_id=user.id,
            email="new@example.com",
        )

        assert updated_user.email == "new@example.com"

    def test_update_user_duplicate_email_fails(self):
        """Test that updating to duplicate email fails."""
        # Create two users
        User.objects.create_user(
            username="user1",
            email="user1@example.com",
            password="password123",
        )
        user2 = User.objects.create_user(
            username="user2",
            email="user2@example.com",
            password="password123",
        )

        # Try to update user2's email to user1's email
        with pytest.raises(ValueError, match="already exists"):
            UserServices.update_user(
                user_id=user2.id,
                email="user1@example.com",
            )

    def test_update_nonexistent_user_fails(self):
        """Test that updating non-existent user fails."""
        with pytest.raises(ValueError, match="not found"):
            UserServices.update_user(
                user_id=99999,
                first_name="Test",
            )

    def test_delete_user_success(self):
        """Test successful user deletion."""
        user = User.objects.create_user(
            username="deleteme",
            email="delete@example.com",
            password="password123",
        )
        user_id = user.id

        # Test business logic - user should be hard deleted
        UserServices.delete_user(user_id=user_id)
        assert not User.objects.filter(id=user_id).exists()

    def test_delete_superuser_fails(self):
        """Test that deleting superuser fails."""
        user = User.objects.create_superuser(
            username="superuser",
            email="super@example.com",
            password="password123",
        )

        with pytest.raises(ValueError, match="Cannot delete superuser"):
            UserServices.delete_user(user_id=user.id)

    def test_delete_nonexistent_user_fails(self):
        """Test that deleting non-existent user fails."""
        with pytest.raises(ValueError, match="User not found"):
            UserServices.delete_user(user_id=99999)

    def test_delete_user_with_related_inquiries(self):
        """Test that deleting user with related inquiries works correctly."""
        from apps.inquiries.models import Inquiry

        # Create user and inquiry
        user = User.objects.create_user(
            username="manager_with_inquiries",
            email="manager@example.com",
            password="password123",
            user_type="manager",
        )

        inquiry = Inquiry.objects.create(
            client="Test Client",
            text="Test inquiry",
            sales_manager=user,
            status="pending",
        )
        inquiry_id = inquiry.id

        # Delete the user
        UserServices.delete_user(user_id=user.id)

        # User should be deleted
        assert not User.objects.filter(id=user.id).exists()

        # Inquiry should still exist but with sales_manager set to None
        inquiry_after_delete = Inquiry.objects.get(id=inquiry_id)
        assert inquiry_after_delete.sales_manager is None
        assert inquiry_after_delete.client == "Test Client"


@pytest.mark.django_db
class TestUserSelectors:
    """Test user data retrieval business logic."""

    @pytest.fixture
    def sample_users(self):
        """Create sample users for testing."""
        users = []
        users.append(
            User.objects.create_user(
                username="customer1",
                email="customer1@example.com",
                password="password123",
                user_type="customer",
                first_name="Customer",
                last_name="One",
            )
        )
        users.append(
            User.objects.create_user(
                username="manager1",
                email="manager1@example.com",
                password="password123",
                user_type="manager",
                first_name="Manager",
                last_name="One",
            )
        )
        users.append(
            User.objects.create_user(
                username="admin1",
                email="admin1@example.com",
                password="password123",
                user_type="admin",
                first_name="Admin",
                last_name="One",
                is_active=False,
            )
        )
        return users

    def test_search_users_by_username(self, sample_users):
        """Test searching users by username."""
        results = UserSelectors.search_users(query="customer", limit=10)

        usernames = [user.username for user in results]
        assert "customer1" in usernames
        assert "manager1" not in usernames

    def test_search_users_by_email(self, sample_users):
        """Test searching users by email."""
        results = UserSelectors.search_users(query="manager1@", limit=10)

        emails = [user.email for user in results]
        assert "manager1@example.com" in emails

    def test_get_user_profile_data(self, sample_users):
        """Test user profile data retrieval."""
        user = sample_users[0]  # customer1

        profile_data = UserSelectors.get_user_profile_data(user=user)

        assert profile_data["id"] == user.id
        assert profile_data["username"] == "customer1"
        assert profile_data["email"] == "customer1@example.com"
        assert profile_data["user_type"] == "customer"
        assert profile_data["is_active"] is True
        assert profile_data["first_name"] == "Customer"
        assert profile_data["last_name"] == "One"


@pytest.mark.django_db
class TestUserBusinessRules:
    """Test business rules enforcement in user management."""

    def test_user_type_validation(self):
        """Test that only valid user types are accepted."""
        valid_types = ["customer", "manager", "admin"]

        for user_type in valid_types:
            user = UserServices.create_user(
                username=f"test_{user_type}",
                email=f"{user_type}@example.com",
                password="password123",
                user_type=user_type,
            )
            assert user.user_type == user_type

    def test_invalid_user_type_rejected(self):
        """Test that invalid user types are rejected."""
        with pytest.raises(ValueError, match="Invalid user type"):
            UserServices.create_user(
                username="invalid",
                email="invalid@example.com",
                password="password123",
                user_type="invalid_type",
            )

    def test_email_business_logic(self):
        """Test email field business logic."""
        # Test that valid emails work
        user = UserServices.create_user(
            username="emailtest",
            email="valid@example.com",
            password="password123",
        )
        assert user.email == "valid@example.com"

    def test_username_uniqueness_case_sensitive(self):
        """Test that username uniqueness is case sensitive."""
        # Create user with lowercase username
        UserServices.create_user(
            username="testuser",
            email="test1@example.com",
            password="password123",
        )

        # Should be able to create user with different case
        user2 = UserServices.create_user(
            username="TestUser",
            email="test2@example.com",
            password="password123",
        )

        assert user2.username == "TestUser"

    def test_user_activation_status(self):
        """Test user activation/deactivation business logic."""
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )

        # User should be active by default
        assert user.is_active is True

        # Deactivate user
        updated_user = UserServices.update_user(
            user_id=user.id,
            is_active=False,
        )

        assert updated_user.is_active is False

    def test_create_user_all_user_types(self):
        """Test creating users with all valid user types."""
        user_types = ["customer", "manager", "admin"]

        for user_type in user_types:
            user = UserServices.create_user(
                username=f"test_{user_type}",
                email=f"{user_type}@test.com",
                password="password123",
                user_type=user_type,
            )
            assert user.user_type == user_type

    def test_update_user_telegram_fields(self):
        """Test updating telegram-related fields."""
        user = User.objects.create_user(
            username="telegramuser",
            email="telegram@example.com",
            password="password123",
        )

        updated_user = UserServices.update_user(
            user_id=user.id,
            telegram_id="987654321",
            telegram_username="telegramuser",
            telegram_access=True,
        )

        assert updated_user.telegram_id == "987654321"
        assert updated_user.telegram_username == "telegramuser"
        assert updated_user.telegram_access is True

    def test_create_user_with_telegram_fields(self):
        """Test creating user with all telegram fields."""
        user = UserServices.create_user(
            username="telegram_test",
            email="telegram_test@example.com",
            password="password123",
            telegram_id="123456789",
            telegram_username="telegram_test",
            telegram_access=True,
        )

        assert user.telegram_id == "123456789"
        assert user.telegram_username == "telegram_test"
        assert user.telegram_access is True

    def test_search_users_empty_query(self):
        """Test searching users with empty query returns all users."""
        User.objects.create_user(
            username="searchuser1",
            email="search1@example.com",
            password="password123",
        )
        User.objects.create_user(
            username="searchuser2",
            email="search2@example.com",
            password="password123",
        )

        results = UserSelectors.search_users(query="", limit=10)
        assert len(results) >= 2
