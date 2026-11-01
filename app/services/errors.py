class BusinessError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(BusinessError):
    status_code = 404


class ConflictError(BusinessError):
    status_code = 409


class ForbiddenError(BusinessError):
    status_code = 403
