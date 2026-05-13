from __future__ import annotations

import base64
import json
import logging
import os
import socket
from dataclasses import dataclass
from typing import Callable, Mapping
from urllib import error, parse, request

from pydantic import BaseModel, ValidationError

from backend.app.pdf_extraction import PdfFigureCandidate


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderSettings:
    base_url: str | None
    api_key: str | None
    model: str | None

    def is_complete(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)


@dataclass(frozen=True)
class ModelProviderSettings:
    figure: ProviderSettings
    outline: ProviderSettings


class ProviderCallError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool):
        super().__init__(message)
        self.retryable = retryable


class _FigureSummaryResponse(BaseModel):
    is_informational: bool
    classification_reason: str
    summary: str
    relevance: str
    relevance_reason: str


def load_model_provider_settings(env: Mapping[str, str] | None = None) -> ModelProviderSettings:
    source = env or os.environ
    return ModelProviderSettings(
        figure=ProviderSettings(
            base_url=_clean_env(source.get("MDA_FIGURE_VISION_BASE_URL")),
            api_key=_clean_env(source.get("MDA_FIGURE_VISION_API_KEY")),
            model=_clean_env(source.get("MDA_FIGURE_VISION_MODEL")),
        ),
        outline=ProviderSettings(
            base_url=_clean_env(source.get("MDA_OUTLINE_GENERATION_BASE_URL")),
            api_key=_clean_env(source.get("MDA_OUTLINE_GENERATION_API_KEY")),
            model=_clean_env(source.get("MDA_OUTLINE_GENERATION_MODEL")),
        ),
    )


def build_default_figure_visual_analyzer(
    env: Mapping[str, str] | None = None,
) -> OpenAiLikeFigureVisualAnalyzer | None:
    settings = load_model_provider_settings(env).figure
    if not settings.is_complete():
        return None
    return OpenAiLikeFigureVisualAnalyzer.from_settings(settings)


class OpenAiLikeFigureVisualAnalyzer:
    prompt_version = "figure_summary_openai_like_v1"

    def __init__(
        self,
        *,
        settings: ProviderSettings,
        post_json: Callable[[str, dict[str, str], dict], dict] | None = None,
    ):
        self._settings = settings
        self._post_json = post_json or self._post_json_default

    @classmethod
    def from_settings(
        cls,
        settings: ProviderSettings,
        *,
        post_json: Callable[[str, dict[str, str], dict], dict] | None = None,
    ) -> OpenAiLikeFigureVisualAnalyzer:
        return cls(settings=settings, post_json=post_json)

    def is_available(self) -> bool:
        return self._settings.is_complete() and self._has_valid_base_url()

    def summarize(self, candidate: PdfFigureCandidate) -> dict:
        if not self.is_available():
            raise RuntimeError("visual model configuration is unavailable")

        payload = self._build_payload(candidate)
        url = self._chat_completions_url()
        headers = {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Content-Type": "application/json",
        }
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._post_json(url, headers, payload)
                content = self._extract_content(response)
                summary = _FigureSummaryResponse.model_validate_json(content)
                return summary.model_dump()
            except ProviderCallError as exc:
                logger.warning(
                    "Figure provider call failed on attempt %s (retryable=%s): %s",
                    attempt,
                    exc.retryable,
                    exc,
                )
                if exc.retryable and attempt < 2:
                    continue
                raise
            except ValidationError as exc:
                logger.warning("Figure provider response validation failed: %s", exc)
                raise ValueError(str(exc)) from exc

    def _build_payload(self, candidate: PdfFigureCandidate) -> dict:
        image_url = self._data_url(candidate)
        return {
            "model": self._settings.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You analyze one figure candidate from the management discussion and analysis "
                        "section of a Chinese annual report."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Return JSON with keys is_informational, classification_reason, summary, "
                                "relevance, and relevance_reason. Treat charts, diagrams, and image-only "
                                "tables as figure inputs in the current phase. Use concise Chinese."
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
        }

    def _data_url(self, candidate: PdfFigureCandidate) -> str:
        extension = candidate.image_extension.lower().lstrip(".") or "png"
        payload = base64.b64encode(candidate.image_bytes).decode("ascii")
        return f"data:image/{'jpeg' if extension in {'jpg', 'jpeg'} else extension};base64,{payload}"

    def _chat_completions_url(self) -> str:
        assert self._settings.base_url is not None
        return self._settings.base_url.rstrip("/") + "/chat/completions"

    def _has_valid_base_url(self) -> bool:
        if not self._settings.base_url:
            return False
        parsed = parse.urlparse(self._settings.base_url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def _extract_content(self, response: dict) -> str:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("missing choices[0].message.content") from exc
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = [
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
            ]
            if text_parts:
                return "".join(text_parts)
        raise ValueError("unsupported message.content shape")

    def _post_json_default(self, url: str, headers: dict[str, str], payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(url, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(http_request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            message = self._safe_http_error_message(exc)
            retryable = exc.code in {408, 409, 425, 429} or exc.code >= 500
            raise ProviderCallError(message, retryable=retryable) from exc
        except (error.URLError, TimeoutError, socket.timeout) as exc:
            raise ProviderCallError("connection failed", retryable=True) from exc
        except json.JSONDecodeError as exc:
            raise ProviderCallError("provider returned invalid JSON", retryable=False) from exc

    def _safe_http_error_message(self, exc: error.HTTPError) -> str:
        return f"http {exc.code} from figure provider"


def _clean_env(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
