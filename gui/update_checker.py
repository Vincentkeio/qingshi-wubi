"""Read official GitHub release metadata. Never download or execute updates."""
from pathlib import Path
import json
import re
import time
import urllib.request
from fixed_order import atomic_write

API = 'https://api.github.com/repos/Vincentkeio/qingshi-wubi/releases/latest'
PREFIX = 'https://github.com/Vincentkeio/qingshi-wubi/releases/tag/'
INTERVAL = 24 * 60 * 60


def version(value):
    found = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', str(value))
    if not found:
        raise ValueError('无法识别的版本号')
    return tuple(map(int, found.groups()))


class UpdateChecker:
    def __init__(self, directory):
        self.path = Path(directory) / 'update_preferences.json'

    def settings(self):
        try:
            result = json.loads(self.path.read_text(encoding='utf-8'))
            return result if isinstance(result, dict) else {}
        except (OSError, ValueError):
            return {}

    def set_automatic(self, enabled):
        state = self.settings()
        state['automatic'] = bool(enabled)
        atomic_write(self.path, json.dumps(state).encode('utf-8'))

    def due(self):
        state = self.settings()
        try:
            last = float(state.get('last_check', 0))
        except (TypeError, ValueError):
            last = 0
        return state.get('automatic', True) is not False and time.time() - last >= INTERVAL

    def check(self, current, manual=False):
        if not manual and not self.due():
            return {'skipped': True}
        request = urllib.request.Request(API, headers={'Accept': 'application/vnd.github+json',
            'User-Agent': 'QingshiWubi-update-checker'})
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('更新信息超出大小限制')
        release = json.loads(raw)
        tag = release.get('tag_name', '')
        newer = not release.get('draft') and not release.get('prerelease') and version(tag) > version(current)
        url = release.get('html_url', '')
        if url != PREFIX + tag:
            raise ValueError('更新来源不是青石官方发布页')
        state = self.settings()
        state['last_check'] = time.time()
        atomic_write(self.path, json.dumps(state).encode('utf-8'))
        return {'newer': bool(newer), 'version': tag.lstrip('v'), 'url': url}
