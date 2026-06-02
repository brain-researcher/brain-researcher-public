from __future__ import annotations

from brain_researcher.services.br_kg.behavior_embeddings import (
    BehaviorEmbeddingConfig,
    _hf_auto_dispatch_kwargs,
    _load_hf_model_with_optional_offload,
)


class _FakeCuda:
    def __init__(self, available: bool) -> None:
        self._available = available
        self.empty_cache_calls = 0

    def is_available(self) -> bool:
        return self._available

    def empty_cache(self) -> None:
        self.empty_cache_calls += 1


class _FakeTorch:
    def __init__(self, available: bool = True) -> None:
        self.cuda = _FakeCuda(available)
        self.float16 = "float16"


def test_hf_auto_dispatch_kwargs_include_device_map_and_dtype_when_cuda_available() -> (
    None
):
    kwargs = _hf_auto_dispatch_kwargs(_FakeTorch(available=True))

    assert kwargs["device_map"] == "auto"
    assert kwargs["low_cpu_mem_usage"] is True
    assert kwargs["torch_dtype"] == "float16"


def test_load_hf_model_with_optional_offload_retries_after_cuda_oom() -> None:
    calls: list[dict[str, object]] = []

    class _FakeModelCls:
        @staticmethod
        def from_pretrained(model_name_or_path: str, **kwargs):
            calls.append({"model_name_or_path": model_name_or_path, **kwargs})
            if len(calls) == 1:
                raise RuntimeError("CUDA out of memory while loading model")
            return {"ok": True}

    config = BehaviorEmbeddingConfig(
        model_name_or_path="marcelbinz/Llama-3.1-Minitaur-8B",
        backend="hf_hidden_state",
        device="cuda",
    )
    torch_module = _FakeTorch(available=True)

    model, used_auto_dispatch = _load_hf_model_with_optional_offload(
        _FakeModelCls,
        config=config,
        torch_module=torch_module,
        requested_device="cuda",
        auto_dispatch=False,
    )

    assert model == {"ok": True}
    assert used_auto_dispatch is True
    assert torch_module.cuda.empty_cache_calls == 1
    assert len(calls) == 2
    assert "device_map" not in calls[0]
    assert calls[1]["device_map"] == "auto"
    assert calls[1]["low_cpu_mem_usage"] is True
    assert calls[1]["torch_dtype"] == "float16"
