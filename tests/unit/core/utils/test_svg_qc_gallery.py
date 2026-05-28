from __future__ import annotations

from pathlib import Path

from brain_researcher.core.utils.svg_qc_gallery import (
    build_rasterized_records,
    detect_svg_rasterization_runtime,
    discover_svg_paths,
    infer_subject_label,
    write_gallery_html,
)

SIMPLE_SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">
  <rect x="0" y="0" width="120" height="80" fill="white"/>
  <rect x="10" y="10" width="100" height="60" fill="none" stroke="black" stroke-width="2"/>
  <line x1="10" y1="10" x2="110" y2="70" stroke="red" stroke-width="2"/>
</svg>
"""


def test_discover_svg_paths_sorts_naturally(tmp_path: Path) -> None:
    input_dir = tmp_path / "figures"
    input_dir.mkdir()
    (input_dir / "sub-10_desc-coreg.svg").write_text(SIMPLE_SVG, encoding="utf-8")
    (input_dir / "sub-2_desc-coreg.svg").write_text(SIMPLE_SVG, encoding="utf-8")

    discovered = discover_svg_paths(input_dir=input_dir)

    assert [path.name for path in discovered] == [
        "sub-2_desc-coreg.svg",
        "sub-10_desc-coreg.svg",
    ]


def test_infer_subject_label_prefers_sub_id(tmp_path: Path) -> None:
    svg_path = tmp_path / "nested" / "sub-031" / "figure.svg"
    svg_path.parent.mkdir(parents=True)
    svg_path.write_text(SIMPLE_SVG, encoding="utf-8")

    assert infer_subject_label(svg_path) == "sub-031"


def test_build_rasterized_records_and_gallery_html(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    svg_path = input_dir / "sub-001_desc-coreg.svg"
    svg_path.write_text(SIMPLE_SVG, encoding="utf-8")

    records = build_rasterized_records(
        [svg_path],
        output_dir=tmp_path / "gallery" / "images",
        input_root=input_dir,
        image_format="png",
        dpi=120,
    )

    assert len(records) == 1
    assert records[0].image_path.exists()
    assert records[0].image_path.suffix == ".png"

    html_path = write_gallery_html(
        records,
        tmp_path / "gallery" / "index.html",
        title="Test QC",
        columns=2,
    )

    html = html_path.read_text(encoding="utf-8")
    assert "Test QC" in html
    assert "sub-001" in html
    assert "images/sub-001_desc-coreg.png" in html
    assert "svgs/sub-001_desc-coreg.svg" in html
    assert (tmp_path / "gallery" / "svgs" / "sub-001_desc-coreg.svg").exists()


def test_detect_svg_rasterization_runtime_reports_required_keys() -> None:
    runtime = detect_svg_rasterization_runtime()

    assert "ok" in runtime
    assert "rasterizer" in runtime
    assert "required_binaries" in runtime
    assert "required_python_modules" in runtime
