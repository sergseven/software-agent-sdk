"""Ask an ACP server what it offers (models, slash commands) before a conversation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from openhands.agent_server._secrets_exposure import get_config
from openhands.agent_server.config import Config
from openhands.agent_server.credential_binding import LocalVersionedCredentialBinding
from openhands.agent_server.persistence import get_secrets_store
from openhands.sdk.agent.acp_discovery import discover_acp_session
from openhands.sdk.agent.acp_file_credentials import CODEX_AUTH_SECRET_NAME
from openhands.sdk.agent.acp_models import ACPDiscovery
from openhands.sdk.credential import VersionedCredentialBinding
from openhands.sdk.logger import get_logger
from openhands.sdk.secret import SecretSource
from openhands.sdk.settings.model import ACPAgentSettings


logger = get_logger(__name__)

acp_router = APIRouter(prefix="/acp", tags=["ACP"])

_CACHE_TTL_SECONDS = 300.0
_MAX_CONCURRENT_DISCOVERIES = 2


class ACPDiscoveryRequest(BaseModel):
    agent_settings: ACPAgentSettings = Field(
        description=(
            "The ACP agent to ask. Only the launch fields are used; "
            "``acp_model``, MCP servers and agent context are ignored."
        ),
    )
    secrets: dict[str, SecretSource] = Field(
        default_factory=dict,
        description=(
            "Credentials for the server, in the same shape as a conversation "
            "start request's ``secrets`` (typically ``LookupSecret`` references "
            "to this server's stored secrets)."
        ),
    )
    working_dir: str | None = Field(
        default=None,
        description=(
            "Directory to open the throwaway session in, so project-level slash "
            "commands are listed. Omitted: an empty directory (models and "
            "user-level commands only)."
        ),
    )
    refresh: bool = Field(
        default=False, description="Ask the server again instead of reusing a result."
    )


@dataclass
class _DiscoveryCache:
    results: dict[str, tuple[float, ACPDiscovery]] = field(default_factory=dict)
    in_flight: dict[str, asyncio.Future[ACPDiscovery]] = field(default_factory=dict)
    slots: asyncio.Semaphore = field(
        default_factory=lambda: asyncio.Semaphore(_MAX_CONCURRENT_DISCOVERIES)
    )

    async def get(
        self,
        key: str,
        discover: Callable[[], Awaitable[ACPDiscovery]],
        *,
        refresh: bool,
    ) -> ACPDiscovery:
        cached = self.results.get(key)
        if not refresh and cached is not None and cached[0] > time.monotonic():
            return cached[1]
        pending = self.in_flight.get(key)
        if pending is None:
            pending = asyncio.ensure_future(self._run(key, discover))
            self.in_flight[key] = pending
        return await asyncio.shield(pending)

    async def _run(
        self, key: str, discover: Callable[[], Awaitable[ACPDiscovery]]
    ) -> ACPDiscovery:
        try:
            async with self.slots:
                result = await discover()
            if result.error is None:
                self.results[key] = (time.monotonic() + _CACHE_TTL_SECONDS, result)
            return result
        finally:
            self.in_flight.pop(key, None)


def _discovery_cache(request: Request) -> _DiscoveryCache:
    cache = getattr(request.app.state, "acp_discovery_cache", None)
    if cache is None:
        cache = _DiscoveryCache()
        request.app.state.acp_discovery_cache = cache
    return cache


def _resolve_secrets(secrets: Mapping[str, SecretSource]) -> dict[str, str]:
    values: dict[str, str] = {}
    for name, source in secrets.items():
        try:
            value = source.get_value()
        except Exception:
            logger.warning("Could not resolve secret %r for ACP discovery", name)
            continue
        if value is not None:
            values[name] = value
    return values


def _cache_key(
    settings: ACPAgentSettings,
    command: list[str],
    secrets: Mapping[str, str],
    working_dir: str | None,
) -> str:
    payload = {
        "working_dir": working_dir,
        "command": command,
        "args": list(settings.acp_args),
        "session_mode": settings.acp_session_mode,
        "isolate": settings.acp_isolate_data_dir,
        "file_secrets": [
            spec.model_dump(mode="json") for spec in settings.acp_file_secrets
        ],
        "secrets": sorted(secrets.items()),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _codex_bindings(
    settings: ACPAgentSettings, config: Config, secrets: dict[str, str]
) -> dict[str, VersionedCredentialBinding]:
    if settings.acp_server != "codex":
        return {}
    store = get_secrets_store(config)
    if store.get_secret(CODEX_AUTH_SECRET_NAME) is None:
        return {}
    # A stored ChatGPT login refreshes through the store, as in a conversation.
    secrets.pop(CODEX_AUTH_SECRET_NAME, None)
    return {
        CODEX_AUTH_SECRET_NAME: LocalVersionedCredentialBinding(
            store, CODEX_AUTH_SECRET_NAME
        )
    }


@acp_router.post("/discover", response_model=ACPDiscovery)
async def discover(body: ACPDiscoveryRequest, request: Request) -> ACPDiscovery:
    """Start the ACP server in a throwaway session and report what it offers.

    The server answers with its default model, the models it offers for the
    given credentials and the slash commands it advertises for
    ``working_dir``. The session is never prompted. A launch or authentication
    failure comes back in ``error`` rather than as an HTTP error.
    """
    config: Config = get_config(request)
    if config.conversation_runtime == "docker":
        raise HTTPException(
            status.HTTP_501_NOT_IMPLEMENTED,
            "ACP discovery runs only where conversations run in-process",
        )
    settings = body.agent_settings
    try:
        command = settings.resolve_acp_command()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if body.working_dir is not None and not Path(body.working_dir).is_dir():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"working_dir is not a directory: {body.working_dir}",
        )

    secrets = await asyncio.to_thread(_resolve_secrets, body.secrets)
    bindings = await asyncio.to_thread(_codex_bindings, settings, config, secrets)
    key = _cache_key(settings, command, secrets, body.working_dir)

    async def run() -> ACPDiscovery:
        config.conversations_path.mkdir(parents=True, exist_ok=True)
        return await asyncio.to_thread(
            discover_acp_session,
            settings,
            secrets=secrets,
            credential_bindings=bindings,
            # Shares the conversations' npx cache.
            work_root=config.conversations_path,
            working_dir=body.working_dir,
        )

    return await _discovery_cache(request).get(key, run, refresh=body.refresh)


@acp_router.post("/models", response_model=ACPDiscovery, deprecated=True)
async def discover_models(body: ACPDiscoveryRequest, request: Request) -> ACPDiscovery:
    """Deprecated alias of ``POST /api/acp/discover``.

    Deprecated since v1.56.0 and scheduled for removal in v1.61.0.
    """
    return await discover(body, request)
