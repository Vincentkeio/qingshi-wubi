"""Native shortcut recorders in the existing settings visual language."""
from copy import deepcopy
from PyQt6.QtCore import QEvent, Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QPushButton, QLabel, QFrame, QVBoxLayout, QHBoxLayout, QGridLayout
from hotkeys import ACTIONS, DEFAULTS, SYMBOLS, BASE_OF, canonical, display, validate

PUNCTUATION = {' ':'space','-':'minus','=':'equal',',':'comma','.':'period','`':'grave',
    '[':'bracketleft',']':'bracketright','\\':'backslash',';':'semicolon',"'":'apostrophe','/':'slash',
    '!':'exclam','@':'at','#':'numbersign','$':'dollar','%':'percent','^':'asciicircum',
    '&':'ampersand','*':'asterisk','(':'parenleft',')':'parenright','_':'underscore','+':'plus',
    '<':'less','>':'greater','~':'asciitilde','{':'braceleft','}':'braceright','|':'bar',':':'colon','"':'quotedbl','?':'question'}


def event_key(event):
    code = event.key()
    key = None
    if Qt.Key.Key_F1 <= code <= Qt.Key.Key_F24:
        key = 'F' + str(code - Qt.Key.Key_F1 + 1)
    elif Qt.Key.Key_A <= code <= Qt.Key.Key_Z or Qt.Key.Key_0 <= code <= Qt.Key.Key_9:
        key = chr(code)
    elif 0x20 <= code < 0x7f:
        key = PUNCTUATION.get(chr(code))
    else:
        key = {Qt.Key.Key_PageUp:'Page_Up', Qt.Key.Key_PageDown:'Page_Down',
               Qt.Key.Key_Tab:'Tab', Qt.Key.Key_Return:'Return', Qt.Key.Key_Enter:'Return',
               Qt.Key.Key_CapsLock:'Caps_Lock', Qt.Key.Key_Home:'Home', Qt.Key.Key_End:'End',
               Qt.Key.Key_Left:'Left', Qt.Key.Key_Right:'Right', Qt.Key.Key_Up:'Up', Qt.Key.Key_Down:'Down'}.get(code)
    if not key:
        raise ValueError('不支持这个按键，请使用 Ctrl、Alt、Shift 组合或功能键')
    modifiers = event.modifiers()
    if modifiers & Qt.KeyboardModifier.KeypadModifier:
        raise ValueError('请使用主键盘区录入快捷键')
    if modifiers & Qt.KeyboardModifier.MetaModifier:
        raise ValueError('Windows 快捷键由系统管理，请换一个组合')
    names = [name for flag, name in ((Qt.KeyboardModifier.ControlModifier,'Control'),
             (Qt.KeyboardModifier.AltModifier,'Alt'),(Qt.KeyboardModifier.ShiftModifier,'Shift')) if modifiers & flag]
    return canonical('+'.join(names + [key]))


class ShortcutRecorder(QPushButton):
    changed = pyqtSignal()
    rejected = pyqtSignal(str)

    def __init__(self, action, slot, parent=None):
        super().__init__(parent)
        self.action, self.value, self.recording = action, '', False
        self.setObjectName('shortcutRecorder')
        self.setAccessibleName(f'{action}，{slot}，点击录入快捷键')
        self.setMinimumWidth(138)
        self.setFixedHeight(34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self.begin)
        self.refresh()

    def refresh(self):
        self.setText('请按快捷键…' if self.recording else display(self.value))
        self.setProperty('recording', self.recording)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_value(self, value):
        self.recording = False
        self.value = value
        self.refresh()

    def begin(self):
        self.recording = True
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.refresh()

    def event(self, event):
        if self.recording and event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)

    def focusOutEvent(self, event):
        self.recording = False
        self.refresh()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if not self.recording:
            return super().keyPressEvent(event)
        event.accept()
        if event.isAutoRepeat():
            return
        if event.key() == Qt.Key.Key_Escape:
            self.recording = False
            self.refresh()
            return
        if event.key() in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return
        if event.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete) and not event.modifiers():
            self.set_value('')
            self.changed.emit()
            return
        try:
            self.set_value(event_key(event))
            self.changed.emit()
        except ValueError as error:
            self.recording = False
            self.refresh()
            self.rejected.emit(str(error))

    def keyReleaseEvent(self, event):
        if self.recording and event.key() == Qt.Key.Key_Shift:
            if self.action == '中英文切换':
                self.set_value('Shift')
                self.changed.emit()
            return
        if not self.recording:
            super().keyReleaseEvent(event)


class HotkeyPage(QWidget):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.fields = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)
        head = QHBoxLayout()
        title = QLabel('快捷键')
        title.setObjectName('h1')
        head.addWidget(title)
        head.addStretch()
        reset = QPushButton('恢复默认')
        reset.setObjectName('ghost')
        reset.clicked.connect(self.reset_defaults)
        head.addWidget(reset)
        layout.addLayout(head)
        hint = QLabel('三套方案共用。点击按键框后录入；点击“应用”保存。Esc 取消录入。')
        hint.setObjectName('desc')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setObjectName('hotkeyMessage')
        self.message.hide()
        layout.addWidget(self.message)
        for group in ('状态切换','方案与翻页'):
            panel = QFrame()
            panel.setObjectName('candidatePanel')
            grid = QGridLayout(panel)
            grid.setContentsMargins(16, 14, 16, 14)
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(9)
            group_title = QLabel(group)
            group_title.setObjectName('sectionTitle')
            grid.addWidget(group_title, 0, 0)
            for column, text in ((1,'主快捷键'),(2,'备用')):
                label = QLabel(text)
                label.setObjectName('hint')
                grid.addWidget(label, 0, column)
            row = 1
            for action, label, defaults, category in ACTIONS:
                if category != group:
                    continue
                name = QLabel(label)
                name.setMinimumWidth(110)
                grid.addWidget(name, row, 0)
                for slot in range(2):
                    field = ShortcutRecorder(label, '主键' if slot == 0 else '备用键')
                    field.changed.connect(self.on_change)
                    field.rejected.connect(self.show_error)
                    clear = QPushButton('清除')
                    clear.setObjectName('shortcutClear')
                    clear.setAccessibleName(f'清除{label}{"主键" if slot == 0 else "备用键"}')
                    clear.setFixedWidth(42)
                    clear.clicked.connect(lambda checked=False, key=action, index=slot: self.clear(key, index))
                    cell = QWidget()
                    line = QHBoxLayout(cell)
                    line.setContentsMargins(0, 0, 0, 0)
                    line.setSpacing(5)
                    line.addWidget(field, 1)
                    line.addWidget(clear)
                    grid.addWidget(cell, row, slot + 1)
                    self.fields[action, slot] = field
                row += 1
            grid.setColumnStretch(1, 1)
            grid.setColumnStretch(2, 1)
            layout.addWidget(panel)
        base = QLabel('数字键选词、空格上屏、Esc 清空与 PgUp / PgDn 保留为基础输入键。\nWin＋空格切换输入法由 Windows 管理。Ctrl＋数字用于候选置顶。')
        base.setWordWrap(True)
        base.setObjectName('hint')
        layout.addWidget(base)
        layout.addStretch()
        self.setStyleSheet('''
            QPushButton#shortcutRecorder { text-align:left; min-height:18px; padding:4px 9px; background:#fff; border:1px solid #d7d7d7; border-radius:4px; }
            QPushButton#shortcutRecorder:hover { border-color:#777; }
            QPushButton#shortcutRecorder:focus, QPushButton#shortcutRecorder[recording="true"] { border:2px solid #252525; padding:3px 8px; background:#f3f3f3; }
            QPushButton#shortcutClear { padding:3px; min-height:28px; color:#666; background:transparent; border:0; }
            QPushButton#shortcutClear:hover { background:#e7e7e7; color:#252525; }
            QLabel#hotkeyMessage { color:#a52626; background:#fff3f3; border:1px solid #e5baba; border-radius:4px; padding:8px 10px; }
        ''')

    def values(self):
        return {action:[self.fields[action, slot].value for slot in range(2)] for action in DEFAULTS}

    def set_values(self, values):
        for action, keys in values.items():
            for slot, value in enumerate(keys):
                self.fields[action, slot].set_value(value)
        self.message.hide()

    def show_error(self, text):
        self.message.setText(text)
        self.message.show()

    def on_change(self):
        try:
            validate(self.values())
            self.message.hide()
        except ValueError as error:
            self.show_error(str(error))
        self.changed.emit()

    def clear(self, action, slot):
        self.fields[action, slot].set_value('')
        self.on_change()

    def reset_defaults(self):
        self.set_values(deepcopy(DEFAULTS))
        self.on_change()
