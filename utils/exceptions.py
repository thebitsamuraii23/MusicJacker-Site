class ServiceError(Exception):
    """Base exception for service layer errors."""


class NotFoundError(ServiceError):
    pass


class ValidationError(ServiceError):
    pass


class ExternalServiceError(ServiceError):
    pass


class StorageError(ServiceError):
    pass
