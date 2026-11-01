#!/usr/bin/env bash
# Build an uploadable AstrBot plugin ZIP using only Bash and Python 3.11+.
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if [[ $# -ne 0 ]]; then
    printf 'Usage: bash pack.sh\nOptional: PYTHON_BIN=/path/to/python bash pack.sh\n' >&2
    exit 2
fi

python_bin="${PYTHON_BIN:-}"
if [[ -n "$python_bin" ]]; then
    "$python_bin" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || {
        printf 'ERROR: PYTHON_BIN must point to Python 3.11 or newer.\n' >&2
        exit 1
    }
else
    for candidate in .venv/bin/python .venv/Scripts/python.exe python3 python; do
        if "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
            python_bin="$candidate"
            break
        fi
    done
    if [[ -z "$python_bin" ]]; then
        printf 'ERROR: Python 3.11+ is required. Set PYTHON_BIN to its executable.\n' >&2
        exit 1
    fi
fi

exec "$python_bin" - <<'PY'
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path.cwd().resolve()
PLUGIN = "astrbot_plugin_Helldivers"
OUTPUT_DIR = ROOT / "dist"
OUTPUT = OUTPUT_DIR / f"{PLUGIN}.zip"
ROOT_FILES = (
    "__init__.py", "main.py", "services.py", "metadata.yaml",
    "_conf_schema.json", "requirements.txt", "README.md", "LICENSE", "logo.png",
)
MODULE_DIRS = ("clients", "core", "renderers")
SKIP_DIRS = {"__pycache__", "data", "tests", "node_modules"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp", ".bak", ".zip"}


def require_file(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Missing, empty or symlinked required file: {path}")


def collect_directory(directory, *, python_only=False):
    base = ROOT / directory
    if base.is_symlink() or not base.is_dir():
        raise ValueError(f"Missing or symlinked source directory: {base}")
    collected = []
    for parent, dirs, files in os.walk(base, followlinks=False):
        dirs[:] = sorted(
            name for name in dirs
            if not name.startswith(".") and name not in SKIP_DIRS
        )
        for name in dirs + files:
            if (Path(parent) / name).is_symlink():
                raise ValueError(f"Symlinks are not packaged: {Path(parent) / name}")
        for name in sorted(files):
            path = Path(parent) / name
            if name.startswith(".") or path.suffix.lower() in SKIP_SUFFIXES:
                continue
            if name.endswith(("~", ".tmp.png")) or "_config." in name:
                continue
            if python_only and path.suffix != ".py":
                continue
            collected.append(path)
    return collected


def build():
    paths = [ROOT / name for name in ROOT_FILES]
    paths.extend(ROOT / directory / "__init__.py" for directory in MODULE_DIRS)
    paths.extend((
        ROOT / "clients/jerry_map.py", ROOT / "clients/jerry_wiki.py",
        ROOT / "assets/manifest.json", ROOT / "assets/LICENSES.md",
    ))
    for path in paths:
        require_file(path)
    for directory in MODULE_DIRS:
        paths.extend(collect_directory(directory, python_only=True))
    paths.extend(collect_directory("assets"))
    paths = sorted(set(paths), key=lambda path: path.relative_to(ROOT).as_posix())

    schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
    if not isinstance(schema, dict) or not schema:
        raise ValueError("_conf_schema.json must contain a nonempty JSON object")
    for key, field in schema.items():
        if not isinstance(field, dict) or not isinstance(field.get("type"), str):
            raise ValueError(f"Invalid config schema field: {key}")
    for path in paths:
        if path.suffix == ".py":
            compile(path.read_bytes(), str(path), "exec")
        elif path.suffix == ".json":
            json.loads(path.read_text(encoding="utf-8"))

    if OUTPUT_DIR.is_symlink() or OUTPUT.is_symlink():
        raise ValueError("Refusing a symlinked output directory or ZIP")
    OUTPUT_DIR.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=OUTPUT_DIR, prefix=".pack-", suffix=".tmp", delete=False,
    ) as handle:
        temporary = Path(handle.name)
    try:
        expected = []
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9,
        ) as archive:
            # One plugin folder, independent of the checkout's name or platform.
            for path in paths:
                name = f"{PLUGIN}/{path.relative_to(ROOT).as_posix()}"
                expected.append(name)
                info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(
                    info, path.read_bytes(),
                    compress_type=zipfile.ZIP_DEFLATED, compresslevel=9,
                )
        with zipfile.ZipFile(temporary) as archive:
            if archive.namelist() != expected or archive.testzip() is not None:
                raise ValueError("ZIP content or CRC validation failed")
        size = temporary.stat().st_size
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        os.replace(temporary, OUTPUT)
    finally:
        temporary.unlink(missing_ok=True)

    print(f"ZIP: {OUTPUT}")
    print(f"Size: {size / 1048576:.2f} MiB ({size:,} bytes)")
    print(f"Files: {len(expected)}")
    print(f"SHA256: {digest}")
    print("Validated: Python syntax, JSON files, ZIP members and CRC.")
    print("Not bundled: virtualenv, tests, caches, local config or Chromium.")


try:
    build()
except Exception as error:
    print(f"ERROR: {error}", file=sys.stderr)
    sys.exit(1)
PY
