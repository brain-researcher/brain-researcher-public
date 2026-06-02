from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

import yaml

DEFAULT_PROFILE = {
    "step_budget": 2,
    "auto_tests": "auto",  # auto | run | skip
    "risk_threshold": {"max_files": 4, "max_lines": 200},
    "require_confirm": False,
    "allow_external_net": False,
}


@dataclass
class Profile:
    name: str
    data: Dict[str, Any]

    def effective(self) -> Dict[str, Any]:
        merged = DEFAULT_PROFILE.copy()
        merged.update(self.data or {})
        return merged


def iter_config_paths() -> Tuple[Path, ...]:
    paths: list[Path] = []
    env_path = os.environ.get("BRAINR_CONFIG")
    if env_path:
        paths.append(Path(env_path).expanduser())

    repo_root = Path.cwd()
    paths.extend(
        [
            repo_root / "configs" / "brainr.yaml",
            repo_root / ".brainr" / "config.yaml",
            Path.home() / ".brainr" / "config.yaml",
        ]
    )
    # Remove duplicates while preserving order
    seen = set()
    unique: list[Path] = []
    for p in paths:
        resolved = p.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(p)
    return tuple(unique)


def load_profiles() -> Tuple[Dict[str, Profile], str]:
    config: Dict[str, Any] = {"profile": "dev", "profiles": {"dev": DEFAULT_PROFILE}}
    for path in iter_config_paths():
        if path.exists():
            with path.open("r", encoding="utf-8") as fh:
                loaded = yaml.safe_load(fh) or {}
            config = {**config, **loaded}
            break

    profiles = {}
    for name, data in config.get("profiles", {}).items():
        profiles[name] = Profile(name=name, data=data or {})
    return profiles, config.get("profile", "dev")
