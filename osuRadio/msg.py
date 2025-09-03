from PySide6.QtCore import (
    Qt
)
from PySide6.QtWidgets import (
    QMessageBox
)

def show_modal(msgbox: QMessageBox):
    msgbox.setWindowModality(Qt.ApplicationModal)
    msgbox.raise_()
    msgbox.activateWindow()
    msgbox.exec()