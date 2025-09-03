import os
from PySide6.QtCore import (
    Qt, Signal, QThread
)
from PySide6.QtWidgets import (
    QApplication, QLabel,
    QMessageBox, QProgressDialog
)
from osuRadio.config import BASE_PATH, CUSTOM_SONGS_PATH
from osuRadio.msg import show_modal
from osuRadio.parser import OsuParser
from osuRadio.db import load_cache, save_cache

class LibraryScanner(QThread):
    done = Signal(list)
    progress_update = Signal(str)

    def __init__(self, folder):
        super().__init__()
        self.folder = folder

    def run(self):
        uniq = {}
        print(f"[LibraryScanner] Starting scan for folder: {self.folder}")
        for root, _, files in os.walk(self.folder):
            if self.isInterruptionRequested():
                print("[LibraryScanner] Interruption requested, stopping scan (outer loop).")
                return
            for fn in files:
                if self.isInterruptionRequested():
                    print("[LibraryScanner] Interruption requested, stopping scan (inner loop).")
                    return
                if fn.lower().endswith(".osu"):
                    full_path = os.path.join(root, fn)
                    try:
                        s = OsuParser.parse(full_path)
                        title = s.get("title", f"Unknown Title - {fn}")
                        artist = s.get("artist", "Unknown Artist")
                        mapper = s.get("mapper", "Unknown Mapper")
                        key = (title, artist, mapper)
                        if key not in uniq:
                            uniq[key] = s
                            msg = f"🎵 Found beatmap: {s['artist']} - {s['title']}"
                            self.progress_update.emit(msg)
                    except Exception as e:
                        print(f"[LibraryScanner] Error parsing {full_path}: {e}")

        if self.isInterruptionRequested():
            print("[LibraryScanner] Interruption requested before saving cache.")
            return

        library = list(uniq.values())
        print(f"[LibraryScanner] Scan complete. Found {len(library)} unique beatmaps.")
        save_cache(self.folder, library)

        if self.isInterruptionRequested():
            print("[LibraryScanner] Interruption requested before emitting 'done' signal.")
            return

        self.done.emit(library)
        print("[LibraryScanner] 'done' signal emitted.")

class LibraryMixin:
    def reload_songs(self):
        self._progress_user_closed = False
        print(f"[reload_songs] Scanning folder: {self.osu_folder}")

        # Stop previous scan if running
        if hasattr(self, "_scanner") and self._scanner.isRunning():
            print("[reload_songs] Interrupting previous scanner...")
            self._scanner.requestInterruption()
            if not self._scanner.wait(5000):
                print("[reload_songs] Forcing scanner termination...")
                self._scanner.terminate()
                self._scanner.wait()

        # Optional: load from cache first
        osu_cache = load_cache(self.osu_folder)
        custom_cache = load_cache(BASE_PATH / "custom_songs")

        combined_cache = (osu_cache or []) + (custom_cache or [])
        if combined_cache:
            print("[reload_songs] ✅ Loaded from cache.")
            self.library = combined_cache
            self.queue = list(combined_cache)
            self.populate_list(self.queue)
            self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")

        # Progress dialog with message label
        self.progress = QProgressDialog("Importing beatmaps...", None, 0, 0, self)
        self.progress.setWindowModality(Qt.ApplicationModal)
        self.progress.setWindowTitle("osu!Radio")
        self.progress.setFixedSize(420, 69)
        self.progress.setCancelButton(None)
        self.progress.setMinimumDuration(0)

        # Add label below progress bar
        self.progress_label = QLabel("Starting scan…")
        self.progress.setLabel(self.progress_label)

        # Confirmation if closed
        def handle_close(ev):
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Question)
            msg.setWindowTitle("Cancel Beatmap Scan?")
            msg.setText("Are you sure you want to cancel scanning for beatmaps?\n\n"
                        "To run it again, click Reload Maps in the top right.")
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            show_modal(msg)
            reply = msg.result()
            if reply == QMessageBox.Yes:
                self._progress_user_closed = True
                if hasattr(self, "_scanner") and self._scanner.isRunning():
                    self._scanner.requestInterruption()
                self.progress.cancel()
                ev.accept()
            else:
                ev.ignore()

        self.progress.closeEvent = handle_close
        self.progress.show()
        QApplication.processEvents()

        # Scanner thread
        self._scanner = LibraryScanner(self.osu_folder)
        self._scanner.progress_update.connect(self.progress_label.setText)
        self._scanner.done.connect(self._on_reload_complete)
        self._scanner.start()
        
    def _on_reload_complete(self, library):
        self.library = library
        self.queue = list(library)
        self.populate_list(self.queue)
        self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")

        print(f"[reload_complete] ✅ Found {len(library)} total songs after rescan.")
        if CUSTOM_SONGS_PATH.exists() and any(CUSTOM_SONGS_PATH.iterdir()):
            print("[startup] 📥 Found files in custom_songs, importing...")
            self.import_custom_audio(CUSTOM_SONGS_PATH)

        if hasattr(self, "progress") and self.progress:
            self.progress.closeEvent = lambda ev: ev.accept()  # disable cancel check
            self.progress.close()
            self.progress = None

        if not getattr(self, "_progress_user_closed", False):
            QMessageBox.information(self, "Import Complete", f"Imported {len(library)} beatmaps.")