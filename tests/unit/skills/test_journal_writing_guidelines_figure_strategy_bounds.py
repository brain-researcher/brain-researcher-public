from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
GUIDES = (
    ROOT / "skills" / "journal-writing-guidelines" / "references" / "journal_writing_guides.yaml"
)
CONSTRAINTS = (
    ROOT / "skills" / "journal-writing-guidelines" / "references" / "journal_constraints.yaml"
)


def test_figure_targets_do_not_exceed_hard_limits_when_defined() -> None:
    guides_payload = yaml.safe_load(GUIDES.read_text(encoding="utf-8")) or {}
    constraints_payload = yaml.safe_load(CONSTRAINTS.read_text(encoding="utf-8")) or {}

    for journal_id, guide_cfg in guides_payload.get("journals", {}).items():
        main_figures = guide_cfg.get("figure_strategy", {}).get("main_figures", {})
        target = int(main_figures.get("target"))
        max_recommended = int(main_figures.get("max"))

        article_cfg = (
            constraints_payload.get("journals", {})
            .get(journal_id, {})
            .get("article_types", {})
            .get("research_article", {})
        )
        display_rule = article_cfg.get("display_items_max")
        if isinstance(display_rule, dict) and isinstance(display_rule.get("value"), int):
            hard_limit = int(display_rule["value"])
            assert target <= hard_limit, f"{journal_id} target {target} > hard limit {hard_limit}"
            assert (
                max_recommended <= hard_limit
            ), f"{journal_id} max {max_recommended} > hard limit {hard_limit}"
