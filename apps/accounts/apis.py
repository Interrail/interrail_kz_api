from drf_spectacular.openapi import OpenApiParameter, OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api_config.pagination import (
    CustomPageNumberPagination,
    get_paginated_response,
)
from apps.api_config.utils import inline_serializer
from apps.authentication.authentication import CookieJWTAuthentication
from apps.core.permissions import IsAdminOnly, IsManagerOrAdmin

from .models import CustomUser
from .selectors import UserSelectors
from .services import UserServices


class UserListApiView(APIView):
    """
    List users
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class Pagination(CustomPageNumberPagination):
        page_size = 10
        max_page_size = 100

    class FilterSerializer(serializers.Serializer):
        id = serializers.IntegerField(required=False)
        email = serializers.CharField(required=False)
        username = serializers.CharField(required=False)
        first_name = serializers.CharField(required=False)
        last_name = serializers.CharField(required=False)
        user_type = serializers.ChoiceField(
            choices=CustomUser.USER_TYPES,
            required=False,
        )
        is_active = serializers.CharField(required=False)
        telegram_username = serializers.CharField(required=False)
        search = serializers.CharField(required=False)
        inquiry_related = serializers.BooleanField(required=False)

    class UserListOutputSerializer(serializers.Serializer):
        id = serializers.IntegerField(read_only=True)
        username = serializers.CharField(read_only=True)
        email = serializers.EmailField(read_only=True)
        first_name = serializers.CharField(read_only=True)
        last_name = serializers.CharField(read_only=True)
        user_type = serializers.CharField(read_only=True)
        user_type_display = serializers.CharField(read_only=True)
        telegram_id = serializers.CharField(read_only=True)
        telegram_username = serializers.CharField(read_only=True)
        telegram_access = serializers.BooleanField(read_only=True)
        last_login = serializers.DateTimeField(read_only=True)
        created_at = serializers.DateTimeField(read_only=True)
        updated_at = serializers.DateTimeField(read_only=True)

    @extend_schema(
        tags=["User Management"],
        summary="List Users",
        parameters=[
            OpenApiParameter(
                "limit", OpenApiTypes.INT, description="Items per page (default: 10)"
            ),
            OpenApiParameter(
                "offset",
                OpenApiTypes.INT,
                description="Number of items to skip (default: 0)",
            ),
            OpenApiParameter("id", OpenApiTypes.INT, description="Filter by user ID"),
            OpenApiParameter(
                "email", OpenApiTypes.STR, description="Filter by email (contains)"
            ),
            OpenApiParameter(
                "username",
                OpenApiTypes.STR,
                description="Filter by username (contains)",
            ),
            OpenApiParameter(
                "first_name",
                OpenApiTypes.STR,
                description="Filter by first name (contains)",
            ),
            OpenApiParameter(
                "last_name",
                OpenApiTypes.STR,
                description="Filter by last name (contains)",
            ),
            OpenApiParameter(
                "user_type", OpenApiTypes.STR, description="Filter by user type"
            ),
            OpenApiParameter(
                "is_active", OpenApiTypes.BOOL, description="Filter by active status"
            ),
            OpenApiParameter(
                "telegram_username",
                OpenApiTypes.STR,
                description="Filter by telegram username (contains)",
            ),
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                description="Search across username, email, names",
            ),
            OpenApiParameter(
                "inquiry_related",
                OpenApiTypes.BOOL,
                description="Filter managers who have created inquiries",
            ),
        ],
        responses={200: UserListOutputSerializer},
    )
    def get(self, request):
        # Validate filters
        filter_serializer = self.FilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)

        # Apply role-based filtering for user access
        filters = filter_serializer.validated_data
        if request.user.user_type != "admin":
            # Managers can only see themselves
            filters["id"] = request.user.id

        # Get filtered queryset
        queryset = UserSelectors.user_list(filters=filters)

        # Use pagination helper
        return get_paginated_response(
            pagination_class=self.Pagination,
            serializer_class=self.UserListOutputSerializer,
            queryset=queryset,
            request=request,
            view=self,
        )


class UserDetailApiView(APIView):
    """
    Retrieve user detail
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class UserDetailOutputSerializer(serializers.Serializer):
        id = serializers.IntegerField(read_only=True)
        username = serializers.CharField(read_only=True)
        email = serializers.EmailField(read_only=True)
        first_name = serializers.CharField(read_only=True)
        last_name = serializers.CharField(read_only=True)
        user_type = serializers.CharField(read_only=True)
        user_type_display = serializers.CharField(read_only=True)
        telegram_id = serializers.CharField(read_only=True)
        telegram_username = serializers.CharField(read_only=True)
        telegram_access = serializers.BooleanField(read_only=True)
        created_at = serializers.DateTimeField(read_only=True)
        updated_at = serializers.DateTimeField(read_only=True)

    @extend_schema(
        tags=["User Management"],
        summary="Get User Detail",
        responses={200: UserDetailOutputSerializer},
    )
    def get(self, request, user_id):
        try:
            # Security check: Managers can only view their own profile
            if request.user.user_type != "admin" and user_id != request.user.id:
                return Response(
                    {"message": "Access denied"}, status=status.HTTP_403_FORBIDDEN
                )

            data = UserSelectors.get_user_profile_data(
                user=UserSelectors.get_user_by_id(user_id=user_id)
            )

            return Response(
                self.UserDetailOutputSerializer(data).data, status=status.HTTP_200_OK
            )
        except CustomUser.DoesNotExist:
            return Response(
                {"message": "User not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except ValueError as e:
            return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class UserCreateApiView(APIView):
    """
    Create user
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class UserCreateSerializer(serializers.Serializer):
        username = serializers.CharField(max_length=150, required=True)
        email = serializers.EmailField(required=True)
        password = serializers.CharField(write_only=True, min_length=8, required=True)
        first_name = serializers.CharField(
            max_length=30, required=False, allow_blank=True
        )
        last_name = serializers.CharField(
            max_length=30, required=False, allow_blank=True
        )
        user_type = serializers.ChoiceField(
            choices=CustomUser.USER_TYPES,
            default="customer",
        )
        telegram_id = serializers.CharField(
            max_length=50, required=False, allow_blank=True
        )
        telegram_username = serializers.CharField(
            max_length=100, required=False, allow_blank=True
        )
        telegram_access = serializers.BooleanField(default=False)

    class UserCreateOutputSerializer(serializers.Serializer):
        id = serializers.IntegerField(read_only=True)
        username = serializers.CharField(read_only=True)
        email = serializers.EmailField(read_only=True)
        first_name = serializers.CharField(read_only=True)
        last_name = serializers.CharField(read_only=True)
        user_type = serializers.CharField(read_only=True)
        user_type_display = serializers.CharField(read_only=True)
        telegram_id = serializers.CharField(read_only=True)
        telegram_username = serializers.CharField(read_only=True)
        telegram_access = serializers.BooleanField(read_only=True)
        is_active = serializers.BooleanField(read_only=True)
        created_at = serializers.DateTimeField(read_only=True)
        updated_at = serializers.DateTimeField(read_only=True)

    @extend_schema(
        tags=["User Management"],
        summary="Create User",
        request=UserCreateSerializer,
        responses={201: UserCreateOutputSerializer},
    )
    def post(self, request):
        serializer = self.UserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            user = UserServices.create_user(**serializer.validated_data)
            data = UserSelectors.get_user_profile_data(user=user)

            return Response(
                self.UserCreateOutputSerializer(data).data,
                status=status.HTTP_201_CREATED,
            )

        except ValueError as e:
            return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class UserUpdateApiView(APIView):
    """
    Update user
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class UserUpdateSerializer(serializers.Serializer):
        username = serializers.CharField(max_length=150, required=False)
        email = serializers.EmailField(required=False)
        first_name = serializers.CharField(
            max_length=30, required=False, allow_blank=True
        )
        last_name = serializers.CharField(
            max_length=30, required=False, allow_blank=True
        )
        user_type = serializers.ChoiceField(
            choices=CustomUser.USER_TYPES,
            required=False,
        )
        telegram_id = serializers.CharField(
            max_length=50, required=False, allow_blank=True
        )
        telegram_username = serializers.CharField(
            max_length=100, required=False, allow_blank=True
        )
        password = serializers.CharField(write_only=True, min_length=8, required=False)
        telegram_access = serializers.BooleanField(required=False)
        is_active = serializers.BooleanField(required=False)

    class UserUpdateOutputSerializer(serializers.Serializer):
        id = serializers.IntegerField(read_only=True)
        username = serializers.CharField(read_only=True)
        email = serializers.EmailField(read_only=True)
        first_name = serializers.CharField(read_only=True)
        last_name = serializers.CharField(read_only=True)
        user_type = serializers.CharField(read_only=True)
        user_type_display = serializers.CharField(read_only=True)
        telegram_id = serializers.CharField(read_only=True)
        telegram_username = serializers.CharField(read_only=True)
        telegram_access = serializers.BooleanField(read_only=True)
        is_active = serializers.BooleanField(read_only=True)
        created_at = serializers.DateTimeField(read_only=True)
        updated_at = serializers.DateTimeField(read_only=True)

    @extend_schema(
        tags=["User Management"],
        summary="Update User",
        request=UserUpdateSerializer,
        responses={200: UserUpdateOutputSerializer},
    )
    def put(self, request, user_id):
        # Security check: Managers can only update their own profile
        if request.user.user_type != "admin" and user_id != request.user.id:
            return Response(
                {"message": "Access denied"}, status=status.HTTP_403_FORBIDDEN
            )

        serializer = self.UserUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            user = UserServices.update_user(
                user_id=user_id, **serializer.validated_data
            )
            data = UserSelectors.get_user_profile_data(user=user)

            return Response(
                self.UserUpdateOutputSerializer(data).data, status=status.HTTP_200_OK
            )

        except ValueError as e:
            return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except CustomUser.DoesNotExist:
            return Response(
                {"message": "User not found"}, status=status.HTTP_404_NOT_FOUND
            )


class UserDeleteApiView(APIView):
    """
    Delete user
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsAdminOnly]

    class DeleteSuccessSerializer(serializers.Serializer):
        message = serializers.CharField()

    @extend_schema(
        tags=["User Management"],
        summary="Delete User",
        responses={200: DeleteSuccessSerializer},
    )
    def delete(self, request, user_id):
        try:
            UserServices.delete_user(user_id=user_id)

            return Response(
                self.DeleteSuccessSerializer(
                    {"message": "User deleted successfully"}
                ).data,
                status=status.HTTP_200_OK,
            )

        except ValueError as e:
            return Response({"message": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except CustomUser.DoesNotExist:
            return Response(
                {"message": "User not found"}, status=status.HTTP_404_NOT_FOUND
            )


class UserStatsApiView(APIView):
    """
    Get user statistics
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class UserStatsOutputSerializer(serializers.Serializer):
        total_users = serializers.IntegerField()
        active_users = serializers.IntegerField()
        inactive_users = serializers.IntegerField()
        user_type_counts = inline_serializer(
            fields={
                "customer": serializers.IntegerField(),
                "manager": serializers.IntegerField(),
                "admin": serializers.IntegerField(),
            }
        )

    @extend_schema(
        tags=["User Management"],
        summary="Get User Statistics",
        responses={200: UserStatsOutputSerializer},
    )
    def get(self, request):
        # Security check: Only admins can see user statistics
        if request.user.user_type != "admin":
            return Response(
                {"message": "Access denied"}, status=status.HTTP_403_FORBIDDEN
            )

        data = UserSelectors.get_users_stats()

        return Response(
            self.UserStatsOutputSerializer(data).data, status=status.HTTP_200_OK
        )


class UserSearchApiView(APIView):
    """
    Search users
    """

    authentication_classes = [CookieJWTAuthentication]
    permission_classes = [IsManagerOrAdmin]

    class UserSearchOutputSerializer(serializers.Serializer):
        id = serializers.IntegerField(read_only=True)
        username = serializers.CharField(read_only=True)
        email = serializers.EmailField(read_only=True)
        first_name = serializers.CharField(read_only=True)
        last_name = serializers.CharField(read_only=True)
        user_type = serializers.CharField(read_only=True)
        user_type_display = serializers.CharField(read_only=True)

    @extend_schema(
        tags=["User Management"],
        summary="Search Users",
        parameters=[
            OpenApiParameter(
                "q", OpenApiTypes.STR, description="Search query", required=True
            ),
            OpenApiParameter(
                "limit", OpenApiTypes.INT, description="Maximum results (default: 10)"
            ),
        ],
        responses={200: UserSearchOutputSerializer(many=True)},
    )
    def get(self, request):
        query = request.query_params.get("q")
        if not query:
            return Response(
                {"message": "Search query is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Security check: Managers can only search for themselves
        if request.user.user_type != "admin":
            # Return only current user if query matches
            if (
                query.lower() in request.user.username.lower()
                or query.lower() in request.user.email.lower()
                or query.lower() in (request.user.first_name or "").lower()
                or query.lower() in (request.user.last_name or "").lower()
            ):
                user_data = UserSelectors.get_user_profile_data(user=request.user)
                return Response(
                    self.UserSearchOutputSerializer([user_data], many=True).data,
                    status=status.HTTP_200_OK,
                )
            else:
                # No matches for non-admin users
                return Response([], status=status.HTTP_200_OK)

        limit = int(request.query_params.get("limit", 10))
        users = UserSelectors.search_users(query=query, limit=limit)

        # Convert queryset to list and get formatted data
        users_data = []
        for user in users:
            user_data = UserSelectors.get_user_profile_data(user=user)
            users_data.append(user_data)

        return Response(
            self.UserSearchOutputSerializer(users_data, many=True).data,
            status=status.HTTP_200_OK,
        )
