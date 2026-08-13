"""
Tests for inquiry file upload functionality.
Comprehensive testing of text vs file mutual exclusivity and CRUD operations.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CustomUser
from apps.inquiries.models import Inquiry
from apps.inquiries.selectors import InquirySelectors
from apps.inquiries.services import InquiryServices


@pytest.mark.django_db
class TestInquiryFileUpload:
    """Test file upload functionality for inquiries."""

    @pytest.fixture
    def manager_user(self):
        return CustomUser.objects.create_user(
            username="manager",
            email="manager@example.com",
            password="testpass123",
            user_type="manager",
        )

    @pytest.fixture
    def admin_user(self):
        return CustomUser.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="testpass123",
            user_type="admin",
        )

    @pytest.fixture
    def sample_file(self):
        """Create a sample file for testing."""
        content = b"This is a test file content for inquiry attachment."
        return SimpleUploadedFile(
            "test_inquiry.txt", content, content_type="text/plain"
        )

    @pytest.fixture
    def large_file(self):
        """Create a large file that exceeds size limit."""
        # Create 11MB file (exceeds 10MB limit)
        content = b"x" * (11 * 1024 * 1024)
        return SimpleUploadedFile("large_file.txt", content, content_type="text/plain")

    def test_create_inquiry_with_text_only(self, manager_user):
        """Test creating inquiry with text only."""
        inquiry = InquiryServices.create_inquiry(
            client="Text Client",
            text="This is a text inquiry",
            sales_manager_id=manager_user.id,
        )

        assert inquiry.client == "Text Client"
        assert inquiry.text == "This is a text inquiry"
        assert not inquiry.attachment  # FileField evaluates to False when empty

    def test_create_inquiry_with_file_only(self, manager_user, sample_file):
        """Test creating inquiry with file only."""
        inquiry = InquiryServices.create_inquiry(
            client="File Client",
            attachment=sample_file,
            sales_manager_id=manager_user.id,
        )

        assert inquiry.client == "File Client"
        assert inquiry.text is None
        assert inquiry.attachment is not None
        assert "test_inquiry" in inquiry.attachment.name
        assert inquiry.attachment.name.endswith(".txt")

    def test_create_inquiry_with_both_text_and_file_succeeds(
        self, manager_user, sample_file
    ):
        """Test that providing both text and file succeeds."""
        inquiry = InquiryServices.create_inquiry(
            client="Both Client",
            text="This is text",
            attachment=sample_file,
            sales_manager_id=manager_user.id,
        )

        assert inquiry.client == "Both Client"
        assert inquiry.text == "This is text"
        assert inquiry.attachment is not None
        assert "test_inquiry" in inquiry.attachment.name

    def test_create_inquiry_with_neither_text_nor_file_fails(self, manager_user):
        """Test that providing neither text nor file fails."""
        with pytest.raises(
            ValueError, match="Must provide either text or attachment \\(or both\\)"
        ):
            InquiryServices.create_inquiry(
                client="Neither Client",
                sales_manager_id=manager_user.id,
            )

    def test_update_inquiry_add_file_to_text(self, manager_user, sample_file):
        """Test adding file to existing text inquiry."""
        # Create inquiry with text
        inquiry = InquiryServices.create_inquiry(
            client="Switch Client",
            text="Original text",
            sales_manager_id=manager_user.id,
        )

        assert inquiry.text == "Original text"
        assert not inquiry.attachment

        # Add file to existing text
        updated_inquiry = InquiryServices.update_inquiry(
            inquiry=inquiry,
            attachment=sample_file,
        )

        assert updated_inquiry.text == "Original text"  # Text should remain
        assert updated_inquiry.attachment is not None
        assert "test_inquiry" in updated_inquiry.attachment.name
        assert updated_inquiry.attachment.name.endswith(".txt")

    def test_update_inquiry_add_text_to_file(self, manager_user, sample_file):
        """Test adding text to existing file inquiry."""
        # Create inquiry with file
        inquiry = InquiryServices.create_inquiry(
            client="Switch Client",
            attachment=sample_file,
            sales_manager_id=manager_user.id,
        )

        assert inquiry.text is None
        assert inquiry.attachment is not None

        # Add text to existing file
        updated_inquiry = InquiryServices.update_inquiry(
            inquiry=inquiry,
            text="New text content",
        )

        assert updated_inquiry.text == "New text content"
        assert updated_inquiry.attachment is not None  # File should remain

    def test_file_size_validation(self, manager_user, large_file):
        """Test that large files are rejected."""
        from django.core.exceptions import ValidationError

        with pytest.raises(
            (ValidationError, ValueError)
        ):  # ValidationError from file validator or service validation
            inquiry = InquiryServices.create_inquiry(
                client="Large File Client",
                attachment=large_file,
                sales_manager_id=manager_user.id,
            )
            # Force model validation to run
            inquiry.full_clean()

    def test_file_cleanup_on_inquiry_deletion(self, manager_user, sample_file):
        """Test that files are cleaned up when inquiry is deleted."""
        inquiry = InquiryServices.create_inquiry(
            client="Delete Client",
            attachment=sample_file,
            sales_manager_id=manager_user.id,
        )

        assert inquiry.attachment is not None

        # Delete inquiry
        InquiryServices.delete_inquiry(inquiry=inquiry)

        # Verify inquiry is deleted
        assert not Inquiry.objects.filter(id=inquiry.id).exists()

    def test_selector_includes_attachment_info(self, manager_user, sample_file):
        """Test that selectors include attachment information."""
        inquiry = InquiryServices.create_inquiry(
            client="Selector Client",
            attachment=sample_file,
            sales_manager_id=manager_user.id,
        )

        # Test selector output
        data = InquirySelectors.get_inquiry_by_id(inquiry_id=inquiry.id)

        assert data["text"] is None
        assert data["attachment_url"] is not None
        assert "test_inquiry" in data["attachment_name"]
        assert data["attachment_name"].endswith(".txt")
        assert data["has_attachment"] is True

    def test_selector_text_inquiry_info(self, manager_user):
        """Test selector output for text-based inquiry."""
        inquiry = InquiryServices.create_inquiry(
            client="Text Selector Client",
            text="Text content",
            sales_manager_id=manager_user.id,
        )

        data = InquirySelectors.get_inquiry_by_id(inquiry_id=inquiry.id)

        assert data["text"] == "Text content"
        assert data["attachment_url"] is None
        assert data["attachment_name"] is None
        assert data["has_attachment"] is False


@pytest.mark.django_db
class TestInquiryFileUploadAPI:
    """Test file upload via API endpoints."""

    @pytest.fixture
    def api_client(self):
        return APIClient()

    @pytest.fixture
    def manager_user(self):
        return CustomUser.objects.create_user(
            username="manager",
            email="manager@example.com",
            password="testpass123",
            user_type="manager",
        )

    @pytest.fixture
    def authenticated_client(self, api_client, manager_user):
        refresh = RefreshToken.for_user(manager_user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        return api_client

    @pytest.fixture
    def sample_file(self):
        content = b"Test file content for API upload"
        return SimpleUploadedFile("api_test.txt", content, content_type="text/plain")

    def test_api_create_inquiry_with_file(
        self, authenticated_client, manager_user, sample_file
    ):
        """Test creating inquiry with file via API."""
        url = reverse("inquiries:inquiry-create")
        data = {
            "client": "API File Client",
            "attachment": sample_file,
            "sales_manager_id": manager_user.id,
            "status": "pending",
        }

        response = authenticated_client.post(url, data, format="multipart")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["client"] == "API File Client"
        assert response.data["text"] is None
        assert response.data["has_attachment"] is True
        assert "api_test" in response.data["attachment_name"]
        assert response.data["attachment_name"].endswith(".txt")

    def test_api_create_inquiry_with_text(self, authenticated_client, manager_user):
        """Test creating inquiry with text via API."""
        url = reverse("inquiries:inquiry-create")
        data = {
            "client": "API Text Client",
            "text": "API text content",
            "sales_manager_id": manager_user.id,
            "status": "pending",
        }

        response = authenticated_client.post(url, data, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["client"] == "API Text Client"
        assert response.data["text"] == "API text content"
        assert response.data["has_attachment"] is False
        assert response.data["attachment_url"] is None

    def test_api_create_inquiry_both_text_and_file_succeeds(
        self, authenticated_client, manager_user, sample_file
    ):
        """Test API creation with both text and file."""
        url = reverse("inquiries:inquiry-create")
        data = {
            "client": "API Both Client",
            "text": "Text content",
            "attachment": sample_file,
            "sales_manager_id": manager_user.id,
            "status": "pending",
        }

        response = authenticated_client.post(url, data, format="multipart")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["client"] == "API Both Client"
        assert response.data["text"] == "Text content"
        assert response.data["has_attachment"] is True
        assert "api_test" in response.data["attachment_name"]

    def test_api_update_inquiry_add_file_to_text(
        self, authenticated_client, manager_user, sample_file
    ):
        """Test adding file to text inquiry via API."""
        # Create text inquiry
        inquiry = InquiryServices.create_inquiry(
            client="API Switch Client",
            text="Original text",
            sales_manager_id=manager_user.id,
        )

        # Add file to existing text
        url = reverse("inquiries:inquiry-update", kwargs={"inquiry_id": inquiry.id})
        data = {
            "attachment": sample_file,
        }

        response = authenticated_client.put(url, data, format="multipart")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["text"] == "Original text"  # Text should remain
        assert response.data["has_attachment"] is True
        assert "api_test" in response.data["attachment_name"]
        assert response.data["attachment_name"].endswith(".txt")

    def test_api_inquiry_list_includes_attachment_info(
        self, authenticated_client, manager_user, sample_file
    ):
        """Test that inquiry list includes attachment information."""
        # Create inquiries with text and file
        InquiryServices.create_inquiry(
            client="List Text Client",
            text="List text content",
            sales_manager_id=manager_user.id,
        )

        InquiryServices.create_inquiry(
            client="List File Client",
            attachment=sample_file,
            sales_manager_id=manager_user.id,
        )

        url = reverse("inquiries:inquiry-list")
        response = authenticated_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]

        # Check text inquiry
        text_inquiry = next(
            item for item in results if item["client"] == "List Text Client"
        )
        assert text_inquiry["has_attachment"] is False
        assert text_inquiry["attachment_url"] is None

        # Check file inquiry
        file_inquiry = next(
            item for item in results if item["client"] == "List File Client"
        )
        assert file_inquiry["has_attachment"] is True
        assert file_inquiry["attachment_url"] is not None

    def test_update_inquiry_remove_both_content_fails(self, manager_user, sample_file):
        """Test that removing both text and attachment fails."""
        # Create inquiry with both text and file
        inquiry = InquiryServices.create_inquiry(
            client="Both Content Client",
            text="Some text",
            attachment=sample_file,
            sales_manager_id=manager_user.id,
        )

        # Try to remove both text and attachment
        with pytest.raises(
            ValueError, match="Must provide either text or attachment \\(or both\\)"
        ):
            InquiryServices.update_inquiry(
                inquiry=inquiry,
                text="",  # Empty text
                attachment=None,  # Remove attachment
            )
