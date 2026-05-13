import json

from backend.app.main import create_app
from backend.app.openai_like_figure_visual_analyzer import (
    OpenAiLikeFigureVisualAnalyzer,
    ProviderCallError,
    load_model_provider_settings,
)
from backend.app.pdf_extraction import PdfFigureCandidate


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\xf8\x0f"
    b"\x00\x01\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)


def figure_candidate() -> PdfFigureCandidate:
    return PdfFigureCandidate(
        candidate_id="chart-1",
        page=4,
        bbox=[96, 180, 480, 360],
        width=384,
        height=180,
        image_bytes=PNG_BYTES,
        image_extension="png",
        title="主营业务收入结构图",
        caption="图像型表格或图表均走当前 figure 分析路径。",
    )


def configured_env() -> dict[str, str]:
    return {
        "MDA_FIGURE_VISION_BASE_URL": "https://openai-like.example/v1",
        "MDA_FIGURE_VISION_API_KEY": "sk-test",
        "MDA_FIGURE_VISION_MODEL": "gpt-4.1-mini",
        "MDA_OUTLINE_GENERATION_BASE_URL": "https://outline.example/v1",
        "MDA_OUTLINE_GENERATION_API_KEY": "sk-outline",
        "MDA_OUTLINE_GENERATION_MODEL": "gpt-4.1",
    }


def test_load_model_provider_settings_reads_separate_figure_and_outline_env_keys() -> None:
    settings = load_model_provider_settings(configured_env())

    assert settings.figure.base_url == "https://openai-like.example/v1"
    assert settings.figure.api_key == "sk-test"
    assert settings.figure.model == "gpt-4.1-mini"
    assert settings.outline.base_url == "https://outline.example/v1"
    assert settings.outline.api_key == "sk-outline"
    assert settings.outline.model == "gpt-4.1"


def test_openai_like_figure_visual_analyzer_sends_inline_image_request_and_validates_response() -> None:
    recorded_calls: list[tuple[str, dict, dict]] = []

    def post_json(url: str, headers: dict[str, str], payload: dict) -> dict:
        recorded_calls.append((url, headers, payload))
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "is_informational": True,
                                "classification_reason": "图像内容包含经营分析信息。",
                                "summary": "图示显示核心产品收入占比较高。",
                                "relevance": "high",
                                "relevance_reason": "直接支持主营业务收入结构分析。",
                            }
                        )
                    }
                }
            ]
        }

    analyzer = OpenAiLikeFigureVisualAnalyzer.from_settings(
        load_model_provider_settings(configured_env()).figure,
        post_json=post_json,
    )

    summary = analyzer.summarize(figure_candidate())

    assert summary["summary"] == "图示显示核心产品收入占比较高。"
    assert len(recorded_calls) == 1
    url, headers, payload = recorded_calls[0]
    assert url == "https://openai-like.example/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-test"
    assert payload["model"] == "gpt-4.1-mini"
    assert payload["response_format"] == {"type": "json_object"}
    content = payload["messages"][1]["content"]
    assert content[0]["type"] == "text"
    assert "image-only tables" in content[0]["text"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_openai_like_figure_visual_analyzer_retries_once_for_retryable_provider_failure() -> None:
    attempts: list[int] = []

    def post_json(url: str, headers: dict[str, str], payload: dict) -> dict:
        attempts.append(len(attempts) + 1)
        if len(attempts) == 1:
            raise ProviderCallError("gateway timeout", retryable=True)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "is_informational": True,
                                "classification_reason": "图像内容包含经营分析信息。",
                                "summary": "第二次请求返回了有效摘要。",
                                "relevance": "high",
                                "relevance_reason": "直接支持分析。",
                            }
                        )
                    }
                }
            ]
        }

    analyzer = OpenAiLikeFigureVisualAnalyzer.from_settings(
        load_model_provider_settings(configured_env()).figure,
        post_json=post_json,
    )

    summary = analyzer.summarize(figure_candidate())

    assert summary["summary"] == "第二次请求返回了有效摘要。"
    assert attempts == [1, 2]


def test_openai_like_figure_visual_analyzer_rejects_invalid_provider_response() -> None:
    def post_json(url: str, headers: dict[str, str], payload: dict) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "is_informational": True,
                                "classification_reason": "给了分类理由。",
                                "relevance": "high",
                                "relevance_reason": "给了相关性理由。",
                            }
                        )
                    }
                }
            ]
        }

    analyzer = OpenAiLikeFigureVisualAnalyzer.from_settings(
        load_model_provider_settings(configured_env()).figure,
        post_json=post_json,
    )

    try:
        analyzer.summarize(figure_candidate())
    except ValueError as exc:
        assert "summary" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_openai_like_figure_visual_analyzer_does_not_retry_non_retryable_provider_failure() -> None:
    attempts: list[int] = []

    def post_json(url: str, headers: dict[str, str], payload: dict) -> dict:
        attempts.append(len(attempts) + 1)
        raise ProviderCallError("unauthorized", retryable=False)

    analyzer = OpenAiLikeFigureVisualAnalyzer.from_settings(
        load_model_provider_settings(configured_env()).figure,
        post_json=post_json,
    )

    try:
        analyzer.summarize(figure_candidate())
    except ProviderCallError as exc:
        assert str(exc) == "unauthorized"
    else:
        raise AssertionError("expected ProviderCallError")

    assert attempts == [1]


def test_create_app_uses_env_configured_openai_like_figure_analyzer(monkeypatch) -> None:
    for key, value in configured_env().items():
        monkeypatch.setenv(key, value)

    app = create_app(database_url="sqlite://")

    analyzer = app.state.mda_analysis.figure_visual_analyzer
    assert isinstance(analyzer, OpenAiLikeFigureVisualAnalyzer)
    assert analyzer.is_available() is True
