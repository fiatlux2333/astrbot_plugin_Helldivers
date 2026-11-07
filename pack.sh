#!/usr/bin/env bash
# Package only runtime files, docs and assets; retain previous release artifacts.
set -euo pipefail
cd "$(dirname "$0")"
python3 - <<'PY'
import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from scripts.check_release import MAX_RELEASE_BYTES, check_path

root = Path.cwd()
check_path(root)
version = re.search(r'^version:\s*[\"\']?v?([0-9]+\.[0-9]+\.[0-9]+)', (root / 'metadata.yaml').read_text(), re.M).group(1)
assert f'PLUGIN_VERSION = "v{version}"' in (root / 'core/plugin_info.py').read_text(), 'version mismatch'
output = root / 'dist'
output.mkdir(exist_ok=True)
files = [root / name for name in ('README.md', 'LICENSE', 'services.py', '_conf_schema.json', '__init__.py', 'metadata.yaml', 'logo.png', 'main.py', 'requirements.txt')]
for folder in ('assets', 'clients', 'core', 'renderers', 'docs'):
    for path in (root / folder).rglob('*'):
        parts = path.relative_to(root).parts
        if any(part.startswith('.') or part == '__pycache__' for part in parts):
            continue
        if path.is_symlink():
            raise ValueError(f'Unexpected symlink in package: {path.relative_to(root)}')
        if path.is_file() and (folder in {'assets', 'docs'} or path.suffix == '.py'):
            files.append(path)
assert all(path.is_file() for path in files), 'missing required release file'
target = output / f'astrbot_plugin_Helldivers-v{version}.zip'
with tempfile.NamedTemporaryFile(dir=output, suffix='.tmp', delete=False) as handle:
    temporary = Path(handle.name)
try:
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files):
            archive.write(path, path.relative_to(root).as_posix())
    assert temporary.stat().st_size <= MAX_RELEASE_BYTES, 'package exceeds 16 MB'
    with zipfile.ZipFile(temporary) as archive:
        assert archive.testzip() is None, 'ZIP integrity check failed'
        for name in archive.namelist():
            if name.endswith('.py'):
                compile(archive.read(name), name, 'exec')
    check_path(temporary)
    digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
    if target.exists():
        previous = hashlib.sha256(target.read_bytes()).hexdigest()
        if previous != digest:
            backup = output / 'archive' / f'{target.stem}-{previous[:12]}.zip'
            backup.parent.mkdir(exist_ok=True)
            if not backup.exists():
                shutil.copy2(target, backup)
    temporary.replace(target)
    generic = output / 'astrbot_plugin_Helldivers.zip'
    staged = generic.with_suffix('.tmp')
    shutil.copy2(target, staged)
    staged.replace(generic)
    manifest = []
    for path in sorted(output.glob('astrbot_plugin_Helldivers-v*.zip')):
        with zipfile.ZipFile(path) as archive:
            count = len(archive.namelist())
        manifest.append({'file': path.name, 'version': path.stem.split('-v')[-1],
                         'size_bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                         'file_count': count})
    staging = output / 'manifest.tmp'
    staging.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    staging.replace(output / 'manifest.json')
    print(json.dumps({'file': str(target), 'version': version, 'size_bytes': target.stat().st_size,
                      'sha256': digest, 'file_count': len(files)}, ensure_ascii=False))
finally:
    temporary.unlink(missing_ok=True)
PY
