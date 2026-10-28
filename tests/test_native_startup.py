"""Installed entry points must never open an installer during daily use."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gui'))
import native_startup


class NativeStartupTests(unittest.TestCase):
    def test_wizard_routes_to_installed_settings_with_fresh_runtime(self):
        target = Path('C:/Program Files/QingshiWubi/runtime/settings/QingshiSettings.exe')
        with patch.object(native_startup, 'installed_settings', return_value=target), \
                patch.object(Path, 'is_file', return_value=True), \
                patch.object(native_startup.subprocess, 'Popen') as launch:
            self.assertEqual(native_startup.open_installed_settings(True), 0)
            self.assertEqual(launch.call_args.args[0], [str(target), '--wizard'])
            self.assertEqual(launch.call_args.kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'], '1')

    def test_daily_check_stays_quiet_when_skipped(self):
        with patch('app_paths.user_directory', return_value='unused'), \
                patch('update_checker.UpdateChecker') as checker, \
                patch.object(native_startup.ctypes.windll.user32, 'MessageBoxW') as dialog:
            checker.return_value.check.return_value = {'skipped': True}
            self.assertEqual(native_startup.background_update(), 0)
            dialog.assert_not_called()

    def test_daily_check_stays_quiet_when_network_fails(self):
        with patch('app_paths.user_directory', return_value='unused'), \
                patch('update_checker.UpdateChecker') as checker, \
                patch.object(native_startup.ctypes.windll.user32, 'MessageBoxW') as dialog:
            checker.return_value.check.side_effect = OSError('offline')
            self.assertEqual(native_startup.background_update(), 0)
            dialog.assert_not_called()


if __name__ == '__main__':
    unittest.main()
