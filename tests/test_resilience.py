import httpx
import pytest

from cineforge.safety.production_gate import (
    BudgetOverrunError,
    PollingDeadlineExceededError,
    ProductionGateError,
    RunExecutionPolicy,
    RunStatus,
    RuntimeMode,
    ServiceAdapterSpec,
    check_budget_ceiling,
    enforce_production_gate,
    fetch_with_retry,
    finalize_run_outcome,
    poll_until_complete,
)


def test_production_mode_blocks_mock_and_unverified_adapters() -> None:
    policy = RunExecutionPolicy(
        mode=RuntimeMode.PRODUCTION,
        require_c2pa_signing=True,
        c2pa_cert_configured=True,
    )
    adapters = [
        ServiceAdapterSpec(name="comfyui", is_mock=False, endpoint_url="http://gpu:8188", verified_live=True),
        ServiceAdapterSpec(name="ollama_qa", is_mock=True, endpoint_url="http://localhost:11434", verified_live=False),
    ]

    with pytest.raises(ProductionGateError, match="forbids mock/stub adapters: ollama_qa"):
        enforce_production_gate(policy, adapters)


def test_production_mode_blocks_missing_c2pa_certificate() -> None:
    policy = RunExecutionPolicy(
        mode=RuntimeMode.PRODUCTION,
        require_c2pa_signing=True,
        c2pa_cert_configured=False,
    )
    adapters = [ServiceAdapterSpec(name="comfyui", is_mock=False, endpoint_url="http://gpu:8188", verified_live=True)]

    with pytest.raises(ProductionGateError, match="C2PA_CERT_PATH"):
        enforce_production_gate(policy, adapters)


def test_mock_and_hybrid_modes_allow_stub_adapters() -> None:
    adapters = [ServiceAdapterSpec(name="comfyui", is_mock=True)]
    enforce_production_gate(RunExecutionPolicy(mode=RuntimeMode.MOCK), adapters)
    enforce_production_gate(RunExecutionPolicy(mode=RuntimeMode.HYBRID), adapters)


@pytest.mark.asyncio
async def test_poll_until_complete_enforces_deadline() -> None:
    async def always_running() -> dict[str, str]:
        return {"status": "running"}

    with pytest.raises(PollingDeadlineExceededError, match="exceeded deadline"):
        await poll_until_complete(always_running, deadline_seconds=0.12, interval_seconds=0.03)


@pytest.mark.asyncio
async def test_fetch_with_retry_surfaces_503_service_loss() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.HTTPStatusError, match="503"):
            await fetch_with_retry(client, "http://gpu:8188/queue", retries=2)

    assert attempts == 3


@pytest.mark.asyncio
async def test_fetch_with_retry_surfaces_read_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("VLM timed out", request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(httpx.ReadTimeout):
            await fetch_with_retry(client, "http://localhost:11434/api/chat", retries=1)


def test_budget_overrun_and_partial_failure_manifest() -> None:
    policy = RunExecutionPolicy(mode=RuntimeMode.PRODUCTION, max_budget_usd=2.50)

    with pytest.raises(BudgetOverrunError) as exc_info:
        check_budget_ceiling(spent_usd=2.75, max_budget_usd=policy.max_budget_usd)

    outcome = finalize_run_outcome(
        policy=policy,
        total_shots=4,
        completed_shots=2,
        spent_usd=2.75,
        error=exc_info.value,
    )
    assert outcome.status == RunStatus.PARTIAL_FAILED
    assert outcome.error_code == "BudgetOverrunError"
    assert outcome.completed_shots == 2
