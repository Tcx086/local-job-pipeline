from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..utils import PROJECT_ROOT, load_yaml


def _as_path(root: Path, value: Any, default: str) -> Path:
    text = str(value or default)
    path = Path(text)
    return path if path.is_absolute() else root / path


@dataclass(frozen=True)
class PathRegistry:
    project_root: Path
    config_dir: Path
    local_resources_dir: Path
    resources_dir: Path
    generated_dir: Path
    data_dir: Path
    db_path: Path
    legacy_db_path: Path
    _config: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_project_root(
        cls,
        project_root: Path | None = None,
        config_path: Path | None = None,
    ) -> "PathRegistry":
        root = (project_root or PROJECT_ROOT).resolve()
        cfg_path = config_path or root / "config" / "paths.yaml"
        if not cfg_path.is_absolute():
            cfg_path = root / cfg_path
        config: dict[str, Any] = {}
        if cfg_path.exists():
            loaded = load_yaml(cfg_path)
            config = loaded if isinstance(loaded, dict) else {}
        legacy = config.get("legacy") if isinstance(config.get("legacy"), dict) else {}
        return cls(
            project_root=root,
            config_dir=root / "config",
            local_resources_dir=_as_path(root, config.get("local_resources_dir"), "local_resources"),
            resources_dir=_as_path(root, config.get("resources_dir"), "resources"),
            generated_dir=_as_path(root, config.get("generated_dir"), "generated"),
            data_dir=_as_path(root, config.get("data_dir"), "data"),
            db_path=_as_path(root, config.get("db_path"), "data/db/job_pipeline.sqlite"),
            legacy_db_path=_as_path(root, legacy.get("legacy_db_path"), "data/job_pipeline.sqlite"),
            _config=config,
        )

    def resolve_resource(self, *parts: str | Path) -> Path:
        return self.resources_dir.joinpath(*[Path(part) for part in parts])

    def resolve_generated(self, *parts: str | Path) -> Path:
        return self.generated_dir.joinpath(*[Path(part) for part in parts])

    def resolve_data(self, *parts: str | Path) -> Path:
        return self.data_dir.joinpath(*[Path(part) for part in parts])

    def resource_path(self, key: str, legacy: Path | None = None) -> Path:
        resources = self._config.get("resources") if isinstance(self._config.get("resources"), dict) else {}
        if key in resources:
            return _as_path(self.project_root, resources[key], f"resources/{key}")
        if legacy is not None:
            return legacy
        return self.resolve_resource(*Path(key).parts)

    def existing_resource_path(self, key: str, legacy: Path | None = None) -> Path:
        path = self.resource_path(key, legacy=None)
        if path.exists():
            return path
        if legacy is not None and legacy.exists():
            return legacy
        return path

    def effective_db_path(self) -> Path:
        if self.db_path.exists():
            return self.db_path
        if self.legacy_db_path.exists():
            return self.legacy_db_path
        return self.db_path
