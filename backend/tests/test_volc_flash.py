import json

import httpx
import pytest

from app.scoring.base import ScoringError
from app.scoring.volc_flash import VolcFlashAsr


def test_flash_transcript_and_request() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Api-Key"] == "test-key"
        assert request.headers["X-Api-Resource-Id"] == "volc.bigasr.auc_turbo"
        payload = json.loads(request.content)
        assert payload["audio"]["data"] == "YXVkaW8="
        assert payload["request"]["enable_ddc"] is False
        assert payload["request"]["enable_itn"] is False
        return httpx.Response(
            200,
            headers={"X-Api-Status-Code": "20000000"},
            json={"result": {"text": "I I like cats."}},
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        assert (
            VolcFlashAsr("test-key", client).transcribe(b"audio", "audio/wav")
            == "I I like cats."
        )


@pytest.mark.parametrize("code", ["45000001", "55000031", ""])
def test_flash_service_errors(code: str) -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, headers={"X-Api-Status-Code": code}, json={})
        )
    ) as client:
        with pytest.raises(ScoringError):
            VolcFlashAsr("test-key", client).transcribe(b"audio", "audio/wav")


def test_flash_silence() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"X-Api-Status-Code": "20000003"}, json={}
            )
        )
    ) as client:
        assert VolcFlashAsr("test-key", client).transcribe(b"audio", "audio/wav") == ""


def test_flash_missing_key() -> None:
    with pytest.raises(ScoringError, match="VOLC_ASR_API_KEY"):
        VolcFlashAsr("").transcribe(b"audio", "audio/wav")


def test_flash_malformed_success() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"X-Api-Status-Code": "20000000"}, json={"result": {}}
            )
        )
    ) as client:
        with pytest.raises(ScoringError, match="格式无效"):
            VolcFlashAsr("test-key", client).transcribe(b"audio", "audio/wav")


def test_provider_selection_keeps_mock_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.scoring.worker import build_asr_provider

    monkeypatch.setattr(settings, "ASR_PROVIDER", "volc_flash")
    monkeypatch.setattr(settings, "VOLC_ASR_API_KEY", "test-key")
    monkeypatch.setattr(settings, "SCORING_PROVIDER", "mock")
    assert build_asr_provider().name == "mock"
    monkeypatch.setattr(settings, "SCORING_PROVIDER", "ark")
    assert isinstance(build_asr_provider(), VolcFlashAsr)
