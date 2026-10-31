from pathlib import Path
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gui'))
import config_bundle as bundle
from fixed_order import ensure_fixed_order
from update_checker import UpdateChecker, API, PREFIX
from rime_config import RimeConfig
from symbol_settings import ensure_symbol_preference


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='qingshi-config-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.target = self.root / 'target'
        self.source.mkdir()
        self.target.mkdir()

    def test_symbol_direct_setting_and_presets(self):
        cfg = RimeConfig(str(self.source))
        self.assertTrue(cfg.symbols_direct())
        for enabled in (False, True):
            cfg.set_symbols_direct(enabled)
            self.assertEqual(cfg.symbols_direct(), enabled)
            for sid in ('wubi86', 'wubi98', 'wubi06'):
                data = yaml.safe_load((self.source / (sid + '.custom.yaml')).read_text(encoding='utf-8'))
                self.assertEqual(data['patch']['punctuator/import_preset'],
                                 'symbols_direct' if enabled else 'symbols')
        pkg = Path(__file__).resolve().parents[1] / 'pkg'
        original = yaml.safe_load((pkg / 'symbols.yaml').read_text(encoding='utf-8'))['punctuator']
        direct = yaml.safe_load((pkg / 'symbols_direct.yaml').read_text(encoding='utf-8'))['punctuator']
        for shape in ('half_shape', 'full_shape'):
            for key, value in original[shape].items():
                self.assertEqual(direct[shape][key], {'commit': value[0]} if isinstance(value, list) else value)
        self.assertEqual(original['symbols'], direct['symbols'])

    def test_symbol_preference_migrates_upgrade_and_preserves_choice(self):
        ensure_symbol_preference(self.source)
        cfg = RimeConfig(str(self.source))
        self.assertTrue(cfg.symbols_direct())
        cfg.set_symbols_direct(False)
        ensure_symbol_preference(self.source)
        self.assertFalse(cfg.symbols_direct())
        (self.source / 'wubi98.custom.yaml').unlink()
        ensure_symbol_preference(self.source)
        restored = yaml.safe_load((self.source / 'wubi98.custom.yaml').read_text(encoding='utf-8'))
        self.assertEqual(restored['patch']['punctuator/import_preset'], 'symbols')

    def test_roundtrip_phrases_order_and_backup(self):
        (self.source / 'custom_phrase.txt').write_text('自定义\tzz\t9999\n', encoding='utf-8')
        (self.source / 'shadow_wubi86.yaml').write_text('version: 1\nrules:\n  wqiy: [仰泳, 你]\n', encoding='utf-8')
        (self.source / 'weasel.custom.yaml').write_text('patch:\n  style/font_point: 18\n', encoding='utf-8')
        (self.source / 'wubi86.userdb').mkdir()
        (self.source / 'wubi86.userdb/private-data').write_text('not exported')
        (self.source / 'qingshi-tsf-diag.log').write_text('not exported')
        (self.target / 'custom_phrase.txt').write_text('旧词条\told\t1\n', encoding='utf-8')
        (self.target / 'shadow_wubi98.yaml').write_text('rules: {a: [旧规则]}', encoding='utf-8')
        data = bundle.snapshot(self.source, False)
        manifest, files = bundle.inspect(data)
        self.assertNotIn('wubi86.userdb', files)
        self.assertNotIn('qingshi-tsf-diag.log', files)
        result = bundle.restore(self.target, data)
        self.assertFalse(result['shift_letter_direct'])
        self.assertEqual((self.target / 'custom_phrase.txt').read_bytes(), (self.source / 'custom_phrase.txt').read_bytes())
        self.assertEqual((self.target / 'shadow_wubi86.yaml').read_bytes(), (self.source / 'shadow_wubi86.yaml').read_bytes())
        self.assertFalse((self.target / 'shadow_wubi98.yaml').exists())
        _, original = bundle.inspect(Path(result['backup']).read_bytes())
        self.assertIn('旧词条', original['custom_phrase.txt'].decode('utf-8'))
        for schema in ('wubi86','wubi98','wubi06'):
            patch_data = yaml.safe_load((self.target / (schema + '.custom.yaml')).read_text())['patch']
            self.assertIs(patch_data['translator/enable_user_dict'], False)

    def test_tampering_and_path_traversal_rejected(self):
        original = bundle.snapshot(self.source)
        with zipfile.ZipFile(io.BytesIO(original)) as source:
            manifest = source.read('manifest.json')
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('manifest.json', manifest)
            archive.writestr('../outside.yaml', b'bad')
        with self.assertRaises(ValueError):
            bundle.restore(self.target, output.getvalue())
        self.assertEqual(list(self.target.iterdir()), [])

    def test_custom_libraries_and_tables_in_subfolders_are_included(self):
        library = self.source / '词库/自定义.dict.yaml'
        library.parent.mkdir()
        library.write_text('---\nname: custom\nsort: original\n...\n自定义\tabcd\t0\n', encoding='utf-8')
        (self.source / 'extra.schema.yaml').write_text('schema: {schema_id: extra}\n', encoding='utf-8')
        result = bundle.restore(self.target, bundle.snapshot(self.source))
        self.assertEqual((self.target / '词库/自定义.dict.yaml').read_bytes(), library.read_bytes())
        self.assertTrue((self.target / 'extra.schema.yaml').exists())

    def test_backup_checksum_rejects_tampering(self):
        (self.source / 'custom_phrase.txt').write_text('original', encoding='utf-8')
        original = bundle.snapshot(self.source)
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(output, 'w') as target:
            for name in source.namelist():
                target.writestr(name, b'tampered' if name == 'custom_phrase.txt' else source.read(name))
        with self.assertRaisesRegex(ValueError, '校验失败'):
            bundle.restore(self.target, output.getvalue())

    def test_invalid_yaml_changes_nothing(self):
        (self.source / 'weasel.custom.yaml').write_text('patch: [invalid', encoding='utf-8')
        (self.target / 'custom_phrase.txt').write_text('keep', encoding='utf-8')
        with self.assertRaises(yaml.YAMLError):
            bundle.restore(self.target, bundle.snapshot(self.source))
        self.assertEqual((self.target / 'custom_phrase.txt').read_text(), 'keep')

    def test_import_write_failure_rolls_back_existing_files(self):
        (self.source / 'custom_phrase.txt').write_text('new', encoding='utf-8')
        (self.target / 'custom_phrase.txt').write_text('old', encoding='utf-8')
        real = bundle.atomic_write
        failed = [False]
        def failing(path, data):
            if Path(path).parent == self.target and not failed[0]:
                failed[0] = True
                raise OSError('simulated disk failure')
            return real(path, data)
        with patch.object(bundle, 'atomic_write', side_effect=failing):
            with self.assertRaises(OSError):
                bundle.restore(self.target, bundle.snapshot(self.source))
        self.assertEqual((self.target / 'custom_phrase.txt').read_text(), 'old')

    def test_fixed_order_preserves_manual_configuration(self):
        path = self.target / 'wubi86.custom.yaml'
        path.write_text('patch:\n  translator:\n    enable_user_dict: true\n  switches/@3/reset: 1\n', encoding='utf-8')
        ensure_fixed_order(self.target)
        config = yaml.safe_load(path.read_text())['patch']
        self.assertFalse(config['translator']['enable_user_dict'])
        self.assertFalse(config['translator/enable_user_dict'])
        self.assertEqual(config['switches/@3/reset'], 1)
        self.assertEqual(ensure_fixed_order(self.target), [])


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='qingshi-update-test-')
        self.addCleanup(self.temp.cleanup)
        self.checker = UpdateChecker(self.temp.name)

    def response(self, version='v1.0.8', **changes):
        result = {'tag_name':version,'html_url':PREFIX+version,'draft':False,'prerelease':False}
        result.update(changes)
        return io.BytesIO(json.dumps(result).encode())

    def test_detects_newer_and_limits_automatic_check(self):
        with patch('urllib.request.urlopen', return_value=self.response()) as request:
            result = self.checker.check('1.0.7')
            self.assertTrue(result['newer'])
            self.assertTrue(self.checker.check('1.0.7')['skipped'])
            self.assertEqual(request.call_count, 1)
            self.assertEqual(request.call_args.args[0].full_url, API)

    def test_disabled_automatic_still_allows_manual_check(self):
        self.checker.set_automatic(False)
        self.assertFalse(self.checker.due())
        with patch('urllib.request.urlopen', return_value=self.response('v1.0.7')):
            self.assertFalse(self.checker.check('1.0.7', manual=True)['newer'])

    def test_downgrade_and_prerelease_do_not_prompt(self):
        for response in (self.response('v1.0.6'), self.response(prerelease=True)):
            with patch('urllib.request.urlopen', return_value=response):
                self.assertFalse(self.checker.check('1.0.7', manual=True)['newer'])

    def test_untrusted_release_link_rejected(self):
        with patch('urllib.request.urlopen', return_value=self.response(html_url='https://elsewhere.invalid')):
            with self.assertRaises(ValueError):
                self.checker.check('1.0.7')
        self.assertFalse(self.checker.path.exists())

    def test_offline_does_not_mark_success(self):
        with patch('urllib.request.urlopen', side_effect=OSError('offline')):
            with self.assertRaises(OSError):
                self.checker.check('1.0.7')
        self.assertTrue(self.checker.due())


if __name__ == '__main__':
    unittest.main()
