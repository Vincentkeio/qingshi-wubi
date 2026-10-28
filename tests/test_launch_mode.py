"""打包版启动时该当安装器还是设置中心。

真事：浏览器重复下载把文件存成 `QingshiSetup (1).exe`，旧逻辑用精确文件名匹配，
安装包被误判成设置中心 —— 双击弹出设置界面、装不上、还一直提示有更新。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gui'))

from qingshi_app import is_setup_invocation


class LaunchModeTests(unittest.TestCase):
    def test_plain_installer_name(self):
        self.assertTrue(is_setup_invocation([], r'C:\dl\QingshiSetup.exe', True))

    def test_browser_renamed_installer(self):
        for name in ('QingshiSetup (1).exe', 'QingshiSetup(2).exe',
                     'QingshiSetup - 副本.exe', 'qingshisetup.exe'):
            with self.subTest(name=name):
                self.assertTrue(is_setup_invocation([], rf'C:\dl\{name}', True))

    def test_installed_settings_center_stays_settings(self):
        self.assertFalse(is_setup_invocation([], r'C:\Program Files\QingshiWubi\Qingshi.exe', True))

    def test_unknown_name_in_packaged_build_is_treated_as_installer(self):
        self.assertTrue(is_setup_invocation([], r'C:\dl\下载.exe', True))

    def test_explicit_setup_flag_wins(self):
        self.assertTrue(is_setup_invocation(['--setup'], r'C:\x\Qingshi.exe', True))

    def test_source_checkout_is_not_installer(self):
        # 源码运行时 sys.executable 是 python.exe，绝不能当安装器
        self.assertFalse(is_setup_invocation([], r'C:\Python313\python.exe', False))


if __name__ == '__main__':
    unittest.main()
