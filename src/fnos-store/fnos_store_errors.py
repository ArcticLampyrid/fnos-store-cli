"""Stable exit codes and user-facing errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


EXIT_CODES = {
    "http_error": 1,
    "not_found": 2,
    "not_available": 3,
    "no_download": 4,
    "invalid_params": 5,
    "auth_failed": 6,
    "rate_limited": 7,
    "timeout": 8,
    "tls_error": 9,
    "decrypt_failed": 10,
}

UPSTREAM_CODES = {
    -1: ("invalid_params", "The store rejected the request parameters."),
    -6: ("not_found", "The appName does not exist in the selected catalog."),
    -7: ("not_available", "No package matches the selected platform and fnOS version."),
}


@dataclass
class StoreError(Exception):
    """An error with a stable code and a short message for CLI users."""

    code: str
    message: str
    upstream_code: int | None = None
    http_status: int | None = None
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)

    @property
    def exit_code(self) -> int:
        return EXIT_CODES.get(self.code, 1)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class RetryableResponse(Exception):
    """Internal marker used by tenacity for HTTP 429 and 5xx responses."""

    def __init__(self, response: Any) -> None:
        self.response = response
        super().__init__(f"retryable HTTP response: {response.status_code}")
