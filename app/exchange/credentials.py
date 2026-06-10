"""Demo (simulated) OKX API credentials - environment only, never stored.

Phase 5 safety rules enforced here:

* Credentials come ONLY from environment variables. They are never read from
  source, the database, the API, or a config file committed to the repo.
* The credential object never reveals its secret material in ``repr``/``str``,
  so it cannot leak through logs, tracebacks, or error messages.
* A logging filter (:func:`install_secret_redaction`) scrubs the exact secret
  values from every log record (message, args, and structured extras) as a
  defence-in-depth backstop.
* Loading fails closed: if any of the three demo variables is missing or empty,
  loading raises and the error text contains no secret material.

These are DEMO/simulated-trading credentials. They authorize no real-money
access; see ``app.exchange.okx_demo_endpoints`` for the hard demo-only
transport guarantees.
"""

from __future__ import annotations

import logging
import os
from typing import Mapping, Optional

# Environment variable names. Demo only - there is deliberately no production
# variant anywhere in this codebase.
ENV_API_KEY = "OKX_DEMO_API_KEY"
ENV_API_SECRET = "OKX_DEMO_API_SECRET"
ENV_API_PASSPHRASE = "OKX_DEMO_API_PASSPHRASE"

_REDACTION = "***REDACTED***"


class MissingDemoCredentialsError(RuntimeError):
    """Raised when demo credentials are absent or incomplete (fail closed).

    The message never includes any credential value.
    """


class DemoCredentials:
    """Holds demo API credentials without ever exposing them in text.

    The secret material is accessible through explicit properties (used only by
    the signer) but is excluded from ``repr``/``str`` and from equality output.
    Construct via :func:`load_demo_credentials`.
    """

    __slots__ = ("_api_key", "_secret", "_passphrase")

    def __init__(self, api_key: str, secret: str, passphrase: str) -> None:
        if not api_key or not secret or not passphrase:
            # Defensive: loaders validate first, but never allow an empty field.
            raise MissingDemoCredentialsError(
                "demo credentials must all be non-empty (none are shown)"
            )
        self._api_key = api_key
        self._secret = secret
        self._passphrase = passphrase

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def secret(self) -> str:
        return self._secret

    @property
    def passphrase(self) -> str:
        return self._passphrase

    def secret_values(self) -> tuple[str, ...]:
        """Return the raw secret strings (for the redaction filter only)."""
        return (self._api_key, self._secret, self._passphrase)

    def key_fingerprint(self) -> str:
        """A short, non-reversible hint for audit logs (not the key itself)."""
        import hashlib

        digest = hashlib.sha256(self._api_key.encode("utf-8")).hexdigest()
        return f"sha256:{digest[:8]}"

    def __repr__(self) -> str:  # never reveal secrets
        return f"DemoCredentials(api_key={_REDACTION}, fingerprint={self.key_fingerprint()})"

    __str__ = __repr__


def load_demo_credentials(
    env: Optional[Mapping[str, str]] = None,
) -> DemoCredentials:
    """Load demo credentials from the environment. Fail closed if incomplete.

    Args:
        env: optional mapping (defaults to ``os.environ``) so tests can inject
            fake values without touching the real environment.

    Raises:
        MissingDemoCredentialsError: if any of the three demo variables is
            missing or blank. The error never contains a credential value.
    """
    source = env if env is not None else os.environ
    api_key = (source.get(ENV_API_KEY) or "").strip()
    secret = (source.get(ENV_API_SECRET) or "").strip()
    passphrase = (source.get(ENV_API_PASSPHRASE) or "").strip()

    missing = [
        name
        for name, value in (
            (ENV_API_KEY, api_key),
            (ENV_API_SECRET, secret),
            (ENV_API_PASSPHRASE, passphrase),
        )
        if not value
    ]
    if missing:
        raise MissingDemoCredentialsError(
            "missing demo credential environment variables: "
            + ", ".join(missing)
            + " (no values are shown)"
        )
    return DemoCredentials(api_key=api_key, secret=secret, passphrase=passphrase)


def demo_credentials_available(env: Optional[Mapping[str, str]] = None) -> bool:
    """Return True only if all three demo variables are present and non-empty."""
    source = env if env is not None else os.environ
    return all(
        (source.get(name) or "").strip()
        for name in (ENV_API_KEY, ENV_API_SECRET, ENV_API_PASSPHRASE)
    )


def redact(text: str, secrets: tuple[str, ...]) -> str:
    """Replace every occurrence of each secret value with a redaction marker."""
    if not text:
        return text
    for secret in secrets:
        if secret:
            text = text.replace(secret, _REDACTION)
    return text


class SecretRedactingFilter(logging.Filter):
    """Logging filter that scrubs known secret values from every record.

    It rewrites the record message, positional args, and any string-valued
    structured extras so a stray ``logger.info(..., extra={...})`` can never
    emit a secret. High-entropy secret strings make exact substring replacement
    both safe (no false positives in practice) and aggressive.
    """

    # Standard LogRecord attributes we must not treat as "extras".
    _RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}

    def __init__(self, secrets: tuple[str, ...]) -> None:
        super().__init__()
        self._secrets = tuple(s for s in secrets if s)

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._secrets:
            return True
        if isinstance(record.msg, str):
            record.msg = redact(record.msg, self._secrets)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    key: (redact(value, self._secrets) if isinstance(value, str) else value)
                    for key, value in record.args.items()
                }
            else:
                record.args = tuple(
                    redact(value, self._secrets) if isinstance(value, str) else value
                    for value in record.args
                )
        for key, value in list(record.__dict__.items()):
            if key in self._RESERVED or key.startswith("_"):
                continue
            if isinstance(value, str):
                record.__dict__[key] = redact(value, self._secrets)
        return True


def install_secret_redaction(credentials: DemoCredentials) -> SecretRedactingFilter:
    """Attach a :class:`SecretRedactingFilter` to the root logger's handlers.

    Returns the installed filter so callers/tests can remove it later. Safe to
    call more than once; it does not stack duplicate filters with equal secrets.
    """
    filt = SecretRedactingFilter(credentials.secret_values())
    root = logging.getLogger()
    _attach_filter(root, filt)
    for handler in root.handlers:
        _attach_filter(handler, filt)
    return filt


def _attach_filter(target: logging.Logger | logging.Handler, filt: SecretRedactingFilter) -> None:
    existing = [
        f
        for f in target.filters
        if isinstance(f, SecretRedactingFilter) and f._secrets == filt._secrets
    ]
    if not existing:
        target.addFilter(filt)
