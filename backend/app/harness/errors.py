from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ToolErrorCode(StrEnum):
    UNKNOWN_TOOL = "unknown_tool"
    INVALID_INPUT = "invalid_input"
    DOMAIN_INVALID = "domain_invalid"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    PERMISSION_DENIED = "permission_denied"
    CONFIRMATION_REQUIRED = "confirmation_required"

    USER_REJECTED = "user_rejected"
    INTERNAL = "internal"


@dataclass(frozen=True)
class ToolError:
    code: ToolErrorCode
    message: str
    details: dict[str, Any] | None = None


class HarnessError(Exception):
    code: ToolErrorCode = ToolErrorCode.INTERNAL

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class UnknownToolError(HarnessError):
    code = ToolErrorCode.UNKNOWN_TOOL


class InvalidToolInputError(HarnessError):
    code = ToolErrorCode.INVALID_INPUT


class PermissionDeniedError(HarnessError):
    code = ToolErrorCode.PERMISSION_DENIED


class ConfirmationRequiredError(HarnessError):
    code = ToolErrorCode.CONFIRMATION_REQUIRED


class UserRejectedError(HarnessError):
    code = ToolErrorCode.USER_REJECTED


class ToolExecutionError(HarnessError):
    def __init__(
        self,
        code: ToolErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details)
        self.code = code


class DuplicateToolError(Exception):
    pass
