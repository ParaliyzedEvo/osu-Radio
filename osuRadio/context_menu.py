from PySide6.QtCore import (
    Qt
)
from PySide6.QtWidgets import (
    QMenu
)

class ContextMenuMixin:
    def onSongContextMenu(self, point):
        item = self.song_list.itemAt(point)
        if not item:
            return
        menu = QMenu(self)
        action = menu.addAction("Add to Next ▶")
        action.triggered.connect(lambda: self.addToNext(item))
        menu.exec(self.song_list.mapToGlobal(point))

    def addToNext(self, item):
        song = item.data(Qt.UserRole)

        if song in self.queue:
            self.queue.remove(song)

        insert_index = self.current_index + 1
        self.queue.insert(insert_index, song)

        self.populate_list(self.queue)
        self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")