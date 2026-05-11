from backend.app.evidence_package import EvidencePackage, EvidencePackageBuilder, MDA_TITLE
from backend.app.evidence_package_projection import EvidencePackageProjection


def test_evidence_package_builder_preserves_json_shape_and_registers_source_items() -> None:
    builder = EvidencePackageBuilder(
        implementation_id="analysis_run_test",
        root_title=MDA_TITLE,
        start_page=4,
        end_page=6,
        locator_evidence=[{"kind": "section_start", "page": 4}],
    )

    builder.start_subsection(title="一、经营情况讨论与分析", page=4)
    builder.add_text_span(page=4, text="营业收入同比增长。")
    table = {
        "table_id": builder.next_table_id(),
        "source_section_id": builder.current_source_section_id,
        "title": "主要经营数据",
        "summary": "主要经营数据，共 1 行 2 列。",
        "page": 4,
        "page_label": "PDF 第 4 页",
        "columns": ["项目", "金额"],
        "rows": [{"项目": "营业收入", "金额": "100亿元"}],
        "notes": [],
        "metadata": {"row_count": 1, "column_count": 2, "parser": "pipe_table_v1"},
        "source_bbox": None,
    }
    builder.add_table(table)

    data = builder.to_persisted_json()

    assert data["implementation_id"] == "analysis_run_test"
    assert data["section_location_evidence"] == [{"kind": "section_start", "page": 4}]
    assert data["source_sections"][0]["children"][0]["text_span_ids"] == ["text_span_1"]
    assert data["source_sections"][0]["children"][0]["table_ids"] == ["table_1"]
    assert data["text_spans"][0]["source_section_id"] == "source_section_2"
    assert data["tables"][0]["source_section_id"] == "source_section_2"


def test_evidence_package_registry_validates_projects_and_indexes_evidence() -> None:
    data = {
        "implementation_id": "analysis_run_test",
        "source_sections": [
            {
                "source_section_id": "source_section_1",
                "title": MDA_TITLE,
                "level": 1,
                "page_start": 4,
                "page_end": 6,
                "text_span_ids": ["text_span_1"],
                "table_ids": ["table_1"],
                "image_ids": ["image_1"],
                "children": [],
            }
        ],
        "text_spans": [
            {
                "text_span_id": "text_span_1",
                "source_section_id": "source_section_1",
                "page": 4,
                "page_label": "PDF 第 4 页",
                "text": "营业收入同比增长。",
            }
        ],
        "tables": [
            {
                "table_id": "table_1",
                "source_section_id": "source_section_1",
                "title": "主要经营数据",
                "summary": "主要经营数据，共 1 行 2 列。",
                "page": 4,
                "page_label": "PDF 第 4 页",
                "columns": ["项目", "金额"],
                "rows": [{"项目": "营业收入", "金额": "100亿元"}],
                "notes": [],
                "metadata": {"row_count": 1, "column_count": 2, "parser": "pipe_table_v1"},
                "source_bbox": None,
            }
        ],
        "figures": [
            {
                "image_id": "image_1",
                "source_section_id": "source_section_1",
                "page": 5,
                "page_label": "PDF 第 5 页",
                "bbox": [0, 0, 100, 100],
                "title": "收入结构图",
                "caption": None,
                "summary": "收入结构图显示主营业务占比较高。",
                "classification_reason": "图示来自管理层讨论与分析。",
                "relevance": "high",
                "relevance_reason": "展示经营数据。",
                "is_relevant_to_analysis": True,
                "original": {
                    "storage_key": "figures/image_1.png",
                    "content_type": "image/png",
                    "width": 100,
                    "height": 100,
                },
                "thumbnail": {
                    "storage_key": "figures/image_1-thumb.png",
                    "content_type": "image/png",
                    "width": 100,
                    "height": 100,
                },
                "prompt_version": "figure_summary_v1",
            }
        ],
        "section_location_evidence": [],
    }
    package = EvidencePackage(data)
    projection = EvidencePackageProjection(package)
    assert not hasattr(package, "source_sections")
    assert not hasattr(package, "text_spans")
    assert not hasattr(package, "tables")
    assert not hasattr(package, "figures")

    validation = package.validate_analysis_point(
        {
            "text": "公司收入增长且主营业务占比较高。",
            "evidence": [
                {
                    "content_type": "text",
                    "source_section_id": "source_section_1",
                    "text_span_id": "text_span_1",
                },
                {
                    "content_type": "table",
                    "source_section_id": "source_section_1",
                    "table_id": "table_1",
                },
                {
                    "content_type": "figure_summary",
                    "source_section_id": "source_section_1",
                    "image_id": "image_1",
                },
            ],
        }
    )

    assert validation.errors == []
    assert validation.point is not None
    assert validation.point["source_section_ids"] == ["source_section_1"]

    detail = projection.report_detail(
        file_version_id=7,
        analysis_run_id=11,
        prompt_version="mda_outline_v1",
        structured_outline={
            "summary": ["摘要一", "摘要二", "摘要三"],
            "analysis_sections": [{"title": "经营表现", "points": [validation.point]}],
        },
        qa_available=True,
        qa_unavailable_reason=None,
    )

    assert detail["table_index"]["table_1"]["table_url"] == (
        "/api/file-versions/7/analysis-result/tables/table_1"
    )
    assert detail["figure_index"]["image_1"]["thumb_url"] == (
        "/api/file-versions/7/analysis-result/figures/image_1?variant=thumb"
    )
    assert detail["analysis_sections"][0]["points"][0]["evidence"][2]["original_url"] == (
        "/api/file-versions/7/analysis-result/figures/image_1?variant=original"
    )

    documents = projection.qa_index_documents(file_version_id=7, analysis_run_id=11)
    assert [document["metadata"]["content_type"] for document in documents] == [
        "text",
        "table",
        "figure_summary",
    ]
    assert projection.evidence_from_index_document(documents[0])["text_span_id"] == "text_span_1"
    assert package.validate_qa_evidence_item(validation.point["evidence"][1])["table_id"] == "table_1"
