"""Initialize the symbol preference when upgrading older installations."""
from pathlib import Path
import yaml

from fixed_order import SCHEMAS, atomic_write


def ensure_symbol_preference(directory):
    configs = []
    preference = None
    for schema in SCHEMAS:
        path = Path(directory) / (schema + '.custom.yaml')
        content = yaml.safe_load(path.read_text(encoding='utf-8')) if path.exists() else {}
        content = content or {}
        if not isinstance(content, dict) or not isinstance(content.get('patch', {}), dict):
            raise ValueError(f'{path.name} 不是有效的方案配置')
        patch = content.setdefault('patch', {})
        nested = patch.get('punctuator')
        explicit = patch.get('punctuator/import_preset')
        if explicit is None and isinstance(nested, dict):
            explicit = nested.get('import_preset')
        if preference is None and explicit in ('symbols', 'symbols_direct'):
            preference = explicit
        configs.append((path, content, explicit))

    preference = preference or 'symbols_direct'
    for path, content, explicit in configs:
        if explicit is None:
            content['patch']['punctuator/import_preset'] = preference
            atomic_write(path, yaml.safe_dump(content, allow_unicode=True, sort_keys=False).encode('utf-8'))
