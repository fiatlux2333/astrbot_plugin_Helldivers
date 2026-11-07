"""Check documented release requirements without importing plugin runtime code.

Usage: python3 scripts/check_release.py [project directory or release ZIP]
Build-only dependencies: PyYAML and packaging (pip's vendored copy also works).
This is a release preflight, not a replacement for marketplace security review.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import yaml

try:
    from packaging.specifiers import InvalidSpecifier, SpecifierSet
except ImportError:
    from pip._vendor.packaging.specifiers import InvalidSpecifier, SpecifierSet


MAX_RELEASE_BYTES = 16_000_000  # Conservative decimal interpretation of the 16 MB limit.
RUNTIME_DIRS = frozenset({"clients", "core", "renderers"})
REQUIRED_FILES = frozenset({"main.py", "__init__.py", "metadata.yaml", "requirements.txt", "README.md", "LICENSE", "core/plugin_info.py", "_conf_schema.json"})
PLATFORMS = frozenset({
    "aiocqhttp", "qq_official", "qq_official_webhook", "telegram", "wecom",
    "wecom_ai_bot", "lark", "dingtalk", "discord", "slack", "kook", "vocechat",
    "weixin_official_account", "weixin_oc", "satori", "misskey", "line", "matrix",
    "mattermost", "webchat",
})
SEMVER = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
                    r"(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?"
                    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?")


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f"duplicate metadata key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def runtime_file(name: str) -> bool:
    path = PurePosixPath(name)
    return path.suffix == ".py" and (len(path.parts) == 1 or path.parts[0] in RUNTIME_DIRS)


def check_logging(name: str, content: bytes) -> list[str]:
    tree = ast.parse(content, filename=name)
    errors = []
    for node in ast.walk(tree):
        modules = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                   else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
        if any(module == "logging" or module.startswith("logging.") for module in modules):
            errors.append(f"{name}:{node.lineno}: standard-library logging import is forbidden")
        if isinstance(node, ast.Call):
            function = node.func
            if (isinstance(function, ast.Attribute) and function.attr == "getLogger") or (
                isinstance(function, ast.Name) and function.id == "getLogger"
            ):
                errors.append(f"{name}:{node.lineno}: getLogger is forbidden")
    uses_logger = any(isinstance(node, ast.Name) and node.id in {"logger", "_logger"} for node in ast.walk(tree))
    official_import = any(isinstance(node, ast.ImportFrom) and node.module == "astrbot.api"
                          and any(alias.name == "logger" and alias.asname in {None, "logger"} for alias in node.names)
                          for node in tree.body)
    if uses_logger and not official_import:
        errors.append(f"{name}: logger must be imported directly with 'from astrbot.api import logger'")
    return errors


def check_files(files: dict[str, bytes], *, archive_bytes: int | None = None) -> dict:
    missing = REQUIRED_FILES - files.keys()
    if missing:
        raise ValueError(f"missing release files: {', '.join(sorted(missing))}")
    if archive_bytes is not None and archive_bytes > MAX_RELEASE_BYTES:
        raise ValueError("release ZIP exceeds 16 MB")
    metadata = yaml.load(files["metadata.yaml"], Loader=UniqueKeyLoader)
    if not isinstance(metadata, dict):
        raise ValueError("metadata.yaml must be a mapping")
    for field in ("name", "display_name", "desc", "version", "author", "repo"):
        if not isinstance(metadata.get(field), str) or not metadata[field].strip():
            raise ValueError(f"metadata {field} must be a nonempty string")
    name, version = metadata["name"], metadata["version"]
    if not re.fullmatch(r"astrbot_plugin_[A-Za-z0-9_]+", name) or name == "astrbot_plugin_example":
        raise ValueError("invalid or placeholder plugin name")
    if not SEMVER.fullmatch(version):
        raise ValueError("metadata version must be a semantic version without a v prefix")
    repo = urlsplit(metadata["repo"])
    if repo.scheme != "https" or repo.hostname != "github.com" or repo.username or repo.password or repo.query or repo.fragment:
        raise ValueError("repo must be the HTTPS GitHub repository URL")
    parts = repo.path.strip("/").removesuffix(".git").split("/")
    if len(parts) != 2 or parts[0] in {"your-name", "example"} or parts[1].casefold() != name.casefold():
        raise ValueError("repo must identify this plugin, without template placeholders")
    for field in ("short_desc", "social_link"):
        if field in metadata and not isinstance(metadata[field], str):
            raise ValueError(f"metadata {field} must be a string")
    if metadata.get("social_link") and urlsplit(metadata["social_link"]).scheme not in {"https", "http"}:
        raise ValueError("social_link must be a web URL")
    if "astrbot_version" in metadata:
        value = metadata["astrbot_version"]
        if not isinstance(value, str) or "v" in value.lower():
            raise ValueError("astrbot_version must be a PEP 440 range without v prefixes")
        try:
            SpecifierSet(value)
        except InvalidSpecifier as exc:
            raise ValueError("invalid astrbot_version range") from exc
    for field in ("support_platforms", "tags"):
        if field in metadata and (not isinstance(metadata[field], list) or
                                  not all(isinstance(v, str) and v.strip() for v in metadata[field])):
            raise ValueError(f"metadata {field} must be a list of strings")
    if set(metadata.get("support_platforms", [])) - PLATFORMS:
        raise ValueError("unknown platform adapter ID")

    info = ast.parse(files["core/plugin_info.py"])
    constants = {target.id: node.value.value for node in info.body if isinstance(node, ast.Assign)
                 and isinstance(node.value, ast.Constant) for target in node.targets if isinstance(target, ast.Name)}
    if constants.get("PLUGIN_NAME") != name or constants.get("PLUGIN_AUTHOR") != metadata["author"]:
        raise ValueError("runtime identity differs from metadata")
    if constants.get("PLUGIN_VERSION") != f"v{version}":
        raise ValueError("runtime version differs from metadata")
    schema = json.loads(files["_conf_schema.json"])
    if schema["api_user_agent"]["default"] != f"{name}/{version}":
        raise ValueError("default User-Agent differs from metadata version")
    if f"`v{version}`" not in files["README.md"].decode("utf-8"):
        raise ValueError("README does not identify the current version")
    errors = [error for filename, content in files.items() if runtime_file(filename)
              for error in check_logging(filename, content)]
    if errors:
        raise ValueError("\n".join(errors))
    notes = []
    if name != name.lower():
        notes.append("Existing mixed-case plugin ID retained for configuration/data continuity; new repository names should be lowercase.")
    return {"version": version, "name": name, "metadata": "passed", "runtime_logging": "passed",
            "runtime_python_files": sum(runtime_file(filename) for filename in files),
            "archive_bytes": archive_bytes, "notes": notes}


def check_path(path: Path) -> dict:
    if path.is_dir():
        paths = [path / name for name in REQUIRED_FILES if (path / name).is_file()]
        paths.extend(path.glob("*.py"))
        for directory in RUNTIME_DIRS:
            paths.extend(p for p in (path / directory).rglob("*.py") if "__pycache__" not in p.parts)
        return check_files({p.relative_to(path).as_posix(): p.read_bytes() for p in paths})
    if path.stat().st_size > MAX_RELEASE_BYTES:
        raise ValueError("release ZIP exceeds 16 MB")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("duplicate archive entries")
        for name in names:
            parts = PurePosixPath(name).parts
            if not parts or name.startswith("/") or ".." in parts or "\\" in name:
                raise ValueError("unsafe archive path")
            if any(part.startswith(".") or part in {"__pycache__", "node_modules", "tests", "dist", "data"} for part in parts):
                raise ValueError(f"non-release file in ZIP: {name}")
        return check_files({name: archive.read(name) for name in names if not name.endswith("/")}, archive_bytes=path.stat().st_size)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        report = check_path(args.path)
    except (ValueError, OSError, SyntaxError, yaml.YAMLError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Release check failed: {exc}\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
