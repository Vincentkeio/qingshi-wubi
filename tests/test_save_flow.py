"""点「应用」时到底做了什么 —— 用真实的设置窗口跑一遍（离屏）。

重点盯两件事：
  1. 只改外观时**不许重启输入法服务**（重启会打断正在打的字）；
  2. 弹窗文案不能再让人以为要重启。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gui'))

from PyQt6.QtWidgets import QApplication

import wubi_settings as ws

app = QApplication.instance() or QApplication([])

BASE_STYLE = {
    "color_scheme": "qingshi_blue",
    "font_face": "Microsoft YaHei",
    "font_point": 13,
    "horizontal": True,
    "inline_preedit": True,
    "round_corner": 6,
}


class SaveFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='qingshi-save-test-')
        self.addCleanup(self.temp.cleanup)
        self.win = ws.MainWindow()
        self.addCleanup(self.win.deleteLater)
        self.win.cfg = ws.RimeConfig(self.temp.name)
        self.win.cfg.write_weasel(BASE_STYLE)
        self.win.load()

    def _save(self, **patches):
        context = {
            'restart_server': patch.object(self.win.cfg, 'restart_server', return_value=True),
            'reload': patch.object(self.win.cfg, 'reload', return_value=True),
            'deploy': patch.object(self.win.cfg, 'deploy', return_value=True),
            'needs_deploy': patch.object(self.win.cfg, 'appearance_needs_deploy',
                                         return_value=patches.pop('needs_deploy', False)),
            'info': patch.object(ws.QMessageBox, 'information'),
            'dialog': patch.object(ws, 'BusyDialog'),
            # 这两项写真实注册表，测试里必须挡住。
            'beep': patch.object(self.win.cfg, 'set_no_candidate_beep', return_value=True),
            'shift': patch.object(self.win.cfg, 'set_shift_letter_direct', return_value=True),
        }
        started = {k: v.start() for k, v in context.items()}
        self.addCleanup(lambda: [v.stop() for v in context.values()])
        started['dialog'].return_value = MagicMock()
        self.win.save(True)
        return started

    def test_appearance_change_does_not_restart_service(self):
        self.win.combo_scheme.setCurrentIndex(
            self.win.combo_scheme.findData('qingshi_ink'))
        calls = self._save()
        self.assertFalse(calls['restart_server'].called, '改外观不该重启服务')
        self.assertTrue(calls['reload'].called, '改外观应该走热加载')
        message = calls['info'].call_args.args[2]
        self.assertNotIn('重启', message)

    def test_appearance_change_with_pending_deploy_deploys_then_reloads(self):
        self.win.spin_font.setValue(18)
        calls = self._save(needs_deploy=True)
        self.assertFalse(calls['restart_server'].called)
        self.assertTrue(calls['deploy'].called)
        self.assertTrue(calls['reload'].called)

    def test_phrase_change_restarts_service(self):
        self.win.phrases.append(('自定义词', 'zzzz'))
        calls = self._save()
        self.assertTrue(calls['restart_server'].called, '词条是稳定词典，必须重启才生效')
        message = calls['info'].call_args.args[2]
        self.assertIn('词条', message)


if __name__ == '__main__':
    unittest.main()
