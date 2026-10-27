"""Non-destructive render and interaction verification for the packaged application."""
from pathlib import Path
import tempfile
from PyQt6.QtWidgets import QApplication, QSpinBox
from ui_theme import apply_theme
from installer_backend import atomic_json


def run(directory):
    from wubi_settings import MainWindow, RimeConfig
    from setup_wizard import SetupWizard
    from installer_ui import InstallerWindow
    output = Path(directory)
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    apply_theme(app)
    captures = []
    def capture(window, name):
        window.show()
        app.processEvents()
        assert window.grab().save(str(output / (name + '.png')))
        captures.append(name)
    with tempfile.TemporaryDirectory(prefix='qingshi-preview-data-') as data:
        cfg = RimeConfig(data)
        window = MainWindow(cfg)
        for width, height, suffix in [(1060, 720, ''), (900, 620, '-compact')]:
            window.resize(width, height)
            for index, name in enumerate(('common', 'appearance', 'dict', 'phrases', 'shadow', 'hotkey', 'backup-update', 'about')):
                window.nav_list.setCurrentRow(index)
                capture(window, name + suffix)
                assert window.stack.currentIndex() == index
                assert sum(button.isChecked() for button in window.nav_list.buttons) == 1
        for spin in window.findChildren(QSpinBox):
            original = spin.value()
            if original < spin.maximum():
                spin.stepUp()
                assert spin.value() == original + 1
                spin.stepDown()
                assert spin.value() == original
        window.close()
        wizard = SetupWizard(cfg)
        for index, name in enumerate(('scheme', 'display', 'summary')):
            if index:
                wizard.next()
            capture(wizard, 'wizard-' + name)
        wizard.close()
        for uninstall, name in [(False, 'install'), (True, 'uninstall')]:
            manager = InstallerWindow(uninstall, preview=True)
            capture(manager, name)
            manager.show_progress(48, '正在移除输入法注册' if uninstall else '正在注册输入法')
            capture(manager, name + '-progress')
            manager.finish({'ok': False, 'error': '测试：操作失败后可以重试。'})
            assert manager.start.isEnabled() and manager.start.text() == '重试'
            capture(manager, name + '-error')
            manager.finish({'ok': True, 'reboot': uninstall, 'data_removed': True})
            capture(manager, name + '-complete')
            manager.close()
    atomic_json(output / 'smoke-result.json', {'ok': True, 'captures': captures})
    return 0
