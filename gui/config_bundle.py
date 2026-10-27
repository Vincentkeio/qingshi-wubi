"""Portable, checked configuration snapshots. No credentials or learned DBs."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import io
import json
import os
import stat
import tempfile
import zipfile
from pathlib import PureWindowsPath
from fixed_order import atomic_write, ensure_fixed_order

APP_ID = 'QingshiWubi'
FORMAT = 1
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
SCHEMAS = ('wubi86', 'wubi98', 'wubi06')
FILES = {'default.custom.yaml', 'weasel.custom.yaml', 'custom_phrase.txt',
         'qingshi_pin_history.tsv'} | {
    schema + suffix for schema in SCHEMAS for suffix in
    ('.schema.yaml', '.dict.yaml', '.custom.yaml')
} | {'shadow_' + schema + '.yaml' for schema in SCHEMAS}


def allowed(name):
    if not isinstance(name, str) or '\\' in name or ':' in name or name.startswith('/'):
        return False
    parts = name.split('/')
    if name.casefold() in {item.casefold() for item in FILES} and name not in FILES:
        return False
    if PureWindowsPath(name).is_reserved():
        return False
    if any(part in ('', '.', '..') or part.endswith(('.', ' ')) for part in parts) or len(parts) > 6:
        return False
    if any(part.lower() in ('build', 'backups', 'sync', '.git') or '.userdb' in part.lower() for part in parts):
        return False
    return name in FILES or name.endswith(('.dict.yaml', '.schema.yaml', '.custom.yaml')) or (
        len(parts) == 1 and name.startswith('shadow_') and name.endswith('.yaml'))


def configuration_files(directory):
    result = set(FILES)
    for current, directories, names in os.walk(directory, followlinks=False):
        directories[:] = [name for name in directories
            if name.lower() not in ('build','backups','sync','.git') and '.userdb' not in name.lower()
            and not (Path(current) / name).lstat().st_file_attributes & 0x400]
        for name in names:
            relative = (Path(current) / name).relative_to(directory).as_posix()
            if allowed(relative):
                result.add(relative)
    return result


def snapshot(directory, shift_letter_direct=True):
    directory = Path(directory)
    entries = {}
    for name in sorted(configuration_files(directory)):
        path = directory / name
        if path.is_symlink() or (path.exists() and path.lstat().st_file_attributes & 0x400):
            raise ValueError('配置目录包含文件链接，未导出：' + name)
        if path.is_file():
            if path.stat().st_size > MAX_FILE:
                raise ValueError('配置文件过大：' + name)
            data = path.read_bytes()
            if len(data) > MAX_FILE:
                raise ValueError('配置文件过大：' + name)
            entries[name] = data
    if len(entries) > 256:
        raise ValueError('配置文件数量超过备份限制')
    if sum(map(len, entries.values())) > MAX_TOTAL:
        raise ValueError('配置备份超过大小限制')
    manifest = {'app_id': APP_ID, 'format': FORMAT,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'preferences': {'shift_letter_direct': bool(shift_letter_direct)},
        'files': {name: {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                  for name, data in entries.items()}}
    from update_checker import UpdateChecker
    manifest['preferences']['automatic_updates'] = UpdateChecker(directory).settings().get('automatic', True) is not False
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        for name, data in entries.items():
            archive.writestr(name, data)
    return output.getvalue()


def inspect(data):
    if len(data) > MAX_TOTAL:
        raise ValueError('备份文件过大')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) > 257 or len(names) != len({name.casefold() for name in names}):
                raise ValueError('备份包含重复或过多文件')
            if 'manifest.json' not in names or any(not allowed(name) for name in names if name != 'manifest.json'):
                raise ValueError('备份包含不支持的文件或路径')
            if sum(info.file_size for info in infos) > MAX_TOTAL or any(info.file_size > MAX_FILE for info in infos):
                raise ValueError('解压后的配置超过大小限制')
            if any(stat.S_ISLNK(info.external_attr >> 16) for info in infos):
                raise ValueError('备份中不允许包含文件链接')
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('app_id') != APP_ID or manifest.get('format') != FORMAT:
                raise ValueError('这不是受支持的青石配置备份')
            files = manifest.get('files')
            if not isinstance(files, dict) or set(files) != set(names) - {'manifest.json'}:
                raise ValueError('备份文件清单不匹配')
            preference = manifest.get('preferences', {}).get('shift_letter_direct', True)
            if not isinstance(preference, bool):
                raise ValueError('备份选项无效')
            if not isinstance(manifest.get('preferences', {}).get('automatic_updates', True), bool):
                raise ValueError('更新选项无效')
            entries = {}
            for name, metadata in files.items():
                value = archive.read(name)
                if len(value) != metadata['size'] or hashlib.sha256(value).hexdigest() != metadata['sha256']:
                    raise ValueError('备份校验失败：' + name)
                value.decode('utf-8-sig')
                entries[name] = value
            return manifest, entries
    except (zipfile.BadZipFile, json.JSONDecodeError, KeyError, TypeError, UnicodeError) as error:
        raise ValueError('备份文件损坏或格式无效') from error


def restore(directory, data, shift_letter_direct=True):
    manifest, entries = inspect(data)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # Validate every target before changing any file; never follow a link.
    for parent in (directory, *directory.parents):
        if parent.exists() and parent.lstat().st_file_attributes & 0x400:
            raise ValueError('配置目录包含链接，未导入')
    previous = {}
    existing = configuration_files(directory)
    folded = {name.casefold(): name for name in existing}
    if any(name.casefold() in folded and folded[name.casefold()] != name for name in entries):
        raise ValueError('备份与本机的词库文件名大小写冲突，请先统一文件名')
    managed = existing | set(entries)
    for name in managed:
        path = directory / name
        for parent in path.parents:
            if parent == directory:
                break
            if parent.exists() and parent.lstat().st_file_attributes & 0x400:
                raise ValueError('配置文件目录包含链接：' + name)
        if path.exists() and (path.is_dir() or path.lstat().st_file_attributes & 0x400):
            raise ValueError('配置路径不是普通文件：' + name)
        previous[name] = path.read_bytes() if path.exists() else None
    # Normalize/validate all YAML in a temporary directory before committing.
    with tempfile.TemporaryDirectory(prefix='qingshi-import-') as temporary:
        staged = Path(temporary)
        for name, value in entries.items():
            (staged / name).parent.mkdir(parents=True, exist_ok=True)
            (staged / name).write_bytes(value)
        import yaml
        for name in entries:
            if name.endswith('.yaml'):
                # Dict YAML has a TSV body after its document terminator.
                text = entries[name].decode('utf-8-sig')
                yaml.safe_load(text.split('\n...')[0] if name.endswith('.dict.yaml') else text)
        ensure_fixed_order(staged)
        for path in staged.rglob('*'):
            if path.is_file():
                entries[path.relative_to(staged).as_posix()] = path.read_bytes()
        managed |= set(entries)
        for name in entries:
            previous.setdefault(name, None)
    backup_dir = directory / 'backups'
    if backup_dir.exists() and backup_dir.lstat().st_file_attributes & 0x400:
        raise ValueError('备份目录包含链接，未导入')
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = backup_dir / ('导入前-' + stamp + '.qingshi.zip')
    atomic_write(backup, snapshot(directory, shift_letter_direct))
    try:
        for name in managed:
            path = directory / name
            if name in entries:
                atomic_write(path, entries[name])
            elif path.exists():
                path.unlink()
    except BaseException:
        for name, value in previous.items():
            path = directory / name
            if value is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, value)
        raise
    return {'backup': str(backup), 'files': len(entries),
            'automatic_updates': manifest.get('preferences', {}).get('automatic_updates', True),
            'shift_letter_direct': manifest.get('preferences', {}).get('shift_letter_direct', True)}
