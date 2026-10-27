"""Single packaged entry point for settings, wizard, installation and removal."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import shutil


def detached_uninstaller(action='--uninstall'):
    # Move the running UI outside Program Files so its own executable can be deleted.
    temporary = Path(tempfile.mkdtemp(prefix='qingshi-uninstall-'))
    executable = temporary / 'QingshiRemove.exe'
    shutil.copy2(sys.executable, executable)
    helper = temporary / 'cleanup.ps1'
    shutil.copy2(Path(__file__).with_name('cleanup.ps1'), helper)
    environment = os.environ.copy()
    environment['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    process = subprocess.Popen([str(executable), action, '--detached'], env=environment)
    subprocess.Popen(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(helper),
                      '-WaitProcessId', str(process.pid), '-TargetDirectory', str(temporary)],
                     creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)


def main():
    if '--diagnose-qt' in sys.argv:
        result = {'ok': False}
        try:
            import ctypes
            import os
            import sys as runtime
            bundle = Path(getattr(runtime, '_MEIPASS', Path(__file__).parent))
            qt_bin = bundle / 'PyQt6' / 'Qt6' / 'bin'
            os.add_dll_directory(str(bundle))
            os.add_dll_directory(str(qt_bin))
            loaded = []
            for name in ('Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Widgets.dll'):
                ctypes.WinDLL(str(qt_bin / name))
                loaded.append(name)
            from PyQt6.QtWidgets import QApplication
            result = {'ok': True, 'qtwidgets': QApplication.__module__, 'loaded': loaded,
                      'bundle': str(bundle), 'qt_bin': str(qt_bin)}
        except Exception as error:
            result['error'] = repr(error)
            result['loaded'] = locals().get('loaded', [])
            result['bundle'] = locals().get('bundle')
            result['qt_bin'] = locals().get('qt_bin')
        destination = Path(sys.argv[sys.argv.index('--diagnose-qt') + 1])
        destination.write_text(__import__('json').dumps(result, ensure_ascii=False), encoding='utf-8')
        return 0 if result['ok'] else 1
    if '--smoke-test' in sys.argv:
        from smoke_test import run
        return run(sys.argv[sys.argv.index('--smoke-test') + 1])
    if '--worker' in sys.argv:
        from installer_backend import run_worker
        return run_worker(sys.argv[sys.argv.index('--worker') + 1])
    frozen = getattr(sys, 'frozen', False)
    uninstall = '--uninstall' in sys.argv
    preview = '--preview' in sys.argv
    if frozen and uninstall and '--detached' not in sys.argv and not preview:
        detached_uninstaller()
        return 0
    if frozen and '--setup' in sys.argv and Path(sys.executable).stem.lower() == 'qingshi' and '--detached' not in sys.argv and not preview:
        detached_uninstaller('--setup')
        return 0
    from PyQt6.QtWidgets import QApplication
    from ui_theme import apply_theme
    app = QApplication(sys.argv)
    apply_theme(app)
    setup = ('--setup' in sys.argv or Path(sys.executable).stem.lower() == 'qingshisetup')
    if setup or uninstall:
        from installer_ui import InstallerWindow
        window = InstallerWindow(uninstall, preview)
    elif '--settings' in sys.argv:
        from wubi_settings import MainWindow
        window = MainWindow()
    elif '--wizard' in sys.argv:
        from setup_wizard import SetupWizard
        window = SetupWizard()
    else:
        from wubi_settings import MainWindow
        window = MainWindow()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
