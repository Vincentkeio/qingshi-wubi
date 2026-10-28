"""Exercise installation/removal in a disposable tree with a fake Windows registry."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gui'))
import installer_backend as backend
import winreg


class FakeRegistry:
    def __init__(self):
        self.records = {}

    def get(self, hive, key, name='', view=winreg.KEY_WOW64_64KEY):
        return self.records.get((hive, key, name, view))

    def set(self, hive, key, name, value, view=winreg.KEY_WOW64_64KEY):
        self.records[(hive, key, name, view)] = value

    def children(self, hive, key, view=winreg.KEY_WOW64_64KEY):
        prefix = key + '\\'
        return sorted({k[len(prefix):].split('\\')[0] for h, k, n, v in self.records if h == hive and v == view and k.startswith(prefix)})

    def delete(self, hive, key, view=winreg.KEY_WOW64_64KEY):
        for address in list(self.records):
            h, k, n, v = address
            if h == hive and v == view and (k == key or k.startswith(key + '\\')):
                del self.records[address]

    def delete_value(self, hive, key, name, view=winreg.KEY_WOW64_64KEY):
        self.records.pop((hive, key, name, view), None)

    def values(self, hive, key, view=winreg.KEY_WOW64_64KEY):
        return [name for h, k, name, v in self.records if h == hive and k == key and v == view]


class FakeWindows:
    def __init__(self, profile):
        self.reg = FakeRegistry()
        self.profile = profile
        self.pending = []
        self.leftover = []
        self.events = []
        self.fail_deploy = False

    def register(self, dll, remove=False, x86=False):
        self.events.append(('register', dll, remove))
        view = winreg.KEY_WOW64_32KEY if x86 else winreg.KEY_WOW64_64KEY
        if remove:
            self.reg.delete(winreg.HKEY_LOCAL_MACHINE, backend.CLASS_KEY, view)
        else:
            self.reg.set(winreg.HKEY_LOCAL_MACHINE, backend.CLASS_KEY + r'\InprocServer32', '', str(dll), view)

    def tip(self, remove=False):
        self.events.append(('tip', remove))

    def install_system_ime(self, source):
        import uuid
        target = backend.SYSTEM_IME_DIR / ('weaselx64-' + uuid.uuid4().hex + '.dll')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        self.events.append(('system_ime', target))
        return target

    def remove_system_ime(self):
        self.remove_tree(backend.SYSTEM_IME_DIR, backend.SYSTEM_IME_DIR)

    def install_game_ime(self, source):
        self.events.append(('game_ime', source))

    def rollback_game_ime(self):
        self.events.append(('game_rollback',))

    def finish_game_ime(self):
        self.events.append(('game_finish',))

    def remove_game_ime(self):
        self.events.append(('game_remove',))

    def schedule_delete(self, path):
        self.pending.append(str(path))

    def stop(self, roots):
        self.events.append(('stop', roots))

    def disarm_autostart(self, roots):
        self.events.append(('disarm_autostart', roots))

    def rearm_autostart(self, roots):
        self.events.append(('rearm_autostart', roots))

    def command(self, arguments, timeout=180, env=None):
        if self.fail_deploy:
            raise RuntimeError('injected deployment failure')
        data = self.profile / 'AppData/Roaming/QingshiWubi/build'
        data.mkdir(parents=True, exist_ok=True)
        (data / 'wubi86.table.bin').write_bytes(b'compiled')

    def shortcut(self, link, executable, arguments=''):
        link.write_text(str(executable) + ' ' + arguments)

    def remove_tree(self, path, allow_root):
        path = Path(path)
        if not path.exists():
            return
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='qingshi-test-')
        self.base = Path(self.temporary.name)
        system_patch = patch.object(backend, 'SYSTEM_IME_DIR', self.base / 'Windows/System32/IME/QingshiWubi')
        system_patch.start()
        self.addCleanup(system_patch.stop)
        self.profile = self.base / 'Users/tester'
        self.profile.mkdir(parents=True)
        test_temp = self.base / 'Temp'
        test_temp.mkdir()
        self.temp_patch = patch('tempfile.gettempdir', return_value=str(test_temp))
        self.temp_patch.start()
        self.addCleanup(self.temp_patch.stop)
        self.env = patch.dict(os.environ, {'ProgramFiles': str(self.base / 'Programs'),
                   'ProgramFiles(x86)': str(self.base / 'Programs32'), 'ProgramData': str(self.base / 'ProgramData')})
        self.env.start()
        self.system = FakeWindows(self.profile)
        self.payload = self.base / 'payload.zip'
        self.files = {f'runtime/{name}': name.encode() for name in ('WeaselServer.exe', 'WeaselDeployer.exe', 'weaselx64.dll', 'qingshi_game.ime', 'rime.dll')}
        self.files.update({'user/custom_phrase.txt': b'# template', 'user/weasel.custom.yaml': b'# template'})
        self.write_payload()
        self.executable = self.base / 'setup.exe'
        self.executable.write_bytes(b'installer')
        self.progress = []
        self.installer = backend.Installer(self.payload, self.system, lambda percent, text: self.progress.append((percent, text)), profile=self.profile)

    def tearDown(self):
        self.env.stop()
        self.temporary.cleanup()

    def write_payload(self):
        with zipfile.ZipFile(self.payload, 'w') as archive:
            hashes = {name: hashlib.sha256(data).hexdigest() for name, data in self.files.items()}
            for name, data in self.files.items():
                archive.writestr(name, data)
            archive.writestr('checksums.json', json.dumps(hashes))

    def test_upgrade_failure_keeps_previous_runtime_and_manifest(self):
        self.install()
        marker = self.installer.root / backend.MARKER
        previous = marker.read_bytes()
        old_dll = self.installer.registered_dll()
        self.system.fail_deploy = True
        with self.assertRaises(RuntimeError):
            self.installer.install(self.executable)
        self.assertEqual(marker.read_bytes(), previous)
        self.assertEqual(self.installer.registered_dll(), old_dll)
        self.assertTrue(old_dll.is_file())
        self.assertIn(('game_rollback',), self.system.events)

    def test_game_ime_is_installed_before_tsf_registration(self):
        self.install()
        events = [event[0] for event in self.system.events]
        self.assertLess(events.index('game_ime'), events.index('register'))

    def test_missing_game_component_is_rejected_before_system_changes(self):
        del self.files['runtime/qingshi_game.ime']
        self.write_payload()
        with self.assertRaisesRegex(RuntimeError, '必要的输入法组件'):
            self.installer.install(self.executable)
        self.assertEqual(self.system.events, [])

    def install(self):
        result = self.installer.install(self.executable)
        self.assertTrue(result['ok'])
        return result

    def test_install_and_complete_uninstall(self):
        self.install()
        self.assertTrue((self.installer.root / 'Qingshi.exe').is_file())
        self.assertEqual(self.system.reg.get(winreg.HKEY_LOCAL_MACHINE, backend.UNINSTALL_KEY, 'DisplayName'), '青石五笔输入法')
        result = self.installer.uninstall()
        self.assertTrue(result['ok'])
        self.assertFalse(self.installer.root.exists())
        self.assertFalse(self.installer.data.exists())
        self.assertFalse(self.system.reg.records)

    def test_keep_data_and_reinstall_preserves_newer_phrases(self):
        self.install()
        phrase = self.installer.data / 'custom_phrase.txt'
        phrase.write_text('my latest words', encoding='utf-8')
        self.installer.uninstall(clear_data=False)
        self.assertEqual(phrase.read_text(), 'my latest words')
        self.installer.changes.clear()
        self.install()
        self.assertEqual(phrase.read_text(), 'my latest words')

    def test_other_rime_data_and_registry_survive(self):
        old_userdir = self.profile / 'AppData/Roaming/Rime'
        self.system.reg.set(winreg.HKEY_CURRENT_USER, backend.RIME_KEY, 'RimeUserDir', str(old_userdir))
        self.system.reg.set(winreg.HKEY_CURRENT_USER, backend.RIME_KEY, 'Profile', 'zhuyin')
        self.system.reg.set(winreg.HKEY_CURRENT_USER, backend.RIME_KEY, 'OtherSetting', 'keep-user')
        self.system.reg.set(winreg.HKEY_LOCAL_MACHINE, backend.RIME_KEY, 'OtherSetting', 'keep-machine')
        self.install()
        manifest = self.installer.managed()
        manifest['legacy_roots'] = [str(Path(os.environ['ProgramFiles']) / 'Rime/weasel-0.17.4')]
        backend.atomic_json(self.installer.root / backend.MARKER, manifest)
        other = self.profile / 'AppData/Roaming/Rime'
        other.mkdir()
        keep = other / 'luna_pinyin.custom.yaml'
        keep.write_text('my pinyin')
        own = other / 'wubi86.dict.yaml'
        own.write_text('# Rime dictionary: wubi86\n# 由极点/五笔原版码表转换，sort: original 保持原始顺序\n', encoding='utf-8')
        (other / 'weasel.custom.yaml').write_text('# 青石五笔 · 外观设置\n', encoding='utf-8')
        (other / 'default.custom.yaml').write_text('# 五笔输入法 · 方案与候选设置\n', encoding='utf-8')
        unrelated = other / 'cangjie5.schema.yaml'
        unrelated.write_text('another input method schema')
        self.system.reg.set(winreg.HKEY_LOCAL_MACHINE, r'Software\Rime\OtherApp', 'value', 'untouched')
        self.installer.uninstall()
        self.assertTrue(keep.exists())
        self.assertFalse(own.exists())
        self.assertFalse((other / 'default.custom.yaml').exists())
        self.assertTrue(unrelated.exists())
        self.assertEqual(self.system.reg.get(winreg.HKEY_LOCAL_MACHINE, r'Software\Rime\OtherApp', 'value'), 'untouched')
        self.assertEqual(self.system.reg.get(winreg.HKEY_LOCAL_MACHINE, backend.RIME_KEY, 'OtherSetting'), 'keep-machine')
        self.assertEqual(self.system.reg.get(winreg.HKEY_CURRENT_USER, backend.RIME_KEY, 'OtherSetting'), 'keep-user')
        self.assertEqual(self.system.reg.get(winreg.HKEY_CURRENT_USER, backend.RIME_KEY, 'RimeUserDir'), str(old_userdir))
        self.assertEqual(self.system.reg.get(winreg.HKEY_CURRENT_USER, backend.RIME_KEY, 'Profile'), 'zhuyin')

    def test_corrupted_payload_has_no_side_effects(self):
        with zipfile.ZipFile(self.payload, 'a') as archive:
            archive.writestr('runtime/tampered.exe', b'tampered')
        with self.assertRaisesRegex(RuntimeError, '文件清单'):
            self.install()
        self.assertFalse(self.installer.root.exists())
        self.assertFalse(self.system.events)

    def test_traversal_rejected(self):
        self.files['runtime/../../escape.exe'] = b'escape'
        self.write_payload()
        with self.assertRaisesRegex(RuntimeError, '越界'):
            self.install()
        self.assertFalse(self.installer.root.exists())

    def test_foreign_installation_not_overwritten(self):
        self.system.reg.set(winreg.HKEY_LOCAL_MACHINE, backend.CLASS_KEY + r'\InprocServer32', '', str(self.base / 'foreign.dll'))
        with self.assertRaisesRegex(RuntimeError, '另一套'):
            self.install()
        self.assertFalse(self.installer.root.exists())

    def test_legacy_qingshi_detected_when_windows_omits_profile_description(self):
        legacy = Path(os.environ['ProgramFiles']) / 'Rime/weasel-0.17.4'
        legacy.mkdir(parents=True)
        (legacy / 'qingshi-weaselx64.dll').write_bytes(b'legacy')
        self.system.reg.set(winreg.HKEY_LOCAL_MACHINE, backend.CLASS_KEY + r'\InprocServer32', '',
                            str(legacy / 'qingshi-weaselx64.dll'))
        self.assertEqual(self.installer.legacy_root(), legacy)

    def test_unmarked_data_is_not_deleted_or_unregistered(self):
        self.install()
        (self.installer.data / backend.DATA_MARKER).unlink()
        count = len(self.system.events)
        with self.assertRaisesRegex(RuntimeError, '归属标记'):
            self.installer.uninstall()
        self.assertEqual(count, len(self.system.events))
        self.assertTrue(self.installer.data.exists())

    def test_deployment_failure_rolls_back_registration_and_keeps_removal_entry(self):
        self.system.fail_deploy = True
        with self.assertRaisesRegex(RuntimeError, 'injected'):
            self.install()
        self.assertFalse(self.installer.registered_dll())
        self.assertFalse(self.system.reg.get(winreg.HKEY_CURRENT_USER, backend.RIME_KEY, 'RimeUserDir'))
        self.assertTrue((self.installer.root / 'Qingshi.exe').exists())
        self.assertTrue(self.system.reg.get(winreg.HKEY_LOCAL_MACHINE, backend.UNINSTALL_KEY, 'UninstallString'))
        self.assertNotEqual(self.progress[-1][0], 100)
        self.assertTrue(self.installer.uninstall()['ok'])

    def test_uninstall_honors_pending_reboot(self):
        self.install()
        self.system.pending = [str(self.installer.root / 'locked.dll')]
        self.assertTrue(self.installer.uninstall()['reboot'])

    def test_standalone_settings_installs_shortcut_and_is_removed(self):
        self.files['runtime/settings/QingshiSettings.exe'] = b'settings gui'
        self.files['runtime/settings/_internal/Qt6Core.dll'] = b'qt runtime'
        self.write_payload()
        result = self.install()
        runtime = Path(result['runtime'])
        settings = runtime / 'settings/QingshiSettings.exe'
        self.assertTrue(settings.is_file())
        shortcut = self.installer.menu_directories()[0] / '青石五笔设置.lnk'
        self.assertIn(str(settings), shortcut.read_text())
        self.assertTrue(self.installer.uninstall()['ok'])
        self.assertFalse(settings.exists())

    def test_custom_install_root_rejected_before_changes(self):
        self.installer.root = self.base
        with self.assertRaisesRegex(RuntimeError, '专用程序目录'):
            self.install()
        self.assertFalse(self.system.events)


if __name__ == '__main__':
    unittest.main(verbosity=2)
