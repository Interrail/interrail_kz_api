# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Django 5.2.4 REST API project for IK with JWT authentication. The project follows Django Styleguide architecture patterns with services/selectors and uses PostgreSQL as the database.

## Architecture

- **Framework**: Django 5.2.4 with Django REST Framework
- **Authentication**: JWT using djangorestframework-simplejwt
- **Database**: PostgreSQL (configured via environment variables)
- **Environment Management**: django-environ for configuration
- **API Documentation**: drf-spectacular (Swagger/OpenAPI)
- **Architecture Pattern**: Django Styleguide (Services/Selectors pattern)
- **Project Structure**: Apps organized under `apps/` directory

## Key Configuration

- **Settings**: `interrail_kz_api/settings.py` uses django-environ for environment-based configuration
- **Environment**: `.env` file contains database credentials and Django settings
- **Authentication**: JWT with custom claims (user_type, telegram_id)
- **API Documentation**: Available at `/api/docs/` (Swagger) and `/api/redoc/` (ReDoc)
- **Apps**: Custom apps are located in `apps/` directory
- **User Model**: CustomUser with user types (customer, manager, admin)

## Environment Variables

The project uses the following environment variables (defined in `.env`):

- `SECRET_KEY`: Django secret key (also used for JWT signing)
- `DEBUG`: Debug mode (True/False)
- `ALLOWED_HOSTS`: Comma-separated list of allowed hosts
- `DB_NAME`: PostgreSQL database name
- `DB_USER`: PostgreSQL username
- `DB_PASSWORD`: PostgreSQL password
- `DB_HOST`: PostgreSQL host (default: localhost)
- `DB_PORT`: PostgreSQL port (default: 5432)

## API Endpoints

### Authentication Endpoints (`/api/auth/`)
- `POST /api/auth/login/` - User login with JWT tokens
- `POST /api/auth/register/` - User registration
- `POST /api/auth/verify-token/` - Verify JWT token validity
- `POST /api/auth/refresh/` - Refresh JWT access token
- `POST /api/auth/logout/` - Logout (blacklist refresh token)
- `GET /api/auth/profile/` - Get current user profile and permissions
- `POST /api/auth/change-password/` - Change user password

### API Documentation
- `/api/docs/` - Swagger UI documentation
- `/api/redoc/` - ReDoc documentation
- `/api/schema/` - OpenAPI schema

All APIs are documented with Swagger decorators including:
- Operation descriptions and summaries
- Request/response examples
- Tagged endpoints (Authentication, User Profile)
- Proper error response codes

## Development Commands

### Django Management Commands
```bash
# Run development server
python manage.py runserver

# Create and apply migrations
python manage.py makemigrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run tests
python manage.py test

# Collect static files
python manage.py collectstatic

# Django shell
python manage.py shell
```

### Database Management
```bash
# Create migrations for specific app
python manage.py makemigrations accounts
python manage.py makemigrations authentication

# Apply migrations
python manage.py migrate

# Show migration status
python manage.py showmigrations
```

## Required Dependencies

Install the following packages:
```bash
pip install django-environ psycopg2-binary djangorestframework djangorestframework-simplejwt drf-spectacular
```

## Project Structure and Patterns

### Apps Structure
```
apps/
├── accounts/          # User management
│   ├── models.py      # CustomUser model
│   ├── services.py    # User business logic (future)
│   └── selectors.py   # User data queries (future)
│
└── authentication/    # JWT authentication
    ├── apis.py        # API views with embedded serializers
    ├── services.py    # Authentication business logic
    ├── selectors.py   # Authentication data queries
    └── urls.py        # Authentication URL patterns
```

### Architecture Patterns

The project follows **Django Styleguide** patterns:

1. **Services**: Handle business logic, database writes, external API calls
   - Located in `services.py` files
   - Class-based with static methods
   - Handle complex operations and validations

2. **Selectors**: Handle data retrieval, complex queries, data formatting
   - Located in `selectors.py` files
   - Class-based with static methods
   - Return formatted data for APIs

3. **APIs**: Handle HTTP requests/responses only
   - Located in `apis.py` files
   - Serializers embedded as inner classes
   - Call services for business logic
   - Call selectors for data retrieval

### User Types and Permissions

The CustomUser model supports three user types:
- **customer**: Can book tickets
- **manager**: Can view users, manage routes, book tickets
- **admin**: Full access to all features

### JWT Configuration

- **Access Token**: 60 minutes lifetime
- **Refresh Token**: 7 days lifetime
- **Token Rotation**: Enabled for security
- **Blacklisting**: Enabled for logout functionality
- **Custom Claims**: user_type, telegram_id included in tokens

## Pre-Commit Workflow

The project uses comprehensive pre-commit checks to ensure code quality. **Always run these checks before committing:**

### Automated Checks (on commit/push)

```bash
# These run automatically when you commit/push
git add .
git commit -m "Your message"  # Triggers pre-commit hooks
git push                      # Triggers pre-push tests
```

### Manual Check Scripts

```bash
# Quick essential checks (recommended before every commit)
./scripts/quick-check.sh

# Full comprehensive checks (recommended before major commits)
./scripts/pre-commit-full.sh
```

### Pre-commit Hooks Include:

1. **Code Quality**:
   - Black code formatting
   - Ruff linting (replaces isort, flake8, pyupgrade)
   - Trailing whitespace and file ending fixes

2. **Security & Django**:
   - Bandit security analysis
   - Django system checks
   - Migration checks

3. **Testing**:
   - Test collection verification
   - Full test suite (on pre-push)

### Pre-commit Commands

```bash
# Install pre-commit hooks
pre-commit install
pre-commit install --hook-type pre-push

# Run hooks manually
pre-commit run --all-files
pre-commit run --files <file1> <file2>

# Update hook versions
pre-commit autoupdate
```

## Important Notes

- **NEVER commit without running pre-commit checks**
- Ensure PostgreSQL is running and accessible with the credentials in `.env`
- The `.env` file contains sensitive information and should not be committed to version control
- JWT tokens include custom claims for user_type and telegram_id
- All APIs follow consistent response format with success/error structure
- Swagger documentation is automatically generated from API decorators
- The project uses class-based services and selectors for better organization
