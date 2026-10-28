"""Validated global shortcut settings and transactional Rime configuration."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import yaml
from fixed_order import atomic_write

FILE = 'qingshi_hotkeys.yaml'
SCHEMAS = ('wubi86', 'wubi98', 'wubi06')
ACTIONS = (
    ('ascii_mode', '中英文切换', ('Shift', ''), '状态切换'),
    ('traditional', '简繁转换', ('Control+Shift+F', 'Control+Shift+T'), '状态切换'),
    ('full_shape', '全角 / 半角', ('Shift+space', ''), '状态切换'),
    ('ascii_punct', '中英标点', ('Control+period', ''), '状态切换'),
    ('extended_charset', '增广字集', ('Control+Shift+5', ''), '状态切换'),
    ('page_up', '上一页', ('minus', 'comma'), '翻页'),
    ('page_down', '下一页', ('equal', 'period'), '翻页'),
)
DEFAULTS = {key: list(keys) for key, label, keys, group in ACTIONS}
LABELS = {key: label for key, label, keys, group in ACTIONS}
SYMBOLS = {'space': '空格', 'minus': '-', 'equal': '=', 'comma': ',', 'period': '.',
           'grave': '`', 'bracketleft': '[', 'bracketright': ']', 'backslash': '\\',
           'semicolon': ';', 'apostrophe': "'", 'slash': '/', 'Page_Up': 'PgUp', 'Page_Down': 'PgDn'}
SHIFTED = dict(zip('1234567890', ('exclam','at','numbersign','dollar','percent','asciicircum','ampersand','asterisk','parenleft','parenright')))
SHIFTED.update({'minus':'underscore','equal':'plus','comma':'less','period':'greater',
                'grave':'asciitilde','bracketleft':'braceleft','bracketright':'braceright',
                'backslash':'bar','semicolon':'colon','apostrophe':'quotedbl','slash':'question'})
BASE_OF = {value: key for key, value in SHIFTED.items()}
SPECIAL = {'space', *SYMBOLS, 'Tab', 'Return', 'Escape', 'BackSpace', 'Delete', 'Caps_Lock',
           'Home', 'End', 'Left', 'Right', 'Up', 'Down', 'Insert'}
TOGGLE = {'ascii_mode','traditional','simplification','full_shape','ascii_punct','extended_charset'}
EDITING = [('Control+p','Up'),('Control+n','Down'),('Control+b','Left'),('Control+f','Right'),
           ('Control+a','Home'),('Control+e','End'),('Control+d','Delete'),('Control+k','Shift+Delete'),
           ('Control+h','BackSpace'),('Control+g','Escape'),('Control+bracketleft','Escape'),
           ('Shift+Tab','Shift+Left'),('Tab','Shift+Right')]


def canonical(value):
    if not isinstance(value, str):
        raise ValueError('快捷键格式无效')
    if not value or value == 'Shift':
        return value
    parts = value.split('+')
    modifiers, key = parts[:-1], parts[-1]
    if len(set(modifiers)) != len(modifiers) or any(x not in ('Control','Alt','Shift') for x in modifiers):
        raise ValueError('只支持 Ctrl、Alt、Shift 组合，Windows 快捷键由系统管理')
    if 'Shift' in modifiers and key in BASE_OF:
        key = BASE_OF[key]
    if len(key) == 1 and key.isascii() and key.isalpha():
        key = key.upper() if 'Shift' in modifiers else key.lower()
    if not (key in SPECIAL or re.fullmatch(r'[a-zA-Z0-9]|F(?:[1-9]|1[0-9]|2[0-4])', key)):
        raise ValueError('不支持这个按键')
    return '+'.join([m for m in ('Control','Alt','Shift') if m in modifiers] + [key])


def display(value):
    if not value:
        return '未设置'
    return ' + '.join({'Control':'Ctrl', **SYMBOLS}.get(x, x.upper() if len(x) == 1 and x.isalpha() else x)
                      for x in value.split('+'))


def validate(values):
    if not isinstance(values, dict):
        raise ValueError('快捷键配置不完整')
    # 旧版本遗留项（如已删除的「切换方案菜单」）直接丢弃，避免升级后配置读不出来
    values = {key: value for key, value in values.items() if key in DEFAULTS}
    if set(values) != set(DEFAULTS):
        raise ValueError('快捷键配置不完整')
    result, seen = {}, {}
    for action, label, defaults, group in ACTIONS:
        keys = values[action]
        if not isinstance(keys, (list, tuple)) or len(keys) != 2:
            raise ValueError(label + '需要主键和备用键两个位置')
        result[action] = []
        for value in keys:
            key = canonical(value)
            if key:
                parts = key.split('+')
                base, modifiers = parts[-1], set(parts[:-1])
                if key == 'Shift' and action != 'ascii_mode':
                    raise ValueError('单独 Shift 仅可用于中英文切换')
                if key != 'Shift':
                    if base in ('Escape','Return','BackSpace','Delete','Tab','Caps_Lock') and not modifiers:
                        raise ValueError(display(key) + '是基础输入键，请使用组合键')
                    if not modifiers and not base.startswith('F') and action not in ('page_up','page_down'):
                        raise ValueError(label + '请使用组合键或 F1–F24')
                    if re.fullmatch('[a-zA-Z0-9]', base) and not (modifiers & {'Control','Alt'}):
                        raise ValueError('字母和数字请同时使用 Ctrl 或 Alt，避免占用正常输入')
                    if action in ('page_up','page_down') and not modifiers and base not in (
                            'minus','equal','comma','period','bracketleft','bracketright','Page_Up','Page_Down') and not base.startswith('F'):
                        raise ValueError('翻页不能占用字母、数字或基础输入键')
                    if key in ('Alt+F4','Alt+Tab','Alt+Shift+Tab','Control+Alt+Delete','Control+Shift+Escape','Control+space'):
                        raise ValueError(display(key) + '由系统管理，请换一个组合')
                    if 'Control' in modifiers and 'Alt' not in modifiers and base in '123456789' and len(base) == 1:
                        if not ('Shift' in modifiers and base == '5'):
                            raise ValueError('Ctrl＋数字及 Ctrl＋Shift＋数字用于候选调序，请换一个组合')
                if key in seen:
                    raise ValueError(f'{display(key)} 同时分配给了「{seen[key]}」和「{label}」')
                seen[key] = label
            result[action].append(key)
    return result


def load(directory, schema='wubi86'):
    path = Path(directory) / FILE
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding='utf-8'))
        except (OSError, yaml.YAMLError) as error:
            raise ValueError('无法读取快捷键配置，请检查文件或恢复默认') from error
        if not isinstance(data, dict) or data.get('version') != 1:
            raise ValueError('快捷键配置文件格式无效')
        return validate(data.get('bindings'))
    values = deepcopy(DEFAULTS)
    custom = Path(directory) / (schema + '.custom.yaml')
    if custom.is_file():
        try:
            data = yaml.safe_load(custom.read_text(encoding='utf-8')) or {}
        except yaml.YAMLError as error:
            raise ValueError('当前方案配置格式无效，请先修复配置文件') from error
        patch = data.get('patch', {}) if isinstance(data, dict) else {}
        patch = patch if isinstance(patch, dict) else {}
        if patch.get('ascii_composer/switch_key/Shift_L') == 'noop':
            values['ascii_mode'][0] = ''
    return values


def accepts(key):
    if not key or key == 'Shift':
        return []
    parts = key.split('+')
    result = [key]
    if 'Shift' in parts[:-1] and parts[-1] in SHIFTED:
        result.append('+'.join(parts[:-1] + [SHIFTED[parts[-1]]]))
    return result


def managed(binding):
    return (binding.get('toggle') in TOGGLE or binding.get('select') == '.next' or
            binding.get('send') in ('Page_Up','Page_Down'))


def put(patch, name, value):
    parts = name.split('/')
    parent = patch.get(parts[0])
    if isinstance(parent, dict) and len(parts) > 1:
        cursor = parent
        for part in parts[1:-1]:
            cursor = cursor.get(part, {}) if isinstance(cursor, dict) else {}
        if isinstance(cursor, dict):
            cursor.pop(parts[-1], None)
    patch[name] = value


def existing_bindings(patch):
    bindings = patch.get('key_binder/bindings', (patch.get('key_binder') or {}).get('bindings', []))
    return [deepcopy(x) for x in bindings if isinstance(x, dict) and not managed(x)] if isinstance(bindings, list) else []


def apply(directory, values, shift_commit=True):
    values = validate(values)
    shift_commit = bool(shift_commit) and 'Shift' in values['ascii_mode']
    directory = Path(directory)
    fingerprint = hashlib.sha256(json.dumps([values, bool(shift_commit)], sort_keys=True).encode()).hexdigest()
    staged = {}
    names = ['default.custom.yaml'] + [sid + '.custom.yaml' for sid in SCHEMAS]
    for name in names:
        path = directory / name
        content = yaml.safe_load(path.read_text(encoding='utf-8')) if path.is_file() else {}
        content = content or {}
        if not isinstance(content, dict) or not isinstance(content.get('patch', {}), dict):
            raise ValueError(name + '不是有效的配置文件')
        patch = content.setdefault('patch', {})
        put(patch, 'qingshi/hotkeys_fingerprint', fingerprint)
        keep = existing_bindings(patch)
        if name == 'default.custom.yaml':
            editing = [{'when':'composing', 'accept':key, 'send':target} for key, target in EDITING]
            existing = {(x.get('accept'), x.get('when')) for x in keep}
            put(patch, 'key_binder/bindings', [x for x in editing if (x['accept'],x['when']) not in existing] + keep)
            # 方案菜单已取消快捷键入口：显式清空，盖掉 default.yaml 里的 F4 / Ctrl+`
            put(patch, 'switcher/hotkeys', [])
        else:
            bindings = keep[:]
            for action, label, defaults, group in ACTIONS:
                for key in values[action]:
                    for accept in accepts(key):
                        if action in ('page_up','page_down'):
                            when = 'paging' if action == 'page_up' and key == 'comma' else 'has_menu'
                            bindings.append({'when':when, 'accept':accept,
                                             'send':'Page_Up' if action == 'page_up' else 'Page_Down'})
                        else:
                            bindings.append({'when':'always', 'accept':accept, 'toggle':action})
            put(patch, 'key_binder/bindings', bindings)
            style = ('commit_code' if shift_commit else 'inline_ascii') if 'Shift' in values['ascii_mode'] else 'noop'
            put(patch, 'ascii_composer/switch_key/Shift_L', style)
            put(patch, 'ascii_composer/switch_key/Shift_R', style)
            schema_file = directory / name.replace('.custom.yaml', '.schema.yaml')
            schema = yaml.safe_load(schema_file.read_text(encoding='utf-8')) if schema_file.is_file() else {}
            processors = list(((schema or {}).get('engine') or {}).get('processors') or [
                'ascii_composer','recognizer','key_binder','speller','selector','punctuator','navigator','express_editor'])
            processors = [x for x in processors if x != 'key_binder']
            processors.insert(0, 'key_binder')
            put(patch, 'engine/processors', processors)
        staged[path] = yaml.safe_dump(content, allow_unicode=True, sort_keys=False).encode('utf-8')
    staged[directory / FILE] = yaml.safe_dump({'version':1, 'bindings':values}, allow_unicode=True, sort_keys=False).encode('utf-8')
    previous = {path:path.read_bytes() if path.exists() else None for path in staged}
    try:
        for path, data in staged.items():
            if data != previous[path]:
                atomic_write(path, data)
    except BaseException:
        for path, data in previous.items():
            if data is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, data)
        raise
    return values


def needs_deploy(directory):
    directory = Path(directory)
    if not (directory / FILE).is_file():
        return False
    for name in ['default'] + list(SCHEMAS):
        custom = yaml.safe_load((directory / (name + '.custom.yaml')).read_text(encoding='utf-8')) or {}
        expected = custom.get('patch', {}).get('qingshi/hotkeys_fingerprint')
        compiled = directory / 'build' / (name + ('.yaml' if name == 'default' else '.schema.yaml'))
        if not compiled.is_file():
            return True
        actual = yaml.safe_load(compiled.read_text(encoding='utf-8')) or {}
        if not expected or (actual.get('qingshi') or {}).get('hotkeys_fingerprint') != expected:
            return True
    return False
