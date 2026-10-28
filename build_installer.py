"""Build the standalone x64 installer from checked local runtime outputs."""
from pathlib import Path
import hashlib
import json
import os
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent / 'work'
GUI = ROOT / 'gui'
OUTPUT = ROOT / 'weasel/output'

# package-deps 里的 PyQt6 是为 Python 3.11 编译的（sip.cp311-win_amd64.pyd）。
# 用 3.12/3.13 打包不会报错，但装出来的 exe 一启动就
# "ModuleNotFoundError: No module named 'PyQt6.sip'" —— 1.0.13 就是这么翻车的。
if sys.version_info[:2] != (3, 11):
    sys.exit(
        f'请用 Python 3.11 打包（当前 {sys.version_info.major}.{sys.version_info.minor}）：'
        'package-deps 里的 PyQt6 是 cp311 构建，版本不匹配会导致安装包启动即崩溃。')


def build_payload():
    entries = {}
    settings = ROOT / 'dist/QingshiSettings'
    if not (settings / 'QingshiSettings.exe').is_file():
        raise FileNotFoundError('Build the standalone settings center before creating the payload.')
    for path in settings.rglob('*'):
        if path.is_file():
            entries['runtime/settings/' + path.relative_to(settings).as_posix()] = path
    # WinSparkle.dll 不再打进安装包：小狼毫的更新模块已在 1.0.11 移除，exe 不再引用它。
    for name in ('WeaselServer.exe', 'WeaselDeployer.exe', 'weaselx64.dll', 'qingshi_game.ime', 'rime.dll',
                 'start_service.bat', 'stop_service.bat'):
        entries['runtime/' + name] = OUTPUT / name
    entries['runtime/data/weasel.yaml'] = OUTPUT / 'data/weasel.yaml'
    for path in (ROOT / 'pkg').iterdir():
        if path.suffix in ('.yaml', '.txt'):
            entries['runtime/data/' + path.name] = path
            if path.name not in ('default.yaml', 'symbols.yaml'):
                entries['user/' + path.name] = path
    # The stock default schema includes both full and half-width symbol tables.
    # Keep this shared runtime resource alongside the shipped schemas.
    punctuation = Path(r'C:\Program Files\Rime\weasel-0.17.4\data\punctuation.yaml')
    if punctuation.is_file() and 'punctuation.yaml' not in {p.name for p in (ROOT / 'pkg').glob('*.yaml')}:
        entries['runtime/data/punctuation.yaml'] = punctuation
    opencc = ROOT / 'rime-bin/rime-deps-33e7814-Windows-msvc-x64/share/opencc'
    for path in opencc.iterdir():
        if path.suffix in ('.json', '.ocd2'):
            entries['runtime/data/opencc/' + path.name] = path
    for target, source in {
        'Weasel-GPL-3.0.txt': 'weasel/LICENSE.txt',
        'librime-BSD.txt': 'weasel/librime/LICENSE',
        'OpenCC.txt': 'weasel/librime/deps/opencc/LICENSE',
        'yaml-cpp.txt': 'weasel/librime/deps/yaml-cpp/LICENSE',
        'LevelDB.txt': 'weasel/librime/deps/leveldb/LICENSE',
    }.items():
        entries['runtime/licenses/' + target] = ROOT / source
    hashes = {}
    with zipfile.ZipFile(GUI / 'payload.zip', 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in sorted(entries.items()):
            if not path.is_file():
                raise FileNotFoundError(path)
            data = path.read_bytes()
            hashes[name] = hashlib.sha256(data).hexdigest()
            archive.writestr(name, data)
        archive.writestr('checksums.json', json.dumps(hashes, indent=2))
    print(f'Payload: {len(hashes)} verified files')


def main():
    from build_settings import build_settings
    build_settings()
    build_payload()
    sys.path.insert(0, str(WORK / 'build-tools'))
    import PyInstaller.__main__
    # 安装器界面已改成原生 Win32，不再需要任何 Qt 运行库。
    assets = [*GUI.glob('*.ps1'), GUI / 'payload.zip', GUI / 'qingshi-mark.png']
    arguments = [str(GUI / 'installer_native.py'), '--noconfirm', '--clean', '--onefile',
                 '--windowed', '--name', 'QingshiSetup', '--paths', str(GUI),
                 '--icon', str(ROOT / 'weasel/resource/weasel.ico'),
                 '--distpath', str(ROOT / 'dist'), '--workpath', str(WORK / 'package-build'),
                 '--specpath', str(WORK / 'package-build'),
                 '--exclude-module', 'tkinter',
                 '--exclude-module', 'PyQt6',
                 '--exclude-module', 'PySide6',
                 '--exclude-module', 'numpy',
                 '--exclude-module', 'PIL',
                 '--exclude-module', 'scipy',
                 '--exclude-module', 'pandas',
                 '--exclude-module', 'matplotlib',
                 '--exclude-module', 'wubi_settings',
                 '--exclude-module', 'installer_ui',
                 '--exclude-module', 'qingshi_app',
                 '--exclude-module', 'ui_theme',
                 '--exclude-module', 'navigation',
                 '--exclude-module', 'backup_page',
                 '--exclude-module', 'setup_wizard',
                 '--exclude-module', 'smoke_test',
                 '--exclude-module', 'hotkey_page',
                 '--exclude-module', 'native.app',
                 '--exclude-module', 'native.pages',
                 '--exclude-module', 'native.wizard',
                 '--exclude-module', 'native.shot']
    for asset in assets:
        arguments += ['--add-data', str(asset) + os.pathsep + '.']
    original_path = os.environ.get('PATH', '')
    os.environ['PATH'] = os.pathsep.join(
        entry for entry in original_path.split(os.pathsep)
        if 'poppler' not in entry.lower()
    )
    try:
        PyInstaller.__main__.run(arguments)
    finally:
        os.environ['PATH'] = original_path
    result = ROOT / 'dist/QingshiSetup.exe'
    digest = hashlib.sha256(result.read_bytes()).hexdigest()
    (ROOT / 'dist/QingshiSetup.sha256').write_text(digest + '  QingshiSetup.exe\n', encoding='utf-8')
    print(f'Built {result} ({result.stat().st_size / 1024 / 1024:.1f} MiB)')


if __name__ == '__main__':
    main()
