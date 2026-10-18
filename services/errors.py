"""Only these deliberately authored messages may be shown directly to users."""


class ApplicationError(Exception):
    pass


class UserError(ApplicationError, ValueError):
    pass


class SourceValidationError(UserError):
    pass


class BusyError(UserError):
    pass


def public_error(exc: Exception) -> str:
    if isinstance(exc, ApplicationError):
        return str(exc)
    return "Operation could not be completed. Refresh the tickets and check source access, configuration, and service availability."
