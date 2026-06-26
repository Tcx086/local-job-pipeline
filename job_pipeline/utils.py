from __future__ import annotations

import csv
import hashlib
import html
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
REPORTS_DIR = DATA_DIR / "reports"
RESUMES_DIR = DATA_DIR / "resumes"
LOGS_DIR = DATA_DIR / "logs"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

STANDARD_FIELDS = [
    "job_id",
    "source",
    "title",
    "company",
    "location",
    "country",
    "date_posted",
    "job_type",
    "salary_min",
    "salary_max",
    "job_url",
    "apply_url",
    "description",
    "search_term_used",
    "collected_at",
]


def ensure_dirs() -> None:
    for path in [RAW_DIR, PROCESSED_DIR, REPORTS_DIR, RESUMES_DIR, LOGS_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def setup_logging(name: str = "job_pipeline", level: int = logging.INFO) -> logging.Logger:
    ensure_dirs()
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        logger.addHandler(stream)
        try:
            file_handler = logging.FileHandler(LOGS_DIR / "job_pipeline.log", encoding="utf-8")
            file_handler.setFormatter(fmt)
            logger.addHandler(file_handler)
        except OSError:
            logger.warning("File logging unavailable; continuing with console logging only.")
    return logger


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")



def _yaml_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"", "null", "Null", "NULL", "~"}:
        return None
    if value in {"true", "True", "TRUE"}:
        return True
    if value in {"false", "False", "FALSE"}:
        return False
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        inner = value[1:-1]
        try:
            return bytes(inner, "utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            return inner
    if value.startswith("[") or value.startswith("{"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _yaml_lines(text: str) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        rows.append((indent, raw.strip()))
    return rows


def _parse_simple_yaml(text: str) -> Any:
    rows = _yaml_lines(text)

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(rows):
            return {}, index
        if rows[index][1].startswith("- "):
            return parse_list(index, indent)
        return parse_dict(index, indent)

    def parse_dict(index: int, indent: int) -> tuple[dict[str, Any], int]:
        output: dict[str, Any] = {}
        while index < len(rows):
            current_indent, content = rows[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                break
            if content.startswith("- "):
                break
            key, sep, rest = content.partition(":")
            if not sep:
                index += 1
                continue
            key = key.strip().strip('"').strip("'")
            rest = rest.strip()
            index += 1
            if rest:
                output[key] = _yaml_scalar(rest)
            else:
                if index < len(rows) and rows[index][0] > current_indent:
                    output[key], index = parse_block(index, rows[index][0])
                else:
                    output[key] = {}
        return output, index

    def parse_list(index: int, indent: int) -> tuple[list[Any], int]:
        output: list[Any] = []
        while index < len(rows):
            current_indent, content = rows[index]
            if current_indent < indent or not content.startswith("- "):
                break
            item = content[2:].strip()
            index += 1
            if not item:
                if index < len(rows) and rows[index][0] > current_indent:
                    value, index = parse_block(index, rows[index][0])
                else:
                    value = None
                output.append(value)
                continue
            if ":" in item:
                key, _, rest = item.partition(":")
                item_dict: dict[str, Any] = {key.strip().strip('"').strip("'"): _yaml_scalar(rest.strip()) if rest.strip() else {}}
                if index < len(rows) and rows[index][0] > current_indent:
                    nested, index = parse_dict(index, rows[index][0])
                    item_dict.update(nested)
                output.append(item_dict)
            else:
                output.append(_yaml_scalar(item))
        return output, index

    parsed, _ = parse_block(0, rows[0][0] if rows else 0)
    return parsed

def load_yaml(path: Path) -> Any:
    """Load YAML, with JSON and a small YAML-subset fallback for minimal installs."""
    text = read_text(path)
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except ModuleNotFoundError:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return _parse_simple_yaml(text)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not fieldnames:
        seen: list[str] = []
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.append(key)
        fieldnames = seen
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def stable_id(*parts: Any) -> str:
    raw = "|".join(normalize_space(str(part or "")).lower() for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_text_escapes(value: Any) -> str:
    return re.sub(r"\\([`*_{}\[\]()#+\-.!&/])", r"\1", str(value or ""))


TAG_RE = re.compile(r"<[^>]+>")


def strip_html(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = TAG_RE.sub(" ", text)
    return normalize_space(normalize_text_escapes(text))


def slugify(value: Any, max_len: int = 80) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return (slug[:max_len].strip("_") or "item")


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def list_to_cell(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(v) for v in value if str(v).strip())
    return str(value or "")


def flatten_text(data: Any) -> str:
    if isinstance(data, dict):
        return " ".join(flatten_text(v) for v in data.values())
    if isinstance(data, list):
        return " ".join(flatten_text(v) for v in data)
    return str(data or "")


@dataclass(frozen=True)
class SearchRequest:
    country: str
    search_term: str
    location: str


def iter_search_requests(config: dict[str, Any]) -> Iterable[SearchRequest]:
    groups = config.get("countries", {})
    for country, payload in groups.items():
        terms = payload.get("search_terms", [])
        locations = payload.get("locations", [])
        for term in terms:
            for location in locations:
                yield SearchRequest(country=country, search_term=term, location=location)
