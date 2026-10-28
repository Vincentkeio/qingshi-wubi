"""Backup and update controls in the existing settings visual language."""
from pathlib import Path
from datetime import datetime
from PyQt6.QtCore import QThread, pyqtSignal, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QMessageBox, QCheckBox)
from config_bundle import snapshot, inspect, restore
from fixed_order import atomic_write
from update_checker import UpdateChecker

# 检查到更新时给两个下载入口：官网 + GitHub 发布页
OFFICIAL_WEBSITE = 'https://qingshi.funnyai.wiki/'


class CheckWorker(QThread):
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, checker, current, manual):
        super().__init__()
        self.checker, self.current, self.manual = checker, current, manual

    def run(self):
        try:
            self.ready.emit(self.checker.check(self.current, self.manual))
        except Exception as error:
            self.failed.emit(str(error))


def run_background_check(directory, current):
    from PyQt6.QtWidgets import QApplication
    application = QApplication([])
    application.setQuitOnLastWindowClosed(False)
    checker = UpdateChecker(directory)
    if not checker.due():
        return 0
    worker = CheckWorker(checker, current, False)
    def ready(result):
        if result.get('newer'):
            answer = QMessageBox.question(None, '青石五笔有更新',
                '发现 v' + result['version'] + '，是否打开官方发布页？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(result['url']))
    worker.ready.connect(ready)
    worker.finished.connect(application.quit)
    worker.start()
    return application.exec()


class BackupPage(QWidget):
    def __init__(self, owner, current):
        super().__init__()
        self.owner, self.current = owner, current
        self.checker = UpdateChecker(owner.cfg.dir)
        self.worker = None
        self.pending_close = False
        self.last_result = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)
        self.label(layout, '备份与更新', 'h1')
        self.label(layout, '保存自己的设置、词条和词序，或恢复到另一台电脑。', 'desc')
        self.label(layout, '配置备份', 'sectionTitle')
        self.label(layout, '包含外观、输入习惯、自定义词条、自定义词库、码表及手动词序。', 'hint')
        row = QHBoxLayout()
        export = QPushButton('导出配置…')
        export.clicked.connect(self.export_config)
        restore_button = QPushButton('导入配置…')
        restore_button.clicked.connect(self.import_config)
        row.addWidget(export)
        row.addWidget(restore_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.label(layout, '导入前会自动备份当前配置；历史学习词频不进入备份。', 'hint')
        self.status = self.label(layout, '尚未导入或导出配置。', 'hint')
        layout.addSpacing(16)
        self.label(layout, '固定词序', 'sectionTitle')
        self.label(layout, '三套方案不自动学习、不按使用次数调整候选顺序。\n只有自定义词条和手动词序规则会改变候选位置。', 'hint')
        layout.addSpacing(16)
        self.label(layout, '软件更新', 'sectionTitle')
        self.automatic = QCheckBox('自动检查更新并提示新版本')
        self.automatic.setChecked(self.checker.settings().get('automatic', True))
        self.automatic.toggled.connect(self.set_automatic)
        layout.addWidget(self.automatic)
        self.label(layout, '登录 Windows 或打开设置时检查，每天最多一次。发现新版后提示前往官方下载页。', 'hint')
        row = QHBoxLayout()
        self.check_button = QPushButton('立即检查更新')
        self.check_button.clicked.connect(lambda: self.check_updates(True))
        row.addWidget(self.check_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.update_status = self.label(layout, '当前版本 v' + current, 'hint')
        layout.addStretch(1)
        # Fixture configs used by preview/tests must never initiate network I/O.
        from app_paths import user_directory
        if Path(owner.cfg.dir).resolve() == Path(user_directory()).resolve():
            QTimer.singleShot(2500, lambda: self.check_updates(False))

    @staticmethod
    def label(layout, text, name):
        label = QLabel(text)
        label.setObjectName(name)
        label.setWordWrap(True)
        layout.addWidget(label)
        return label

    def export_config(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出青石配置',
            '青石配置-' + datetime.now().strftime('%Y%m%d') + '.qingshi.zip', '青石配置备份 (*.qingshi.zip)')
        if not path:
            return
        try:
            # Save only when requested: other settings tabs may contain edits.
            if not self.owner.save(False):
                return
            atomic_write(path, snapshot(self.owner.cfg.dir, self.owner.cfg.shift_letter_direct()))
            self.status.setText('配置已导出：' + str(path))
        except Exception as error:
            QMessageBox.warning(self, '导出失败', str(error))

    def import_config(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入青石配置', '', '青石配置备份 (*.qingshi.zip);;ZIP 文件 (*.zip)')
        if not path:
            return
        try:
            if Path(path).stat().st_size > 64 * 1024 * 1024:
                raise ValueError('备份文件过大')
            data = Path(path).read_bytes()
            _, files = inspect(data)
            answer = QMessageBox.question(self, '恢复配置',
                f'备份包含 {len(files)} 个配置文件。\n将替换当前设置、词条和手动词序；导入前会自动保留本机备份。\n是否继续？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            result = restore(self.owner.cfg.dir, data, self.owner.cfg.shift_letter_direct())
            self.owner.cfg.set_shift_letter_direct(result['shift_letter_direct'])
            self.automatic.setChecked(result['automatic_updates'])
            self.owner.load()
            self.status.setText('已恢复配置；原配置备份：' + result['backup'])
            # Imported schemas and dictionaries require a real deployment.
            self.owner.redeploy()
        except Exception as error:
            QMessageBox.warning(self, '导入失败', str(error))

    def set_automatic(self, enabled):
        try:
            self.checker.set_automatic(enabled)
        except OSError as error:
            self.update_status.setText('更新选项保存失败：' + str(error))

    def check_updates(self, manual):
        if self.worker and self.worker.isRunning():
            return
        if not manual and not self.checker.due():
            return
        self.check_button.setEnabled(False)
        self.update_status.setText('正在检查更新…')
        self.worker = CheckWorker(self.checker, self.current, manual)
        self.worker.ready.connect(lambda result: self.update_result(result, manual))
        self.worker.failed.connect(lambda error: self.update_failed(error, manual))
        self.worker.finished.connect(self.worker_finished)
        self.worker.start()

    def worker_finished(self):
        self.check_button.setEnabled(True)
        if self.pending_close:
            self.owner.close()

    def update_result(self, result, manual):
        if result.get('skipped'):
            return
        self.last_result = result
        if not result['newer']:
            self.update_status.setText('当前已是最新正式版本。')
            return
        self.update_status.setText('发现新版本 v' + result['version'])
        if self.pending_close:
            return
        box = QMessageBox(self)
        box.setWindowTitle('青石五笔有更新')
        box.setText('发现新版本 v' + result['version'])
        box.setInformativeText('选择从哪里下载安装包。升级后请重新打开正在使用的程序。')
        website = box.addButton('从官网下载', QMessageBox.ButtonRole.AcceptRole)
        github = box.addButton('从 GitHub 下载', QMessageBox.ButtonRole.ActionRole)
        box.addButton('稍后再说', QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is website:
            QDesktopServices.openUrl(QUrl(OFFICIAL_WEBSITE))
        elif clicked is github:
            QDesktopServices.openUrl(QUrl(result['url']))

    def update_failed(self, error, manual):
        self.update_status.setText('暂时无法检查更新，请稍后重试。')
        if manual and not self.pending_close:
            QMessageBox.warning(self, '检查更新失败', '无法连接官方更新服务，请检查网络后重试。')
