from __future__ import annotations


class ProviderError(Exception):
    def __init__(
        self,
        *,
        code: str,
        provider: str,
        message: str,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.provider = provider
        self.message = message
        self.retryable = retryable

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "code": self.code,
            "provider": self.provider,
            "message": self.message,
            "retryable": self.retryable,
        }

    def __repr__(self) -> str:
        return (
            f"ProviderError(code={self.code!r}, provider={self.provider!r}, "
            f"message={self.message!r}, retryable={self.retryable!r})"
        )
