from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from config import TEMPLATE_DIR, TEMPLATE_PATH

DEFAULT_TEMPLATE_NAME = "default"
SUPPORTED_TEMPLATE_SUFFIXES = (".xlsx", ".xlsm")
DEFAULT_TEMPLATE_FILENAME = "upload_template"


class TemplateProfileError(RuntimeError):
    pass


@dataclass(frozen=True)
class TemplateProfile:
    name: str
    template_path: Path


def discover_template_profiles(template_dir: Path = TEMPLATE_DIR) -> list[TemplateProfile]:
    if not template_dir.exists():
        return []

    profiles = [
        TemplateProfile(
            name=template_profile_name(path, template_dir),
            template_path=path,
        )
        for path in sorted(template_dir.rglob("*"))
        if is_supported_template_file(path)
    ]

    return profiles


def resolve_template_profile(
    template_identifier: str | None,
    template_dir: Path = TEMPLATE_DIR,
) -> TemplateProfile:
    raw_identifier = template_identifier.strip() if template_identifier else ""
    identifier = normalize_identifier(raw_identifier)
    if not identifier or identifier == DEFAULT_TEMPLATE_NAME:
        return TemplateProfile(
            name=DEFAULT_TEMPLATE_NAME,
            template_path=resolve_default_template_path(template_dir),
        )

    path_profile = resolve_template_path(raw_identifier, identifier, template_dir)
    if path_profile:
        return path_profile

    profiles = discover_template_profiles(template_dir)
    for profile in profiles:
        if identifier in template_aliases(profile, template_dir):
            return profile

    available = ", ".join(profile.name for profile in profiles) or "none"
    raise TemplateProfileError(
        f"Unknown template '{template_identifier}'. Available templates: {available}"
    )


def resolve_template_path(
    raw_identifier: str,
    normalized_identifier: str,
    template_dir: Path,
) -> TemplateProfile | None:
    candidate = Path(raw_identifier).expanduser()
    if candidate.suffix.lower() in SUPPORTED_TEMPLATE_SUFFIXES:
        if candidate.is_absolute():
            path = candidate
        elif candidate.exists():
            path = candidate.resolve()
        elif candidate.parts and candidate.parts[0] == template_dir.name:
            path = template_dir.parent / candidate
        else:
            path = template_dir / candidate
        return TemplateProfile(name=template_profile_name(path, template_dir), template_path=path)

    for suffix in SUPPORTED_TEMPLATE_SUFFIXES:
        direct_template = template_dir / f"{normalized_identifier}{suffix}"
        if direct_template.exists():
            return TemplateProfile(
                name=template_profile_name(direct_template, template_dir),
                template_path=direct_template,
            )

    for suffix in SUPPORTED_TEMPLATE_SUFFIXES:
        folder_template = template_dir / normalized_identifier / f"{DEFAULT_TEMPLATE_FILENAME}{suffix}"
        if folder_template.exists():
            return TemplateProfile(
                name=template_profile_name(folder_template, template_dir),
                template_path=folder_template,
            )

    return None


def resolve_default_template_path(template_dir: Path = TEMPLATE_DIR) -> Path:
    configured_template = (
        TEMPLATE_PATH
        if template_dir == TEMPLATE_DIR
        else template_dir / TEMPLATE_PATH.name
    )
    candidates = [configured_template]

    for suffix in SUPPORTED_TEMPLATE_SUFFIXES:
        candidate = template_dir / f"{DEFAULT_TEMPLATE_FILENAME}{suffix}"
        if candidate not in candidates:
            candidates.append(candidate)

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return configured_template


def template_profile_name(path: Path, template_dir: Path = TEMPLATE_DIR) -> str:
    try:
        relative_path = path.relative_to(template_dir)
    except ValueError:
        return path.stem

    return relative_path.with_suffix("").as_posix()


def template_aliases(profile: TemplateProfile, template_dir: Path = TEMPLATE_DIR) -> set[str]:
    aliases = {
        normalize_identifier(profile.name),
        normalize_identifier(profile.template_path.name),
        normalize_identifier(profile.template_path.stem),
    }

    if profile.template_path == resolve_default_template_path(template_dir):
        aliases.add(DEFAULT_TEMPLATE_NAME)

    try:
        relative_path = profile.template_path.relative_to(template_dir)
    except ValueError:
        return aliases

    if (
        relative_path.stem == DEFAULT_TEMPLATE_FILENAME
        and relative_path.suffix.lower() in SUPPORTED_TEMPLATE_SUFFIXES
        and len(relative_path.parts) > 1
    ):
        aliases.add(normalize_identifier(relative_path.parts[0]))

    return aliases


def is_supported_template_file(path: Path) -> bool:
    return (
        path.is_file()
        and path.suffix.lower() in SUPPORTED_TEMPLATE_SUFFIXES
        and not path.name.startswith("~$")
    )


def normalize_identifier(value: str | None) -> str:
    if not value:
        return ""

    normalized = value.strip().replace("\\", "/")
    for suffix in SUPPORTED_TEMPLATE_SUFFIXES:
        if normalized.lower().endswith(suffix):
            normalized = normalized[: -len(suffix)]
            break

    return normalized
