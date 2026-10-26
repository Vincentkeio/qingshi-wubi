"""以浮起与压下表达状态的桌面导航。"""
from PyQt6.QtCore import Qt, QRectF, QEvent, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen, QPainterPath
from PyQt6.QtWidgets import QWidget, QPushButton, QVBoxLayout, QGraphicsDropShadowEffect


class NavigationButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setFixedHeight(46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.keyboard_focus = False
        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(8)
        self.shadow.setOffset(0, 2)
        self.shadow.setColor(QColor(0, 0, 0, 22))
        self.setGraphicsEffect(self.shadow)
        self.toggled.connect(self._state)

    def _state(self, selected):
        self.shadow.setEnabled(not selected)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        down = self.isChecked() or self.isDown()
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e3e3e3" if down else "#ffffff" if self.underMouse() else "#f6f6f6"))
        painter.drawRoundedRect(rect, 6, 6)
        if down:
            path = QPainterPath()
            path.addRoundedRect(rect, 6, 6)
            painter.setClipPath(path)
            for i, alpha in enumerate((15, 8, 3)):
                painter.setPen(QPen(QColor(0, 0, 0, alpha), 1))
                painter.drawLine(6, 2 + i, self.width() - 6, 2 + i)
            painter.setClipping(False)
        if self.hasFocus() and self.keyboard_focus:
            painter.setPen(QPen(QColor("#555555"), 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 4, 4)
        font = self.font()
        font.setPixelSize(13)
        font.setBold(down)
        painter.setFont(font)
        painter.setPen(QColor("#171717" if down else "#555555"))
        painter.drawText(self.rect().adjusted(18, int(down), -12, 0), Qt.AlignmentFlag.AlignVCenter, self.text())

    def focusInEvent(self, event):
        self.keyboard_focus = event.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason, Qt.FocusReason.ShortcutFocusReason)
        super().focusInEvent(event)

    def mousePressEvent(self, event):
        self.keyboard_focus = False
        super().mousePressEvent(event)


class Navigation(QWidget):
    currentRowChanged = pyqtSignal(int)

    def __init__(self, labels, parent=None):
        super().__init__(parent)
        self.buttons = []
        self._row = -1
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 6, 4, 8)
        layout.setSpacing(10)
        for index, label in enumerate(labels):
            button = NavigationButton(label)
            button.clicked.connect(lambda checked, i=index: self.setCurrentRow(i))
            button.installEventFilter(self)
            self.buttons.append(button)
            layout.addWidget(button)
        layout.addStretch(1)

    def currentRow(self):
        return self._row

    def setCurrentRow(self, index):
        if not 0 <= index < len(self.buttons):
            return
        changed = self._row != index
        self._row = index
        for i, button in enumerate(self.buttons):
            button.setChecked(i == index)
        if changed:
            self.currentRowChanged.emit(index)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Home, Qt.Key.Key_End):
            target = (self._row + (1 if event.key() == Qt.Key.Key_Down else -1)) % len(self.buttons)
            if event.key() == Qt.Key.Key_Home:
                target = 0
            elif event.key() == Qt.Key.Key_End:
                target = len(self.buttons) - 1
            self.setCurrentRow(target)
            self.buttons[target].setFocus(Qt.FocusReason.TabFocusReason)
            return True
        return super().eventFilter(watched, event)
