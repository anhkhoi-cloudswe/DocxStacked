import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.app.db.models import Exam, ExamType, Job, JobStatus, Question
from backend.app.modules.analysis.ai_check import AICheckService
from backend.app.modules.analysis.providers import ProviderAuthError, VisionProvider
from backend.app.modules.crawler.browser import AuthenticationRequiredError
from backend.app.modules.crawler.questions import _download_image_sync, crawl_exam_questions
from backend.app.modules.jobs.orchestrator import JobOrchestrator


class MockFailingAuthProvider(VisionProvider):
    def __init__(self, name="failing_auth"):
        super().__init__(name=name, model="test-model", api_key_env="TEST_KEY")

    def is_available(self) -> bool:
        return True

    def call_vision_api(self, image_path: Path, prompt: str, system_prompt: str) -> str:
        raise ProviderAuthError("HTTP 401 Unauthorized: Invalid API key")


def test_ai_check_service_disables_failing_provider(tmp_path):
    """Verify that ProviderAuthError marks provider as disabled so it is not queried repeatedly."""
    service = AICheckService()
    failing_provider = MockFailingAuthProvider()
    service._providers = [failing_provider]

    assert len(service.get_available_providers()) == 1

    # Create real dummy image file
    fake_img = tmp_path / "test_q.jpg"
    fake_img.write_bytes(b"dummy image bytes")

    with patch.object(service, "compute_phash", return_value="12345"):
        res = service.analyze_with_provider(failing_provider, fake_img)
        assert res is None
        assert failing_provider.name in service._disabled_providers
        # Next call to get_available_providers must exclude it
        assert len(service.get_available_providers()) == 0


@pytest.mark.asyncio
async def test_download_image_consecutive_403_raises_auth_error(tmp_path):
    """Verify that 2 consecutive 403 responses raise AuthenticationRequiredError with single-session hint."""
    exam = Exam(id=999, subject_id=1, title="Test Exam", url="https://fuoverflow.com/threads/test.123/", exam_type=ExamType.FE)

    # Mock _fetch_thread_html_sync returning valid thread with 2 attachments
    fake_html = """
    <section class="message-attachments">
      <ul class="attachmentList">
        <li class="file"><span class="file-name">Q1.jpg</span><a class="file-preview" data-lb-sidebar-href="/media/q1.101/"></a></li>
        <li class="file"><span class="file-name">Q2.jpg</span><a class="file-preview" data-lb-sidebar-href="/media/q2.102/"></a></li>
      </ul>
    </section>
    """

    mock_db = AsyncMock()
    mock_db.execute.return_value = MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]), scalar_one_or_none=MagicMock(return_value=None))))
    mock_storage = MagicMock()

    with patch("backend.app.modules.crawler.questions._fetch_thread_html_sync", return_value=(fake_html, "ok")):
        # Simulate 403 Forbidden returned by browser for both images
        with patch("backend.app.modules.crawler.questions._download_image_sync", return_value=(False, "403_forbidden")):
            with pytest.raises(AuthenticationRequiredError) as exc_info:
                await crawl_exam_questions(
                    exam=exam,
                    subject_code="TEST",
                    db=mock_db,
                    storage=mock_storage,
                )
            assert "1 phiên đăng nhập" in str(exc_info.value)
