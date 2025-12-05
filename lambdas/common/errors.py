from dataclasses import dataclass


@dataclass
class AppError(Exception):
    """Base application error."""
    message: str
    status: int = 500
    code: str = "INTERNAL_ERROR"
    
    def __str__(self) -> str:
        return self.message


class AuthError(AppError):
    """Authentication/authorization errors."""
    def __init__(self, message: str = "Unauthorized", status: int = 401):
        super().__init__(message=message, status=status, code="AUTH_ERROR")


class ValidationError(AppError):
    """Input validation errors."""
    def __init__(self, message: str = "Invalid input"):
        super().__init__(message=message, status=400, code="VALIDATION_ERROR")


class DownloadError(AppError):
    """Track download errors."""
    def __init__(self, message: str = "Download failed"):
        super().__init__(message=message, status=500, code="DOWNLOAD_ERROR")


class NotFoundError(AppError):
    """Resource not found errors."""
    def __init__(self, message: str = "Resource not found"):
        super().__init__(message=message, status=404, code="NOT_FOUND")
