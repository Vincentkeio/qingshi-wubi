"""共享的青石五笔桌面界面主题。"""

QSS = """
* { font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif; }
QMainWindow, QWidget#root { background: #f7f7f7; color: #252525; }
QWidget#topbar { background: #ffffff; border-bottom: 1px solid #e9e9e9; }
QLabel#brandMark { background: #131313; color: #ffffff; border-radius: 10px; font-size: 18px; font-weight: 700; }
QLabel#brandTitle { color: #252525; font-size: 16px; font-weight: 700; }
QLabel#brandSub, QLabel#muted { color: #737373; font-size: 12px; }
QWidget#nav { background: #ffffff; border-right: 1px solid #e9e9e9; }
QLabel#navSection { color: #939393; font-size: 10px; font-weight: 700; letter-spacing: 1px; }
QListWidget#navList { border: 0; background: transparent; outline: 0; padding: 6px 10px; }
QListWidget#navList::item { height: 42px; border-radius: 7px; padding-left: 12px; color: #252525; font-size: 13px; margin: 2px 0; }
QListWidget#navList::item:selected { background: #f1f1f1; color: #252525; font-weight: 600; border-left: 3px solid #252525; padding-left: 9px; }
QListWidget#navList::item:hover:!selected { background: #f7f7f7; color: #252525; }
QLabel#pageTitle, QLabel#h1 { color: #252525; font-size: 22px; font-weight: 700; }
QLabel#pageDesc, QLabel#desc { color: #737373; font-size: 12px; }
QLabel#sectionTitle { color: #252525; font-size: 14px; font-weight: 650; }
QLabel#sectionBadge { background: #252525; color: #ffffff; border-radius: 13px; font-size: 12px; font-weight: 700; }
QLabel#sectionH1 { color: #252525; font-size: 16px; font-weight: 700; }
QLabel#fieldLabel { color: #252525; font-size: 12px; font-weight: 600; }
QFrame#sectionHeader { border-bottom: 1px solid #e7e7e7; }
QLabel#sectionNumber { color: #252525; background: #f1f1f1; border-radius: 6px; font-size: 11px; font-weight: 700; }
QGroupBox { background: #ffffff; border: 1px solid #e9e9e9; border-radius: 9px; margin-top: 14px; padding: 16px 16px 12px; color: #252525; font-size: 13px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 14px; padding: 0 6px; background: transparent; color: #252525; font-size: 12px; font-weight: 600; }
QLabel { color: #252525; font-size: 13px; }
QLabel#hint { color: #797979; font-size: 12px; font-weight: 400; }
QPushButton { min-height: 34px; padding: 0 14px; border: 1px solid #dfdfdf; border-radius: 6px; background: #ffffff; color: #252525; font-size: 12px; }
QPushButton:hover { border-color: #9f9f9f; background: #f8f8f8; color: #252525; }
QPushButton:pressed { background: #efefef; }
QPushButton:focus { border: 2px solid #252525; }
QPushButton#primary { background: #252525; border: 1px solid #252525; color: #ffffff; font-weight: 650; }
QPushButton#primary:hover { background: #252525; border-color: #252525; }
QPushButton#primary:pressed { background: #252525; }
QPushButton#ghost { background: transparent; border-color: transparent; color: #252525; }
QPushButton#ghost:hover { background: #f3f3f3; color: #252525; }
QPushButton#link { background: transparent; border: 0; color: #252525; padding: 0 4px; }
QRadioButton, QCheckBox { color: #252525; font-size: 13px; spacing: 8px; }
QRadioButton::indicator { width: 16px; height: 16px; border: 1px solid #bababa; background: #ffffff; }
QCheckBox::indicator { width: 16px; height: 16px; border: 0; background: transparent; image: url("@GUI@/check-off.svg"); }
QRadioButton::indicator { border-radius: 8px; }
QRadioButton::indicator:checked { border: 1px solid #252525; border-radius: 8px; background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 #252525, stop:0.40 #252525, stop:0.46 #ffffff, stop:1 #ffffff); }
QCheckBox::indicator:checked { image: url("@GUI@/check-on.svg"); }
QRadioButton::indicator:disabled { border-color: #dfdfdf; background: #f5f5f5; }
QCheckBox::indicator:disabled { image: url("@GUI@/check-off.svg"); }
QSpinBox, QComboBox, QLineEdit { min-height: 30px; padding: 0 9px; border: 1px solid #dfdfdf; border-radius: 6px; background: #ffffff; color: #252525; font-size: 12px; }
QSpinBox:focus, QComboBox:focus, QLineEdit:focus { border: 2px solid #252525; }
QComboBox::drop-down { border: 0; width: 24px; }
QFrame#footer { background: #ffffff; border-top: 1px solid #e9e9e9; }
QFrame#schemaCard { background: #ffffff; border: 2px solid #e6e6e6; border-radius: 8px; }
QFrame#schemaCard:hover { border-color: #b2b2b2; background: #fdfdfd; }
QFrame#schemaCard[checked="true"] { border: 2px solid #252525; background: #f6f6f6; }
QLabel#schemaName { color: #252525; font-size: 14px; font-weight: 650; }
QLabel#schemaDetail { color: #737373; font-size: 11px; font-weight: 400; }
QLabel#badge { color: #252525; background: #efefef; border-radius: 4px; padding: 4px 9px; font-size: 12px; font-weight: 650; }
QFrame#statusPanel { background: #f8f8f8; border: 1px solid #e9e9e9; border-radius: 8px; }
QFrame#candidatePanel { background: #ffffff; border: 1px solid #e6e6e6; border-radius: 9px; }
QFrame#settingsDivider { background: #ececec; border: 0; max-height: 1px; }
QFrame#metricCard { background: #ffffff; border: 1px solid #e6e6e6; border-radius: 9px; }
QFrame#shortcutRow { background: #ffffff; border: 1px solid #eaeaea; border-radius: 7px; }
QTableWidget { background: #ffffff; border: 1px solid #eaeaea; border-radius: 8px; gridline-color: #f2f2f2; font-size: 13px; selection-background-color: #f1f1f1; selection-color: #252525; }
QTableWidget::item { padding: 7px 9px; color: #252525; border: 0; }
QTableWidget::item:selected { background: #f1f1f1; color: #252525; }
QHeaderView::section { background: #f9f9f9; color: #252525; border: 0; border-bottom: 1px solid #eaeaea; padding: 8px 9px; font-size: 12px; font-weight: 600; }
QTableCornerButton::section { background: #f9f9f9; border: 0; }
QLabel#metricValue { color: #252525; font-size: 21px; font-weight: 700; }
QLabel#shortcutChip { color: #252525; background: #f1f1f1; border-radius: 5px; padding: 6px 10px; font-family: Consolas, monospace; font-size: 11px; }
QFrame#candidatePreview { background: #ffffff; border: 1px solid #e4e4e4; border-radius: 8px; }
QLabel#previewSelected { background: #252525; color: #ffffff; border-radius: 4px; padding: 5px 8px; font-weight: 600; }
QFrame#footer, QFrame#statusPanel, QFrame#schemaCard { outline: none; }
QScrollArea { border: 0; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; border: 0; }
QScrollBar::handle:vertical { background: #dedede; border-radius: 4px; min-height: 32px; }
QScrollBar::handle:vertical:hover { background: #c7c7c7; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; border: 0; background: transparent; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 0; border: 0; }
QScrollBar::handle:horizontal { background: #dedede; border-radius: 4px; min-width: 32px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; border: 0; background: transparent; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
QTextEdit { border: 1px solid #dfdfdf; border-radius: 6px; background: #ffffff; color: #252525; font-size: 12px; }
QSlider::groove:horizontal { height: 4px; background: #e4e4e4; border-radius: 2px; }
QSlider::handle:horizontal { width: 16px; margin: -6px 0; border-radius: 8px; background: #252525; }
QWizard, QWizardPage { background: #f7f7f7; }
QWizard QLabel#stepCount { color: #252525; font-size: 11px; font-weight: 700; }
QWizard QLabel#wizardTitle { color: #252525; font-size: 21px; font-weight: 700; }
QWizard QLabel#wizardText { color: #737373; font-size: 12px; }
QWizard QFrame#wizardHero { background: #ffffff; border: 1px solid #e9e9e9; border-radius: 10px; }
QWizard::separator { height: 1px; background: #e9e9e9; }
"""


QSS += """
QWidget { color: #202020; font-size: 13px; }
QMainWindow, QDialog, QWizard, QWizardPage, QWidget#root { background: #fafafa; }
QWidget#topbar, QWidget#nav, QFrame#footer { background: transparent; border: none; }
QLabel { background: transparent; }
QLabel#brandMark { background: transparent; }
QLabel#brandTitle { font-size: 16px; font-weight: 600; }
QLabel#brandSub, QLabel#muted, QLabel#desc, QLabel#pageDesc, QLabel#hint,
QLabel#wizardText, QLabel#schemaDetail { color: #626262; font-size: 12px; font-weight: 400; }
QLabel#h1, QLabel#pageTitle, QLabel#wizardTitle { color: #171717; font-size: 23px; font-weight: 600; }
QLabel#navSection, QLabel#stepCount { color: #626262; font-size: 11px; font-weight: 600; }
QLabel#sectionTitle, QLabel#sectionH1 { color: #202020; font-size: 14px; font-weight: 600; }
QFrame#sectionHeader, QFrame#settingsDivider { background: transparent; border: none; }
QLabel#sectionNumber { color: #707070; background: transparent; }
QGroupBox { background: transparent; border: none; margin-top: 20px; padding: 16px 0 8px; font-size: 14px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 0; padding: 0; color: #202020; }
QPushButton { min-height: 36px; padding: 0 16px; border: none; border-radius: 6px; background: #eeeeee; color: #303030; }
QPushButton:hover { background: #e5e5e5; color: #111111; }
QPushButton:pressed { background: #d8d8d8; padding-top: 1px; }
QPushButton:focus { border: 1px solid #353535; }
QPushButton:disabled { color: #949494; background: #f1f1f1; }
QPushButton#primary { background: #202020; color: white; font-weight: 600; border: none; }
QPushButton#primary:hover { background: #383838; }
QPushButton#primary:pressed { background: #080808; }
QPushButton#primary:disabled { background: #d9d9d9; color: #777777; }
QPushButton#ghost, QPushButton#link { background: transparent; color: #535353; }
QPushButton#ghost:hover, QPushButton#link:hover { background: #ededed; color: #171717; }
QRadioButton, QCheckBox { color: #333333; spacing: 9px; }
QRadioButton::indicator { border-color: #929292; }
QRadioButton::indicator:checked { image: url("@GUI@/radio-on.svg"); background: transparent; border: none; width: 18px; height: 18px; }
QCheckBox:focus, QRadioButton:focus { color: black; background: #e8e8e8; border-radius: 3px; }
QCheckBox:disabled, QRadioButton:disabled { color: #999999; }
QSpinBox, QComboBox, QLineEdit { min-height: 34px; padding: 0 10px; border: 1px solid transparent; border-radius: 5px; background: #eeeeee; color: #202020; }
QSpinBox { padding-right: 32px; }
QSpinBox:hover, QComboBox:hover, QLineEdit:hover { background: #e8e8e8; }
QSpinBox:focus, QComboBox:focus, QLineEdit:focus { border: 1px solid #454545; background: white; }
QSpinBox:disabled, QComboBox:disabled, QLineEdit:disabled { color: #999999; background: #f3f3f3; }
QSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 27px; height: 17px; margin: 2px 3px 0 0; background: #dedede; border: none; border-top-left-radius: 3px; border-top-right-radius: 3px; }
QSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 27px; height: 17px; margin: 0 3px 2px 0; background: #dedede; border: none; border-bottom-left-radius: 3px; border-bottom-right-radius: 3px; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #cccccc; }
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed { background: #252525; }
QSpinBox::up-arrow { image: url("@GUI@/triangle-up.svg"); width: 8px; height: 5px; }
QSpinBox::down-arrow { image: url("@GUI@/triangle-down.svg"); width: 8px; height: 5px; }
QSpinBox::up-arrow:pressed { image: url("@GUI@/triangle-up-white.svg"); }
QSpinBox::down-arrow:pressed { image: url("@GUI@/triangle-down-white.svg"); }
QSpinBox::up-arrow:disabled, QSpinBox::up-arrow:off { image: url("@GUI@/triangle-up-disabled.svg"); }
QSpinBox::down-arrow:disabled, QSpinBox::down-arrow:off { image: url("@GUI@/triangle-down-disabled.svg"); }
QComboBox { padding-right: 30px; }
QComboBox::drop-down { width: 28px; border: none; }
QComboBox::down-arrow { image: url("@GUI@/triangle-down.svg"); width: 8px; height: 5px; }
QComboBox QAbstractItemView { background: white; color: #202020; selection-background-color: #e7e7e7; selection-color: #111111; outline: none; padding: 5px; border: 1px solid #dddddd; }
QFrame#schemaCard { background: #f0f0f0; border: 1px solid transparent; border-radius: 7px; }
QFrame#schemaCard:hover { background: #e9e9e9; }
QFrame#schemaCard[checked="true"] { background: #e2e2e2; border: 1px solid transparent; }
QFrame#schemaCard:focus { border-color: #555555; }
QLabel#badge { background: transparent; color: #353535; font-size: 11px; padding: 0; }
QFrame#statusPanel, QFrame#candidatePanel, QFrame#metricCard, QFrame#shortcutRow,
QFrame#wizardHero { background: transparent; border: none; }
QLabel#metricValue { color: #202020; font-size: 25px; font-weight: 600; }
QLabel#shortcutChip { color: #353535; background: #eeeeee; }
QTableWidget, QTableWidget::item, QHeaderView::section { border: none; gridline-color: transparent; }
QTextEdit { border: none; border-radius: 5px; background: #eeeeee; color: #202020; padding: 8px; }
QWizard::separator { height: 0; background: transparent; }
QFrame#wizardHero { background: transparent; border: none; }
QProgressBar { border: none; border-radius: 3px; background: #e5e5e5; height: 6px; text-align: center; }
QProgressBar::chunk { background: #202020; border-radius: 3px; }
"""
from pathlib import Path
QSS = QSS.replace("@GUI@", Path(__file__).resolve().parent.as_posix())


def apply_theme(app):
    from PyQt6.QtGui import QColor, QPalette
    app.setStyle("Fusion")
    palette = app.palette()
    for role, color in {
        QPalette.ColorRole.Window: "#fafafa", QPalette.ColorRole.WindowText: "#202020",
        QPalette.ColorRole.Base: "#ffffff", QPalette.ColorRole.Text: "#202020",
        QPalette.ColorRole.Button: "#eeeeee", QPalette.ColorRole.ButtonText: "#202020",
        QPalette.ColorRole.Highlight: "#252525", QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.Link: "#353535",
    }.items():
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(QSS)
