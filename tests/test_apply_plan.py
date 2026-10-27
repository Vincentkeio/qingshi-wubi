"""保存时的执行路径：外观只热加载，词条才重启服务。

这个判断以前埋在 save() 里，改一次就回退一次（出现过「改个配色也重启服务」）。
抽成纯函数后可以直接测。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'gui'))

from wubi_settings import apply_plan


class ApplyPlanTests(unittest.TestCase):
    def test_appearance_never_restarts_the_service(self):
        for needs_deploy in (True, False):
            plan = apply_plan(appearance_changed=True, phrases_changed=False,
                              needs_deploy=needs_deploy)
            self.assertNotEqual(plan, 'restart')
        self.assertEqual(apply_plan(True, False, False), 'reload')
        self.assertEqual(apply_plan(True, False, True), 'deploy+reload')

    def test_phrase_change_restarts_because_it_is_a_stable_dictionary(self):
        self.assertEqual(apply_plan(False, True, False), 'restart')
        self.assertEqual(apply_plan(True, True, True), 'restart')

    def test_plain_setting_change_only_reloads(self):
        self.assertEqual(apply_plan(False, False, False), 'reload')
        self.assertEqual(apply_plan(False, False, True), 'deploy')


if __name__ == '__main__':
    unittest.main()
