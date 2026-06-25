from __future__ import annotations

import os


class MissingCredential(RuntimeError):
    """A required credential was not found in the environment."""


def require_secret(name: str) -> str:
    """Read a secret from the environment by variable name, or raise MissingCredential.

    The one place credentials enter Gather. Secrets live ONLY in the environment, never in
    source, never in a config file Gather reads, never in an Item or its receipt. The value is
    never logged and never appears in an error: the raised message names the variable that is
    missing, not any value. An adapter that needs auth calls this and passes the result in a
    request header (see gather.api), so the secret never reaches a URL, a receipt, or the disk.
    """
    value = os.environ.get(name)
    if not value or not value.strip():
        raise MissingCredential(f"missing required credential in environment: {name}")
    if "\r" in value or "\n" in value:
        # a stray newline (e.g. from `export TOKEN=$(cat file)`) would corrupt or inject a header
        raise MissingCredential(f"credential in environment variable {name} contains a newline")
    return value


def has_secret(name: str) -> bool:
    """True if the named credential is present and non-empty (without revealing it)."""
    return bool(os.environ.get(name))
