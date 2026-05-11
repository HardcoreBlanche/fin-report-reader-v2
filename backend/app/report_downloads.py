from __future__ import annotations

from pathlib import Path
from typing import Protocol

from backend.app.evidence_package_projection import projection_from_result
from backend.app.models import AnalysisResult


class FigureAssetResolver(Protocol):
    def resolve_asset(self, implementation_id: str, storage_key: str) -> Path:
        """Resolve a run-owned figure asset key to a local file."""


class AnalysisResultDownloadService:
    def __init__(self, figure_asset_store: FigureAssetResolver | None = None):
        self.figure_asset_store = figure_asset_store

    def render_markdown(self, result: AnalysisResult) -> str:
        return render_analysis_result_markdown(result)

    def build_zip(self, result: AnalysisResult) -> bytes:
        return build_analysis_result_zip(result, self.figure_asset_store)


def render_analysis_result_markdown(result: AnalysisResult) -> str:
    return projection_from_result(result).render_markdown(result)


def build_analysis_result_zip(
    result: AnalysisResult,
    figure_asset_store: FigureAssetResolver | None,
) -> bytes:
    return projection_from_result(result).build_zip(
        result=result,
        figure_asset_store=figure_asset_store,
    )
