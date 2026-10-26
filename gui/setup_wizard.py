"""三步式首次配置向导。"""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from wubi_settings import APP_NAME, APP_VER, RimeConfig, SCHEMAS
from wubi_settings import SchemaCard


class WizardPage(QWizardPage):
    def __init__(self, wizard, step, title, description):
        super().__init__(wizard)
        self.flow = wizard
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 24)
        layout.setSpacing(14)

        step_label = QLabel(f"青石五笔  /  {step} — 03")
        step_label.setObjectName("stepCount")
        layout.addWidget(step_label)

        title_label = QLabel(title)
        title_label.setObjectName("wizardTitle")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        desc = QLabel(description)
        desc.setObjectName("wizardText")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.content = QVBoxLayout()
        self.content.setSpacing(10)
        layout.addLayout(self.content, 1)


class SchemaPage(WizardPage):
    def __init__(self, wizard):
        super().__init__(
            wizard,
            "01",
            "选择默认五笔方案",
            "之后仍可在设置中心切换方案。",
        )
        self.setTitle("")
        self.group = QButtonGroup(self)
        self.radios = {}

        for sid, title, detail in SCHEMAS:
            row = SchemaCard(sid, title, detail, sid == wizard.selected_schema)
            row.setMinimumHeight(90)
            row.set_checked(sid == wizard.selected_schema)
            radio = row.radio
            self.radios[sid] = (radio, row)
            row.clicked.connect(lambda key: self._select(key, True, None))
            self.content.addWidget(row)

        self.content.addStretch(1)

    def _select(self, sid, checked, card):
        if checked:
            self.flow.selected_schema = sid
            for key, (radio, item) in self.radios.items():
                item.set_checked(key == sid)


class DisplayPage(WizardPage):
    def __init__(self, wizard):
        super().__init__(
            wizard,
            "02",
            "调整候选窗显示",
            "选择顺手的排列与数量，之后可在设置中心继续调整。",
        )
        self.setTitle("")
        panel = QFrame()
        panel.setObjectName("wizardHero")
        grid = QGridLayout(panel)
        grid.setContentsMargins(0, 24, 0, 20)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(14)

        grid.addWidget(QLabel("候选词数量"), 0, 0)
        self.page_size = QSpinBox()
        self.page_size.setRange(3, 10)
        self.page_size.setValue(wizard.page_size)
        self.page_size.setAccessibleName("每页候选词数量")
        grid.addWidget(self.page_size, 0, 1)
        grid.addWidget(QLabel("个"), 0, 2)

        grid.addWidget(QLabel("候选窗主题"), 1, 0)
        self.theme = QComboBox()
        for key, skin in wizard.cfg.SKINS.items():
            self.theme.addItem(skin["name"], key)
        theme_index = self.theme.findData(wizard.style["color_scheme"])
        self.theme.setCurrentIndex(max(theme_index, 0))
        self.theme.setAccessibleName("候选窗主题")
        grid.addWidget(self.theme, 1, 1, 1, 2)

        self.horizontal = QCheckBox("横排显示候选词")
        self.horizontal.setChecked(wizard.style["horizontal"])
        self.inline = QCheckBox("编码显示在光标处")
        self.inline.setChecked(wizard.style["inline_preedit"])
        grid.addWidget(self.horizontal, 2, 0, 1, 3)
        grid.addWidget(self.inline, 3, 0, 1, 3)

        self.content.addWidget(panel)
        hint = QLabel("横排适合连续输入；纵排更便于逐项查看。")
        hint.setObjectName("hint")
        self.content.addWidget(hint)
        self.content.addStretch(1)


class SummaryPage(WizardPage):
    def __init__(self, wizard):
        super().__init__(
            wizard,
            "03",
            "检查并完成设置",
            "完成后会保存配置，并尝试重新部署青石五笔。",
        )
        self.setTitle("")
        self.summary = QLabel()
        self.summary.setObjectName("wizardText")
        self.summary.setWordWrap(True)

        panel = QFrame()
        panel.setObjectName("wizardHero")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 24, 0, 20)
        panel_layout.addWidget(self.summary)
        self.content.addWidget(panel)
        self.content.addStretch(1)

    def initializePage(self):
        schema = next((name for sid, name, _ in SCHEMAS if sid == self.flow.selected_schema), "五笔 86")
        theme = self.flow.display_page.theme.currentText()
        layout = "横排候选" if self.flow.display_page.horizontal.isChecked() else "纵排候选"
        inline = "编码显示在光标处" if self.flow.display_page.inline.isChecked() else "编码显示在候选窗"
        count = self.flow.display_page.page_size.value()
        self.summary.setText(
            f"默认方案：{schema}\n\n"
            f"候选窗：{theme} · {layout}\n\n"
            f"每页候选：{count} 个\n\n"
            f"编码位置：{inline}"
        )


class SetupWizard(QDialog):
    def __init__(self, cfg=None, parent=None):
        super().__init__(parent)
        self.cfg = cfg or RimeConfig()
        current = self.cfg.current_schema()
        self.selected_schema = current if current in {sid for sid, _, _ in SCHEMAS} else "wubi86"
        self.page_size = self.cfg.page_size()
        self.style = self.cfg.weasel_style()

        self.setWindowTitle(f"{APP_NAME} · 配置向导")
        icon = QIcon(os.path.join(os.path.dirname(__file__), "qingshi-mark.png"))
        self.setWindowIcon(icon)
        self.setMinimumSize(640, 590)
        self.resize(700, 620)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        actions = QHBoxLayout()
        actions.setContentsMargins(36, 12, 36, 24)
        self.back_button = QPushButton("上一步")
        self.back_button.setObjectName("ghost")
        self.back_button.clicked.connect(self.back)
        actions.addWidget(self.back_button)
        actions.addStretch()
        cancel_button = QPushButton("取消")
        cancel_button.setObjectName("ghost")
        cancel_button.clicked.connect(self.reject)
        actions.addWidget(cancel_button)
        self.next_button = QPushButton("继续")
        self.next_button.setObjectName("primary")
        self.next_button.clicked.connect(self.next)
        actions.addWidget(self.next_button)
        self.finish_button = QPushButton("应用并完成")
        self.finish_button.setObjectName("primary")
        self.finish_button.clicked.connect(self.accept)
        actions.addWidget(self.finish_button)
        outer.addLayout(actions)

        self.pages.addWidget(SchemaPage(self))
        self.display_page = DisplayPage(self)
        self.pages.addWidget(self.display_page)
        self.pages.addWidget(SummaryPage(self))
        self._show_step(0)

    def page(self, index):
        return self.pages.widget(index)

    def _show_step(self, index):
        self.pages.setCurrentIndex(index)
        self.back_button.setVisible(index > 0)
        self.next_button.setVisible(index < 2)
        self.finish_button.setVisible(index == 2)
        if index == 2:
            self.page(2).initializePage()

    def next(self):
        self._show_step(min(2, self.pages.currentIndex() + 1))

    def back(self):
        self._show_step(max(0, self.pages.currentIndex() - 1))

    def accept(self):
        style = self.cfg.weasel_style()
        style.update({
            "color_scheme": self.display_page.theme.currentData(),
            "font_face": style["font_face"],
            "font_point": style["font_point"],
            "horizontal": self.display_page.horizontal.isChecked(),
            "inline_preedit": self.display_page.inline.isChecked(),
            "round_corner": style["round_corner"],
        })
        try:
            self.cfg.write_default(self.selected_schema, self.display_page.page_size.value())
            self.cfg.write_weasel(style)
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return

        deployed = self.cfg.deploy(wait=True)
        if deployed:
            self.cfg.restart_server()
        message = "设置已保存并重新部署。" if deployed else "设置已保存，部署未完成。请在设置中心重试重新部署。"
        QMessageBox.information(self, "青石五笔已配置", message)
        super().accept()
