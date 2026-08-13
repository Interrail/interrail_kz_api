from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.views import exception_handler as drf_exception_handler


def exception_handler(exc, context):
    """Report model validation as 400 instead of 500.

    Services call full_clean() before saving, which raises Django's
    ValidationError. DRF does not recognise it, so every such failure — a file
    over the size limit, a disallowed extension — surfaced as a server error
    with a traceback instead of telling the caller what was wrong. Six call
    sites do this; translating it once here covers all of them and anything
    added later.
    """
    if isinstance(exc, DjangoValidationError):
        detail = (
            exc.message_dict
            if hasattr(exc, "message_dict")
            else {"detail": exc.messages}
        )
        exc = DRFValidationError(detail=detail)

    return drf_exception_handler(exc, context)
