from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from brain_researcher.autoresearch.society.cards import (
    ClaimSpecV1,
    ClaimStatusV1,
    CommitmentCardV1,
    EvidenceEngineRefV1,
    ScopeBoundaryV1,
    lock_commitment,
)
from brain_researcher.autoresearch.society.evidence_backend import EvidenceVerdict

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_SCRIPT = REPO_ROOT / "scripts" / "autoresearch" / "run_auditable_claim_demo.py"


def _load_demo_module():
    spec = importlib.util.spec_from_file_location(
        "claim_demo_contract_test", DEMO_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _claim() -> ClaimSpecV1:
    return ClaimSpecV1(
        claim_id="claim-stable",
        claim_text="A fixed test claim.",
        scope_boundary=ScopeBoundaryV1(modality="fMRI", datasets=["public-v1"]),
    )


def _write_rubrics(root: Path) -> dict[str, Path]:
    paths = {}
    for name, content in {
        "strict_evidence_profile": "strict rubric\n",
        "compositional_specificity": "specificity rubric\n",
        "network_coactivation": "network rubric\n",
    }.items():
        path = root / "reproducibility" / "rubrics" / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        paths[name] = path
    return paths


def test_hash_is_clone_stable_but_covers_engine_and_rubric_content(
    tmp_path: Path,
) -> None:
    demo = _load_demo_module()
    root_a = tmp_path / "clone-a"
    root_b = tmp_path / "clone-b"
    refs_a = demo._rubric_refs(rubric_paths=_write_rubrics(root_a), repo_root=root_a)
    refs_b = demo._rubric_refs(rubric_paths=_write_rubrics(root_b), repo_root=root_b)
    engine = EvidenceEngineRefV1(
        name="nimare", version="0.6.1", adapter="NimareBackend"
    )

    card_a = lock_commitment(_claim(), list(refs_a), refs_a, evidence_engine=engine)
    card_b = lock_commitment(_claim(), list(refs_b), refs_b, evidence_engine=engine)

    assert refs_a == refs_b
    assert all(not Path(ref["path"]).is_absolute() for ref in refs_a.values())
    assert card_a.commitment_hash == card_b.commitment_hash
    assert card_a.model_copy(update={"locked_at": "different-time"}).verify_hash()
    assert not card_a.model_copy(
        update={
            "evidence_engine": EvidenceEngineRefV1(
                name="nimare", version="different", adapter="NimareBackend"
            )
        }
    ).verify_hash()

    changed_refs = {name: dict(ref) for name, ref in refs_a.items()}
    changed_refs["strict_evidence_profile"]["hash"] = "0" * 64
    assert not card_a.model_copy(update={"rubric_refs": changed_refs}).verify_hash()


def test_new_card_without_engine_identity_seals_the_typed_null() -> None:
    card = lock_commitment(_claim(), [], {})
    assert card.evidence_engine is None
    assert "evidence_engine" in card.model_fields_set
    assert card.verify_hash()


def test_committed_historical_card_keeps_its_original_hash_shape() -> None:
    payload = json.loads(
        (
            REPO_ROOT
            / "reproducibility"
            / "auditable_claim_record"
            / "commitment_card.json"
        ).read_text(encoding="utf-8")
    )
    card = CommitmentCardV1.model_validate(payload)
    assert "falsifier_battery" not in card.model_fields_set
    assert "evidence_engine" not in card.model_fields_set
    assert card.verify_hash()


def test_demo_persists_commitment_before_querying_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    demo = _load_demo_module()
    corpus = tmp_path / "clone" / "data" / "corpus.pkl"
    corpus.parent.mkdir(parents=True)
    corpus.write_bytes(b"public corpus")
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "source_manifest.json").write_text("{}", encoding="utf-8")
    provenance_path = corpus.with_name(corpus.name + ".provenance.json")
    provenance_path.write_text("{}", encoding="utf-8")
    output_dir = tmp_path / "output"
    engine = EvidenceEngineRefV1(
        name="nimare", version="0.6.1", adapter="NimareBackend"
    )
    refs = {
        name: {"path": f"rubrics/{name}.md", "hash": str(index) * 64}
        for index, name in enumerate(demo.RUBRIC_PATHS, start=1)
    }

    monkeypatch.setattr(demo, "_evidence_engine_ref", lambda *args, **kwargs: engine)
    monkeypatch.setattr(demo, "_rubric_refs", lambda: refs)
    monkeypatch.setattr(
        demo,
        "verify_converted_dataset",
        lambda *args, **kwargs: {
            "source_snapshot": "version-7",
            "source_commit": "test-source-commit",
        },
    )

    def fake_evidence(**kwargs):
        sealed = output_dir / "commitment_card.json"
        assert sealed.is_file()
        assert CommitmentCardV1.model_validate_json(
            sealed.read_text(encoding="utf-8")
        ).verify_hash()
        verdict = EvidenceVerdict(
            status=ClaimStatusV1.supported_within_scope,
            backend="nimare",
            n_supporting=1,
        )
        return {
            "forward_default": verdict,
            "forward_strict": verdict,
            "specificity_excluding_rivals": verdict,
            "network_coactivation": verdict,
        }

    monkeypatch.setattr(demo, "run_neurolang_evidence", fake_evidence)
    bundle = demo.run_demo(
        corpus_path=corpus,
        source_dir=source_dir,
        output_dir=output_dir,
        venv_python=None,
        backend_name="nimare",
    )

    assert bundle["calibration"]["commitment_card"]["evidence_engine"] == {
        "name": "nimare",
        "version": "0.6.1",
        "adapter": "NimareBackend",
    }
    assert bundle["corpus_ref"]["kind"] == "external_basename"
    assert not Path(bundle["corpus_ref"]["path"]).is_absolute()
    assert bundle["corpus_ref"]["verified_source"]["source_commit"] == (
        "test-source-commit"
    )
