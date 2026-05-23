"""CLI input validation helpers."""

from __future__ import annotations

import ipaddress
import os
import socket

import click


class NonLoopbackHostError(click.BadParameter):
    """Raised when a service host is not loopback-only."""

    def __init__(self) -> None:
        super().__init__("must resolve to a loopback address")


class NonEmptyStringError(click.BadParameter):
    """Raised when an option value is empty after trimming whitespace."""

    def __init__(self) -> None:
        super().__init__("must not be empty")


class MissingRunJobEnvironmentError(click.UsageError):
    """Raised when internal run-job configuration is missing."""

    def __init__(self, env_name: str) -> None:
        super().__init__(f"{env_name} is required")


def _require_loopback_host(host: str) -> str:
    if _is_loopback_host(host):
        return host
    raise NonLoopbackHostError()


def _require_non_empty(value: str) -> str:
    stripped = value.strip()
    if stripped:
        return stripped
    raise NonEmptyStringError()


def _optional_non_empty(value: str | None) -> str | None:
    return None if value is None else _require_non_empty(value)


def _run_job_value(option_value: str | None, env_name: str) -> str:
    value = option_value if option_value is not None else os.environ.get(env_name)
    if value is None:
        raise MissingRunJobEnvironmentError(env_name)
    return _require_non_empty(value)


def _is_loopback_host(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass

    try:
        addresses = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False

    return bool(addresses) and all(ipaddress.ip_address(address[4][0]).is_loopback for address in addresses)
