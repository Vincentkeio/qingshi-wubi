# -*- coding: utf-8 -*-
"""启动设置界面并截图（用于验证外观）"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
import wubi_settings as ws

app = QApplication(sys.argv)
app.setStyleSheet(ws.QSS)
w = ws.MainWindow()
w.show()

out_dir = os.path.dirname(os.path.abspath(__file__))
def shot():
    for idx, name in [(0, "p1_common"), (1, "p2_appearance"), (2, "p3_dict")]:
        w.nav_list.setCurrentRow(idx)
        app.processEvents()
        w.grab().save(os.path.join(out_dir, f"{name}.png"))
    print("saved")
    app.quit()

QTimer.singleShot(1200, shot)
app.exec()
