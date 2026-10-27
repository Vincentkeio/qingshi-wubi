from pathlib import Path
import ctypes
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import winreg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gui'))
from game_compat import GameIme, IME_NAME, LAYOUTS, PRELOAD
import installer_backend as backend
from test_installer import FakeRegistry


class GameCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='qingshi-imm-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.system = self.root / 'System32'
        self.system.mkdir()
        self.source = self.root / IME_NAME
        self.source.write_bytes(b'new component')
        self.reg = FakeRegistry()
        self.deleted = []
        self.ime = GameIme(self.reg, self.deleted.append, self.system)
        self.key = LAYOUTS + '\\E0200804'
        self.foreign_key = LAYOUTS + '\\E0210804'
        self.reg.set(winreg.HKEY_LOCAL_MACHINE, self.foreign_key, 'Ime File', 'other.ime')
        self.reg.set(winreg.HKEY_CURRENT_USER, PRELOAD, '1', '00000804')
        self.install_function = Mock(side_effect=self.install_api)
        self.library = Mock()
        self.library.ImmInstallIMEW = self.install_function
        self.library.UnloadKeyboardLayout = Mock(return_value=True)
        self.dll_patch = patch('ctypes.WinDLL', return_value=self.library)
        self.dll_patch.start()
        self.addCleanup(self.dll_patch.stop)

    def install_api(self, path, description):
        self.assertTrue(Path(path).is_file())
        self.reg.set(winreg.HKEY_LOCAL_MACHINE, self.key, 'Ime File', IME_NAME.upper())
        self.reg.set(winreg.HKEY_CURRENT_USER, PRELOAD, '2', 'E0200804')
        return 0xE0200804

    def test_install_remove_preserves_other_ime(self):
        self.ime.install(self.source)
        self.assertEqual(self.ime.target.read_bytes(), self.source.read_bytes())
        self.ime.finish()
        self.ime.remove()
        self.assertFalse(self.ime.target.exists())
        self.assertIsNone(self.reg.get(winreg.HKEY_LOCAL_MACHINE, self.key, 'Ime File'))
        self.assertEqual(self.reg.get(winreg.HKEY_LOCAL_MACHINE, self.foreign_key, 'Ime File'), 'other.ime')
        self.assertEqual(self.reg.get(winreg.HKEY_CURRENT_USER, PRELOAD, '1'), '00000804')
        self.assertIsNone(self.reg.get(winreg.HKEY_CURRENT_USER, PRELOAD, '2'))

    def test_failed_registration_restores_previous_component(self):
        self.ime.target.write_bytes(b'previous component')
        self.reg.set(winreg.HKEY_LOCAL_MACHINE, self.key, 'Ime File', IME_NAME)
        self.install_function.side_effect = lambda *args: 0
        with self.assertRaisesRegex(RuntimeError, '注册游戏兼容组件'):
            self.ime.install(self.source)
        self.assertEqual(self.ime.target.read_bytes(), b'previous component')
        self.assertEqual(self.reg.get(winreg.HKEY_LOCAL_MACHINE, self.key, 'Ime File'), IME_NAME)

    def test_post_install_failure_removes_new_registration(self):
        self.ime.install(self.source)
        self.ime.rollback()
        self.assertFalse(self.ime.target.exists())
        self.assertIsNone(self.reg.get(winreg.HKEY_LOCAL_MACHINE, self.key, 'Ime File'))
        self.assertTrue(self.deleted)

    def test_identical_orphan_is_registered(self):
        self.ime.target.write_bytes(self.source.read_bytes())
        self.ime.install(self.source)
        self.install_function.assert_called_once()

    def test_upgrade_releases_old_file_only_after_success(self):
        self.ime.target.write_bytes(b'old')
        self.reg.set(winreg.HKEY_LOCAL_MACHINE, self.key, 'Ime File', IME_NAME)
        self.ime.install(self.source)
        self.assertEqual(self.ime.backup.read_bytes(), b'old')
        self.assertEqual(self.deleted, [])
        self.ime.finish()
        self.assertIn(self.ime.backup, self.deleted)

    def test_foreign_unregistered_file_is_not_overwritten(self):
        self.ime.target.write_bytes(b'foreign file')
        with self.assertRaisesRegex(RuntimeError, '未覆盖'):
            self.ime.install(self.source)
        self.assertEqual(self.ime.target.read_bytes(), b'foreign file')

    def test_tip_restores_original_values_even_after_api_failure(self):
        key = r'Control Panel\International\User Profile\zh-Hans-CN'
        other = '0804:other-input-method'
        self.reg.set(winreg.HKEY_CURRENT_USER, key, other, 9)
        def replace(*args):
            self.reg.delete(winreg.HKEY_CURRENT_USER, key)
            return False
        self.library.InstallLayoutOrTip = Mock(side_effect=replace)
        windows = backend.Windows(self.reg)
        with self.assertRaises(OSError):
            windows.tip()
        self.assertEqual(self.reg.get(winreg.HKEY_CURRENT_USER, key, other), 9)


if __name__ == '__main__':
    unittest.main()
