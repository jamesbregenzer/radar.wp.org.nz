#!/usr/bin/env python3
"""Runtime placement guard for unattended WordPress source acquisition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import platform
import re
from pathlib import Path
from typing import Any, Mapping

CAPABILITY = "wordpress.trac.raw-acquisition"
DEFAULT_CANONICAL_PROVIDER = "thor"
ERROR_CODE = "UNATTENDED_SOURCE_ACQUISITION_WRONG_HOST"
ROOT = Path(__file__).resolve().parents[1]
CAPABILITY_REGISTRY = ROOT / "config" / "source-acquisition-capabilities.json"


class PlacementError(RuntimeError):
    """Raised when source acquisition is invoked on a noncanonical provider."""

    def __init__(self, code: str = ERROR_CODE, *, placement: "Placement") -> None:
        super().__init__(code)
        self.code = code
        self.placement = placement


@dataclass(frozen=True)
class Placement:
    capability: str
    required_provider: str
    provider: str
    host: str
    unattended: bool
    interactive_canary: bool

    @property
    def accepted(self) -> bool:
        return self.provider == self.required_provider and self.unattended

    @property
    def status(self) -> str:
        if self.accepted:
            return "accepted"
        if self.interactive_canary:
            return "diagnostic-canary"
        return "wrong-host"

    def public_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "requiredProvider": self.required_provider,
            "provider": self.provider,
            "host": self.host,
            "unattended": self.unattended,
            "interactiveCanary": self.interactive_canary,
            "status": self.status,
        }


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_provider(value: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9.-]+", "-", (value or "").strip().lower()).strip("-")
    return normalized or "unknown"


def canonical_provider() -> str:
    try:
        registry = json.loads(CAPABILITY_REGISTRY.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_CANONICAL_PROVIDER
    for capability in registry.get("capabilities", []):
        if capability.get("id") == CAPABILITY:
            return normalize_provider(capability.get("canonicalProvider"))
    return DEFAULT_CANONICAL_PROVIDER


def _is_provider(value: str, provider: str) -> bool:
    return value == provider or value.startswith(f"{provider}.")


def resolve_placement(
    *,
    env: Mapping[str, str] | None = None,
    hostname: str | None = None,
    interactive_canary: bool = False,
) -> Placement:
    values = env or os.environ
    required_provider = canonical_provider()
    explicit_provider = values.get("RADAR_ACQUISITION_PROVIDER") or values.get("RADAR_EXECUTION_HOST")
    observed_host = normalize_provider(hostname or platform.node())
    provider = normalize_provider(explicit_provider) if explicit_provider else (
        required_provider if _is_provider(observed_host, required_provider) else "noncanonical-interactive"
    )
    is_required_provider = _is_provider(provider, required_provider)
    return Placement(
        capability=CAPABILITY,
        required_provider=required_provider,
        provider=required_provider if is_required_provider else provider,
        host=required_provider if is_required_provider else "noncanonical-interactive",
        unattended=is_required_provider,
        interactive_canary=interactive_canary,
    )


def require_trac_acquisition_placement(
    *,
    allow_interactive_canary: bool = False,
    env: Mapping[str, str] | None = None,
    hostname: str | None = None,
) -> Placement:
    values = env or os.environ
    canary = allow_interactive_canary or values.get("RADAR_ALLOW_INTERACTIVE_ACQUISITION_CANARY") == "1"
    placement = resolve_placement(env=values, hostname=hostname, interactive_canary=canary)
    if placement.accepted or placement.interactive_canary:
        return placement
    raise PlacementError(ERROR_CODE, placement=placement)


def receipt_execution_metadata(
    *,
    started_at: str | None,
    completed_at: str | None,
    placement: Placement | None = None,
    upload_status: str = "pending-repository-publication",
    readback_status: str = "pending-repository-publication",
    next_scheduled_at: str | None = None,
    failure_reason: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any] | None:
    values = env or os.environ
    resolved = placement
    if resolved is None:
        provider = values.get("RADAR_ACQUISITION_EXECUTION_PROVIDER")
        if not provider:
            return None
        resolved = Placement(
            capability=values.get("RADAR_ACQUISITION_CAPABILITY", CAPABILITY),
            required_provider=canonical_provider(),
            provider=normalize_provider(provider),
            host=values.get("RADAR_ACQUISITION_EXECUTION_HOST", normalize_provider(provider)),
            unattended=values.get("RADAR_ACQUISITION_UNATTENDED", "false").lower() == "true",
            interactive_canary=values.get("RADAR_ACQUISITION_INTERACTIVE_CANARY", "false").lower() == "true",
        )
    return {
        **resolved.public_dict(),
        "startedAt": started_at,
        "completedAt": completed_at,
        "uploadStatus": upload_status,
        "readbackStatus": readback_status,
        "nextScheduledAcquisition": next_scheduled_at,
        "failureReason": failure_reason,
    }


def placement_environment(placement: Placement, *, started_at: str) -> dict[str, str]:
    return {
        "RADAR_ACQUISITION_CAPABILITY": placement.capability,
        "RADAR_ACQUISITION_EXECUTION_PROVIDER": placement.provider,
        "RADAR_ACQUISITION_EXECUTION_HOST": placement.host,
        "RADAR_ACQUISITION_UNATTENDED": "true" if placement.unattended else "false",
        "RADAR_ACQUISITION_INTERACTIVE_CANARY": "true" if placement.interactive_canary else "false",
        "RADAR_ACQUISITION_STARTED_AT": started_at,
    }
