from copy import deepcopy
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch
import yaml

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gui'))
import hotkeys
import config_bundle


class HotkeyConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_defaults_and_physical_key_conflicts(self):
        self.assertEqual(hotkeys.validate(hotkeys.DEFAULTS), hotkeys.DEFAULTS)
        values = deepcopy(hotkeys.DEFAULTS)
        values['traditional'][0] = 'Control+Shift+percent'
        with self.assertRaisesRegex(ValueError, '同时分配'):
            hotkeys.validate(values)

    def test_reserved_typing_and_system_keys_rejected(self):
        for value in ('a', 'Shift+A', 'Alt+F4', 'Control+space', 'Control+1', 'Control+Shift+2'):
            values = deepcopy(hotkeys.DEFAULTS)
            values['traditional'][0] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                hotkeys.validate(values)

    def test_patch_preserves_unrelated_settings_and_removes_old_bindings(self):
        custom = self.root / 'wubi86.custom.yaml'
        custom.write_text('patch:\n  style/color_scheme: personal\n  key_binder/bindings:\n'
                          '    - {when: always, accept: Control+Shift+F, toggle: traditional}\n'
                          '    - {when: composing, accept: Alt+h, send: Home}\n', encoding='utf-8')
        values = deepcopy(hotkeys.DEFAULTS)
        values['ascii_mode'] = ['F8','']
        values['traditional'] = ['Control+Alt+t','']
        hotkeys.apply(self.root, values)
        for sid in hotkeys.SCHEMAS:
            data = yaml.safe_load((self.root / (sid + '.custom.yaml')).read_text())['patch']
            self.assertEqual(data['ascii_composer/switch_key/Shift_L'], 'noop')
            self.assertEqual(data['engine/processors'][0], 'key_binder')
            self.assertFalse(any(b.get('accept') == 'Control+Shift+F' for b in data['key_binder/bindings']))
        data = yaml.safe_load(custom.read_text())['patch']
        self.assertEqual(data['style/color_scheme'], 'personal')
        self.assertIn({'when':'composing','accept':'Alt+h','send':'Home'}, data['key_binder/bindings'])
        self.assertEqual(hotkeys.load(self.root), values)
        self.assertTrue(hotkeys.needs_deploy(self.root))

    def test_invalid_config_is_not_overwritten(self):
        target = self.root / 'wubi98.custom.yaml'
        target.write_text('patch: broken', encoding='utf-8')
        with self.assertRaises(ValueError):
            hotkeys.apply(self.root, hotkeys.DEFAULTS)
        self.assertEqual(target.read_text(), 'patch: broken')
        self.assertFalse((self.root / 'default.custom.yaml').exists())

    def test_write_failure_rolls_back_all_files(self):
        target = self.root / 'default.custom.yaml'
        target.write_text('patch: {menu: {page_size: 7}}', encoding='utf-8')
        original = target.read_bytes()
        write = hotkeys.atomic_write
        failed = False
        def injected(path, data):
            nonlocal failed
            if Path(path).name == 'wubi98.custom.yaml' and not failed:
                failed = True
                raise OSError('injected')
            return write(path, data)
        with patch.object(hotkeys, 'atomic_write', side_effect=injected), self.assertRaises(OSError):
            hotkeys.apply(self.root, hotkeys.DEFAULTS)
        self.assertEqual(target.read_bytes(), original)
        self.assertFalse((self.root / hotkeys.FILE).exists())

    def test_shortcuts_roundtrip_in_configuration_backup(self):
        source, target = self.root / 'source', self.root / 'target'
        source.mkdir()
        hotkeys.apply(source, hotkeys.DEFAULTS)
        config_bundle.restore(target, config_bundle.snapshot(source))
        self.assertEqual(hotkeys.load(target), hotkeys.DEFAULTS)


class HotkeyUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_record_cancel_clear_and_conflict_feedback(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from hotkey_page import HotkeyPage
        page = HotkeyPage()
        self.addCleanup(page.deleteLater)
        page.set_values(hotkeys.DEFAULTS)
        field = page.fields['ascii_mode', 0]
        field.begin()
        QTest.keyClick(field, Qt.Key.Key_F8)
        self.assertEqual(field.value, 'F8')
        field.begin()
        QTest.keyClick(field, Qt.Key.Key_Escape)
        self.assertEqual(field.value, 'F8')
        page.fields['traditional', 0].set_value('F8')
        page.on_change()
        self.assertIn('同时分配', page.message.text())
        page.clear('traditional', 0)
        self.assertTrue(page.message.isHidden())
        page.reset_defaults()
        self.assertEqual(page.values(), hotkeys.DEFAULTS)

    def test_save_uses_deploy_and_restart_only_for_changed_shortcuts(self):
        from wubi_settings import MainWindow, RimeConfig
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(RimeConfig(directory))
            self.addCleanup(window.deleteLater)
            values = deepcopy(hotkeys.DEFAULTS)
            values['ascii_mode'] = ['F8','']
            window.hotkey_page.set_values(values)
            with patch.object(window.cfg, 'deploy', return_value=True) as deploy, \
                 patch.object(window.cfg, 'restart_server', return_value=True) as restart, \
                 patch.object(window.cfg, 'set_shift_letter_direct'), \
                 patch.object(window.cfg, 'set_no_candidate_beep'), \
                 patch.object(window.cfg, 'set_auto_commit_unique'), \
                 patch('wubi_settings.QMessageBox.information'):
                self.assertTrue(window.save())
            deploy.assert_called_once_with(wait=True)
            restart.assert_called_once()
            self.assertEqual(hotkeys.load(directory), values)
            values['ascii_mode'][0] = 'F7'
            window.hotkey_page.set_values(values)
            with patch.object(window.cfg, 'deploy', return_value=False), \
                 patch.object(window.cfg, 'restart_server') as restart, \
                 patch.object(window.cfg, 'set_shift_letter_direct'), \
                 patch.object(window.cfg, 'set_no_candidate_beep'), \
                 patch.object(window.cfg, 'set_auto_commit_unique'), \
                 patch('wubi_settings.QMessageBox.information'):
                self.assertFalse(window.save())
            restart.assert_not_called()
            self.assertNotEqual(window._hotkey_snapshot, values)
            self.assertTrue(hotkeys.needs_deploy(directory))


if __name__ == '__main__':
    unittest.main()
