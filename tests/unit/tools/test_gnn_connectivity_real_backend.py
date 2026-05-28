import numpy as np

from brain_researcher.services.tools.params import gnn_connectivity as gc


def _make_params(tmp_path, use_real_gnn: bool) -> gc.GNNConnectivityParameters:
    return gc.GNNConnectivityParameters(
        connectivity_file=None,
        timeseries_file=None,
        output_dir=str(tmp_path),
        graph_type="functional",
        threshold=None,
        sparsity=0.1,
        model_type="gcn",
        n_layers=2,
        hidden_dim=8,
        task="node_classification",
        n_classes=2,
        mode="train",
        epochs=2,
        learning_rate=0.01,
        compute_metrics=False,
        metrics=["degree"],
        save_model=True,
        save_embeddings=True,
        save_predictions=True,
        visualize=False,
        seed=123,
        use_real_gnn=use_real_gnn,
    )


def test_real_gnn_flag_disabled(tmp_path):
    params = _make_params(tmp_path, use_real_gnn=False)
    result = gc.run_gnn_connectivity(params)
    assert result["summary"]["real_gnn_attempted"] is False
    assert result["summary"]["used_full_backend"] is False


def test_real_gnn_fallback_on_error(tmp_path, monkeypatch):
    def fake_attempt(params, adjacency, rng):
        return None, "torch_unavailable"

    monkeypatch.setattr(gc, "_attempt_real_gnn", fake_attempt)

    params = _make_params(tmp_path, use_real_gnn=True)
    result = gc.run_gnn_connectivity(params)
    assert result["summary"]["real_gnn_attempted"] is True
    assert result["summary"]["used_full_backend"] is False
    assert result["summary"]["real_gnn_error"] == "torch_unavailable"


def test_real_gnn_outputs_saved(tmp_path, monkeypatch):
    embeddings = np.ones((5, 4), dtype=np.float32)
    predictions = np.array([0, 1, 0, 1, 1], dtype=np.int32)

    def fake_attempt(params, adjacency, rng):
        return {
            "embeddings": embeddings,
            "predictions": predictions,
            "model_info": {"model_type": "gcn"},
        }, None

    monkeypatch.setattr(gc, "_attempt_real_gnn", fake_attempt)

    params = _make_params(tmp_path, use_real_gnn=True)
    result = gc.run_gnn_connectivity(params)
    assert result["summary"]["used_full_backend"] is True
    assert "embeddings" in result["outputs"]
    assert "predictions" in result["outputs"]
