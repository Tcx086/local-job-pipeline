from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .utils import CONFIG_DIR, TEMPLATES_DIR, load_yaml


@dataclass(frozen=True)
class PublicConfigSpec:
    name: str
    local_path: Path
    example_path: Path
    required: bool = False


PUBLIC_CONFIGS: dict[str, PublicConfigSpec] = {
    "search_scope": PublicConfigSpec(
        "search_scope",
        CONFIG_DIR / "search_scope.yaml",
        CONFIG_DIR / "search_scope.example.yaml",
        required=True,
    ),
    "application_campaign": PublicConfigSpec(
        "application_campaign",
        CONFIG_DIR / "application_campaign.local.yaml",
        CONFIG_DIR / "application_campaign.example.yaml",
    ),
    "apply_profile": PublicConfigSpec(
        "apply_profile",
        CONFIG_DIR / "apply_profile.local.yaml",
        CONFIG_DIR / "apply_profile.example.yaml",
    ),
    "resume_profile_paths": PublicConfigSpec(
        "resume_profile_paths",
        CONFIG_DIR / "resume_profile_paths.local.yaml",
        CONFIG_DIR / "resume_profile_paths.example.yaml",
    ),
    "scoring_rules": PublicConfigSpec(
        "scoring_rules",
        CONFIG_DIR / "scoring_rules.local.yaml",
        CONFIG_DIR / "scoring_rules.example.yaml",
    ),
    "master_resume": PublicConfigSpec(
        "master_resume",
        TEMPLATES_DIR / "master_resume.yaml",
        TEMPLATES_DIR / "master_resume.example.yaml",
    ),
}


def setup_message(spec: PublicConfigSpec) -> str:
    return (
        f"Missing local config: {spec.local_path}. Run "
        "python -m job_pipeline.setup_wizard --init to create local files, "
        f"or copy {spec.example_path} and edit it."
    )


def example_path_for(path: Path) -> Path:
    path = Path(path)
    for spec in PUBLIC_CONFIGS.values():
        if path.resolve() == spec.local_path.resolve():
            return spec.example_path
    name = path.name
    if name.endswith(".local.yaml"):
        return path.with_name(name.replace(".local.yaml", ".example.yaml"))
    if name.endswith(".yaml"):
        return path.with_name(name.replace(".yaml", ".example.yaml"))
    return path.with_suffix(path.suffix + ".example")


def load_path_with_fallback(path: Path, *, required: bool = False) -> Any:
    path = Path(path)
    if path.exists():
        return load_yaml(path)
    example = example_path_for(path)
    if example.exists():
        return load_yaml(example)
    if required:
        raise RuntimeError(f"Missing required config: {path}. Run python -m job_pipeline.setup_wizard --init.")
    return {}


def resolve_public_config_path(name: str) -> Path:
    spec = PUBLIC_CONFIGS[name]
    return spec.local_path if spec.local_path.exists() else spec.example_path


def load_public_config(name: str, *, required: bool | None = None) -> Any:
    spec = PUBLIC_CONFIGS[name]
    required = spec.required if required is None else required
    if spec.local_path.exists():
        return load_yaml(spec.local_path)
    if spec.example_path.exists():
        return load_yaml(spec.example_path)
    if required:
        raise RuntimeError(setup_message(spec))
    return {}


def public_config_status() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for spec in PUBLIC_CONFIGS.values():
        active = spec.local_path if spec.local_path.exists() else spec.example_path
        rows.append(
            {
                "name": spec.name,
                "local_path": str(spec.local_path),
                "example_path": str(spec.example_path),
                "local_exists": spec.local_path.exists(),
                "example_exists": spec.example_path.exists(),
                "active_path": str(active) if active.exists() else "",
                "using_example": not spec.local_path.exists() and spec.example_path.exists(),
            }
        )
    return rows
