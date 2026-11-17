from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, Field


class RuntimeMode(StrEnum):
    MOCK = "mock"
    HYBRID = "hybrid"
    PRODUCTION = "production"


class RunStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    PARTIAL_FAILED = "PARTIAL_FAILED"
    FAILED = "FAILED"


class ProductionGateError(RuntimeError):
    """Raised when production mode detects mock adapters, missing certs, or unverified QA."""


class PollingDeadlineExceededError(TimeoutError):
    """Raised when upstream job polling exceeds its hard wall-clock deadline."""


class BudgetOverrunError(RuntimeError):
    """Raised when accumulated run spend exceeds the configured ceiling."""


class ServiceAdapterSpec(BaseModel):
    name: str
    is_mock: bool = False
    endpoint_url: str | None = None
    verified_live: bool = False


class RunExecutionPolicy(BaseModel):
    mode: RuntimeMode = RuntimeMode.MOCK
    max_budget_usd: float = Field(gt=0.0, default=5.0)
    max_poll_seconds: float = Field(gt=0.0, default=180.0)
    poll_interval_seconds: float = Field(gt=0.0, default=1.0)
    require_c2pa_signing: bool = False
    c2pa_cert_configured: bool = False


class RunOutcome(BaseModel):
    status: RunStatus
    mode: RuntimeMode
    completed_shots: int
    total_shots: int
    spent_usd: float
    error_code: str | None = None
    error_detail: str | None = None


def enforce_production_gate(
    policy: RunExecutionPolicy,
    adapters: list[ServiceAdapterSpec],
) -> None:
    """Block unverified or mock adapters from ever running or approving output in production mode."""
    if policy.mode != RuntimeMode.PRODUCTION:
        return

    mock_names = [a.name for a in adapters if a.is_mock]
    if mock_names:
        raise ProductionGateError(f"Production mode forbids mock/stub adapters: {', '.join(mock_names)}")

    unverified = [a.name for a in adapters if not a.verified_live or not a.endpoint_url]
    if unverified:
        raise ProductionGateError(f"Production mode requires live-verified endpoints for: {', '.join(unverified)}")

    if policy.require_c2pa_signing and not policy.c2pa_cert_configured:
        raise ProductionGateError("Production mode requires C2PA_CERT_PATH and C2PA_KEY_PATH when signing is enabled.")


def check_budget_ceiling(spent_usd: float, max_budget_usd: float) -> None:
    """Fail fast if run expenditure crosses the hard budget ceiling."""
    if spent_usd > max_budget_usd:
        raise BudgetOverrunError(f"Budget ceiling exceeded: spent ${spent_usd:.4f} > limit ${max_budget_usd:.4f}")


async def poll_until_complete(
    check_fn: Callable[[], Awaitable[dict[str, Any]]],
    deadline_seconds: float,
    interval_seconds: float = 0.2,
) -> dict[str, Any]:
    """Poll an upstream render job with a hard deadline so hung queues never stall indefinitely."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadline_seconds

    while True:
        payload = await check_fn()
        state = str(payload.get("status", "")).lower()
        if state in {"completed", "succeeded", "done"}:
            return payload
        if state in {"failed", "error", "cancelled"}:
            raise RuntimeError(f"Upstream job reported terminal failure: {payload}")

        remaining = deadline - loop.time()
        if remaining <= 0:
            raise PollingDeadlineExceededError(f"Job polling exceeded deadline of {deadline_seconds:.2f}s")
        await asyncio.sleep(min(interval_seconds, remaining))


def finalize_run_outcome(
    policy: RunExecutionPolicy,
    total_shots: int,
    completed_shots: int,
    spent_usd: float,
    error: Exception | None = None,
) -> RunOutcome:
    """Map execution results and exceptions into a deterministic, auditable terminal RunOutcome."""
    if error is not None:
        status = RunStatus.PARTIAL_FAILED if 0 < completed_shots < total_shots else RunStatus.FAILED
        return RunOutcome(
            status=status,
            mode=policy.mode,
            completed_shots=completed_shots,
            total_shots=total_shots,
            spent_usd=round(spent_usd, 4),
            error_code=type(error).__name__,
            error_detail=str(error),
        )

    if completed_shots < total_shots:
        return RunOutcome(
            status=RunStatus.PARTIAL_FAILED,
            mode=policy.mode,
            completed_shots=completed_shots,
            total_shots=total_shots,
            spent_usd=round(spent_usd, 4),
            error_code="IncompleteShotBatch",
            error_detail=f"Completed {completed_shots}/{total_shots} shots.",
        )

    return RunOutcome(
        status=RunStatus.SUCCEEDED,
        mode=policy.mode,
        completed_shots=completed_shots,
        total_shots=total_shots,
        spent_usd=round(spent_usd, 4),
    )


async def fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    retries: int = 2,
    timeout_seconds: float = 10.0,
) -> httpx.Response:
    """Retry transient HTTP 503/network errors up to `retries` times before surfacing failure."""
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = await client.get(url, timeout=timeout_seconds)
            if resp.status_code == 503:
                raise httpx.HTTPStatusError("Service Unavailable (503)", request=resp.request, response=resp)
            resp.raise_for_status()
            return resp
        except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.TransportError) as exc:
            last_exc = exc
            if attempt >= retries:
                break
            await asyncio.sleep(0.05 * (attempt + 1))
    assert last_exc is not None
    raise last_exc
