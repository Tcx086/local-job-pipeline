from __future__ import annotations

from pathlib import Path
from typing import Any

from .utils import load_yaml
from .workspace import PathRegistry

RESOURCE_DEFAULTS = {
    "common_answers": Path("resources/templates/answer_packs/common_answers.yaml"),
    "cover_letter_human_templates": Path("resources/templates/cover_letters/human_templates.yaml"),
    "cover_letter_configurable_templates": Path("resources/templates/cover_letters/configurable_templates.yaml"),
    "sensitive_fields_policy": Path("resources/policies/sensitive_fields_policy.yaml"),
}

LEGACY_DEFAULTS = {
    "candidate_master_profile": Path("templates/master_resume.yaml"),
    "common_answers": Path("config/common_answers.yaml"),
    "cover_letter_human_templates": Path("config/cover_letter_human_templates.yaml"),
    "cover_letter_configurable_templates": Path("config/cover_letter_templates.yaml"),
    "sensitive_fields_policy": Path("config/sensitive_fields_policy.yaml"),
}

CANDIDATE_MASTER_ERROR = (
    "Candidate master profile not found. Copy "
    "resources/candidate/master_profile.example.yaml to "
    "local_resources/candidate/master_profile.yaml and fill it locally."
)


def _registry(paths: PathRegistry | None = None) -> PathRegistry:
    return paths or PathRegistry.from_project_root()


def _load_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = load_yaml(path)
    return data if isinstance(data, dict) else {}


def _project_path(registry: PathRegistry, value: str | Path | None, default: str | Path) -> Path:
    path = Path(value or default)
    return path if path.is_absolute() else registry.project_root / path


def _configured_resource_path(registry: PathRegistry, key: str, default: str | Path) -> Path:
    resources = registry._config.get("resources") if isinstance(registry._config.get("resources"), dict) else {}
    return _project_path(registry, resources.get(key), default)


def _resource(paths: PathRegistry | None, key: str) -> Path:
    registry = _registry(paths)
    resource_path = _configured_resource_path(registry, key, RESOURCE_DEFAULTS[key])
    legacy_path = registry.project_root / LEGACY_DEFAULTS[key]
    return resource_path if resource_path.exists() else legacy_path


def load_candidate_master(paths: PathRegistry | None = None, *, allow_example: bool = False) -> dict[str, Any]:
    registry = _registry(paths)
    candidates = [
        _configured_resource_path(registry, "candidate_master_profile", "local_resources/candidate/master_profile.yaml"),
        registry.project_root / "resources" / "candidate" / "master_profile.yaml",
        registry.project_root / LEGACY_DEFAULTS["candidate_master_profile"],
    ]
    if allow_example:
        candidates.append(
            _configured_resource_path(
                registry,
                "candidate_master_profile_example",
                "resources/candidate/master_profile.example.yaml",
            )
        )
    for path in candidates:
        data = _load_dict(path)
        if data:
            return data
    raise FileNotFoundError(CANDIDATE_MASTER_ERROR)


def load_common_answers(paths: PathRegistry | None = None) -> dict[str, Any]:
    return _load_dict(_resource(paths, "common_answers"))


def load_cover_letter_human_templates(paths: PathRegistry | None = None) -> dict[str, Any]:
    return _load_dict(_resource(paths, "cover_letter_human_templates"))


def load_cover_letter_configurable_templates(paths: PathRegistry | None = None) -> dict[str, Any]:
    return _load_dict(_resource(paths, "cover_letter_configurable_templates"))


def load_sensitive_policy(paths: PathRegistry | None = None) -> dict[str, Any]:
    return _load_dict(_resource(paths, "sensitive_fields_policy"))


def load_role_profile(profile_name: str, paths: PathRegistry | None = None) -> dict[str, Any]:
    registry = _registry(paths)
    filename = f"{profile_name}.yaml"
    local_dir = _configured_resource_path(registry, "role_profiles_dir", "local_resources/role_profiles")
    examples_dir = _configured_resource_path(registry, "role_profiles_examples_dir", "resources/role_profiles")
    candidates = [
        local_dir / filename,
        registry.project_root / "resources" / "role_profiles" / filename,
        examples_dir / f"{profile_name}.example.yaml",
        registry.project_root / "templates" / "resume_profiles" / filename,
    ]
    for path in candidates:
        data = _load_dict(path)
        if data:
            return data
    return {}