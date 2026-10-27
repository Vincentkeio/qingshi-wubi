"""Keep user learning disabled without changing intentional phrase ordering."""
from pathlib import Path
import os
import tempfile
import yaml

SCHEMAS = ('wubi86', 'wubi98', 'wubi06')
FIXED = {'enable_user_dict': False, 'enable_sentence': False,
         'enable_encoder': False, 'encode_commit_history': False}


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.qingshi-', dir=path.parent)
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def ensure_fixed_order(directory):
    changed = []
    for schema in SCHEMAS:
        path = Path(directory) / (schema + '.custom.yaml')
        content = yaml.safe_load(path.read_text(encoding='utf-8')) if path.exists() else {}
        if content is None:
            content = {}
        if not isinstance(content, dict) or not isinstance(content.get('patch', {}), dict):
            raise ValueError(f'{path.name} 不是有效的方案配置')
        patch = content.setdefault('patch', {})
        before = yaml.safe_dump(content, allow_unicode=True, sort_keys=False)
        nested = patch.get('translator')
        if isinstance(nested, dict):
            for key, value in FIXED.items():
                if key in nested:
                    nested[key] = value
        for key, value in FIXED.items():
            patch['translator/' + key] = value
        after = yaml.safe_dump(content, allow_unicode=True, sort_keys=False)
        if not path.exists() or before != after:
            atomic_write(path, after.encode('utf-8'))
            changed.append(path.name)
    return changed
