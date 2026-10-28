"""Lightweight installed settings entry, independent of the installer payload."""
import hashlib
from pathlib import Path
import sys
import tempfile


def main():
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    from PyQt6.QtCore import QLockFile
    from PyQt6.QtWidgets import QApplication
    from ui_theme import apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName('QingshiSettings')
    name = 'QingshiSettings-' + hashlib.sha256(str(Path.home()).encode()).hexdigest()[:16]
    lock = QLockFile(str(Path(tempfile.gettempdir()) / (name + '.lock')))
    lock.setStaleLockTime(0)
    server = QLocalServer(app)
    # Windows named pipes allow multiple listening server instances with the
    # same name. A per-user lock is required in addition to QLocalServer.
    if not lock.tryLock(0):
        socket = QLocalSocket()
        socket.connectToServer(name)
        if socket.waitForConnected(1000):
            socket.write(b'show')
            socket.waitForBytesWritten(500)
            return 0
        return 1
    if not server.listen(name):
        return 1

    apply_theme(app)
    from wubi_settings import MainWindow
    window = MainWindow()

    def show_existing():
        while server.hasPendingConnections():
            connection = server.nextPendingConnection()
            connection.disconnected.connect(connection.deleteLater)
            connection.disconnectFromServer()
        if window.isMinimized():
            window.showNormal()
        window.show()
        window.raise_()
        window.activateWindow()

    server.newConnection.connect(show_existing)
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
