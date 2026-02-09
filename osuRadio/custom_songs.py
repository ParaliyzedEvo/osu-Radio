import re
import subprocess
import sys
import os
import json
import zipfile
import sqlite3
import py7zr
from pathlib import Path

from PySide6.QtCore import QTimer, Signal, QThread, Qt
from PySide6.QtWidgets import (
    QLabel, QButtonGroup, QRadioButton, QVBoxLayout, QProgressBar, QLineEdit,
    QDialog, QDialogButtonBox, QMessageBox, QCheckBox, QScrollArea, QWidget,
    QFileDialog, QApplication, QHBoxLayout
)

from osuRadio.audio import get_audio_duration
from osuRadio.db import save_cache
from osuRadio.msg import show_modal
from osuRadio.config import (
    CUSTOM_SONGS_PATH, DATABASE_FILE, IS_WINDOWS, get_yt_dlp_path,
    BASE_PATH, EXPORT_STATE_FILE
)


class ExportWorker(QThread):
    progress_updated = Signal(int, str)  # (current_count, current_file)
    export_finished = Signal(bool, str)  # (success, message)

    def __init__(self, selected_songs, output_path, archive_format):
        super().__init__()
        self.selected_songs = selected_songs
        self.output_path = output_path
        self.archive_format = archive_format

    def run(self):
        try:
            total = len(self.selected_songs)
            
            if self.archive_format == "zip":
                with zipfile.ZipFile(self.output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                    for i, song in enumerate(self.selected_songs, 1):
                        audio_path = Path(song["folder"]) / song["audio"]
                        if audio_path.exists():
                            arcname = f"{song['artist']} - {song['title']}{audio_path.suffix}"
                            self.progress_updated.emit(i, arcname)
                            zipf.write(audio_path, arcname=arcname)
                        else:
                            print(f"[Export] Missing: {audio_path}")
                            
            else:  # 7z
                with py7zr.SevenZipFile(self.output_path, "w") as archive:
                    for i, song in enumerate(self.selected_songs, 1):
                        audio_path = Path(song["folder"]) / song["audio"]
                        if audio_path.exists():
                            arcname = f"{song['artist']} - {song['title']}{audio_path.suffix}"
                            self.progress_updated.emit(i, arcname)
                            archive.write(audio_path, arcname)
                        else:
                            print(f"[Export] Missing: {audio_path}")
            
            self.export_finished.emit(True, f"Exported {total} songs successfully!")
            
        except Exception as e:
            self.export_finished.emit(False, f"Export failed: {str(e)}")


class CustomSongsMixin:
    def add_custom_songs(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Custom Songs")
        msg.setText("Would you like to import or export custom songs?")
        import_btn = msg.addButton("Import", QMessageBox.AcceptRole)
        export_btn = msg.addButton("Export", QMessageBox.ActionRole)
        msg.addButton(QMessageBox.Cancel)
        show_modal(msg)

        if msg.clickedButton() == import_btn:
            self.import_custom_songs_flow()
        elif msg.clickedButton() == export_btn:
            self.export_songs_dialog()

    def import_custom_audio(self, folder: Path):
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS songs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    artist TEXT,
                    mapper TEXT,
                    audio TEXT,
                    background TEXT,
                    length INTEGER,
                    osu_file TEXT,
                    folder TEXT
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.commit()

        print(f"[Custom Audio] Importing from: {folder}")
        supported_exts = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".opus"}
        maps = []

        # existing rows for this folder
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT title, artist, audio FROM songs WHERE folder = ?", (str(folder),))
            existing = set((r[0], r[1], r[2]) for r in cursor.fetchall())

        for file in folder.glob("*"):
            if file.suffix.lower() in supported_exts:
                try:
                    title = file.stem
                    artist = "Custom"
                    audio = file.name

                    if (title, artist, audio) in existing:
                        print(f"[Custom Audio] Skipping duplicate: {title}")
                        continue

                    duration = get_audio_duration(file) or 0
                    maps.append({
                        "title": title,
                        "artist": artist,
                        "mapper": "User",
                        "audio": audio,
                        "background": "",
                        "length": int(duration * 1000),
                        "osu_file": "",
                        "folder": str(folder)
                    })
                    print(f"[Custom Audio] Found: {title} ({audio})")
                except Exception as e:
                    print(f"[Custom Audio] Failed to import {file}: {e}")

        if maps:
            save_cache(str(folder), maps)
            try:
                mtime = str(os.path.getmtime(self.osu_folder))
                with sqlite3.connect(DATABASE_FILE) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                        ("folder_mtime", mtime)
                    )
                    conn.commit()
            except Exception as e:
                print(f"[Custom Audio] Failed to update folder_mtime: {e}")

            self.library.extend(maps)
            self.queue.extend(maps)
            self.populate_list(self.queue)
            self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
            QMessageBox.information(self, "Import Complete", f"Imported {len(maps)} custom songs.")
        else:
            QMessageBox.warning(self, "No Songs Found", "No supported audio files found.")

        if self.current_index >= len(self.queue):
            self.current_index = 0

    def import_custom_songs_flow(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Import Custom Songs")
        msg.setText("How would you like to import songs?")
        manual_btn = msg.addButton("Manual (Open Folder)", QMessageBox.ButtonRole.AcceptRole)
        youtube_btn = msg.addButton("Download from YouTube", QMessageBox.ButtonRole.ActionRole)
        msg.addButton(QMessageBox.StandardButton.Cancel)
        show_modal(msg)

        if msg.clickedButton() == manual_btn:
            self.manual_import_flow(CUSTOM_SONGS_PATH)
        elif msg.clickedButton() == youtube_btn:
            self.youtube_import_flow(CUSTOM_SONGS_PATH)

    def manual_import_flow(self, CUSTOM_SONGS_PATH):
        if IS_WINDOWS:
            os.startfile(str(CUSTOM_SONGS_PATH))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(CUSTOM_SONGS_PATH)])
        elif sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", str(CUSTOM_SONGS_PATH)])

        msg = QMessageBox(self)
        msg.setWindowTitle("Import Custom Songs")
        msg.setText("Do you want to import songs from the custom_songs folder now?")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        show_modal(msg)

        if msg.result() == QMessageBox.StandardButton.Yes:
            self.import_custom_audio(CUSTOM_SONGS_PATH)

    def youtube_import_flow(self, CUSTOM_SONGS_PATH):
        class DownloadWorker(QThread):
            progress_updated = Signal(int)
            status_updated = Signal(str)
            download_finished = Signal(bool, str)

            def __init__(self, url, audio_format, CUSTOM_SONGS_PATH):
                super().__init__()
                self.url = url
                self.audio_format = audio_format
                self.CUSTOM_SONGS_PATH = CUSTOM_SONGS_PATH

            def run(self):
                try:
                    print(f"[YouTube Download] Starting download: {self.url}")
                    print(f"[YouTube Download] Format: {self.audio_format}")
                    print(f"[YouTube Download] Output folder: {self.CUSTOM_SONGS_PATH}")

                    ytdlp_path = str(get_yt_dlp_path())
                    output_template = str(self.CUSTOM_SONGS_PATH / "%(title)s.%(ext)s")
                    cmd = [
                        str(ytdlp_path),
                        "-x",
                        "--audio-format", self.audio_format,
                        "--audio-quality", "0",
                        "--newline",
                        "-o", output_template,
                        self.url
                    ]

                    print(f"[YouTube Download] Command: {' '.join(cmd)}")

                    process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        universal_newlines=True,
                        creationflags=subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
                    )

                    while True:
                        line = process.stdout.readline()
                        if not line and process.poll() is not None:
                            break

                        if line:
                            line = line.strip()
                            print(f"[yt-dlp] {line}")

                            if '[download]' in line and '%' in line:
                                match = re.search(r'\[download\]\s+(\d+(?:\.\d+)?)%', line)
                                if match:
                                    percent = int(float(match.group(1)))
                                    self.progress_updated.emit(percent)
                                    self.status_updated.emit(f"Downloading... {percent}%")

                            elif '[ffmpeg]' in line or 'post-process' in line.lower():
                                self.status_updated.emit("Processing audio...")

                    return_code = process.wait()
                    if return_code == 0:
                        self.download_finished.emit(True, "")
                    else:
                        self.download_finished.emit(False, "Download failed - check console for details")

                except Exception as e:
                    print(f"[YouTube Download] Exception: {e}")
                    self.download_finished.emit(False, str(e))

        dialog = QDialog(self)
        dialog.setWindowTitle("Download from YouTube")
        dialog.setFixedSize(400, 220)
        layout = QVBoxLayout()

        url_label = QLabel("YouTube URL:")
        layout.addWidget(url_label)

        url_input = QLineEdit()
        url_input.setPlaceholderText("https://www.youtube.com/watch?v=...")
        layout.addWidget(url_input)

        format_label = QLabel("Audio Format:")
        layout.addWidget(format_label)

        format_group = QButtonGroup()
        wav_radio = QRadioButton("WAV (High quality)")
        mp3_radio = QRadioButton("MP3 (Good quality)")
        mp3_radio.setChecked(True)

        format_group.addButton(wav_radio)
        format_group.addButton(mp3_radio)

        layout.addWidget(wav_radio)
        layout.addWidget(mp3_radio)

        progress_bar = QProgressBar()
        progress_bar.setVisible(False)
        layout.addWidget(progress_bar)

        status_label = QLabel("")
        layout.addWidget(status_label)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(button_box)

        dialog.setLayout(layout)
        worker = None

        def download_song():
            nonlocal worker
            url = url_input.text().strip()
            if not url:
                QMessageBox.warning(dialog, "Invalid URL", "Please enter a YouTube URL.")
                return

            audio_format = "wav" if wav_radio.isChecked() else "mp3"

            progress_bar.setVisible(True)
            progress_bar.setRange(0, 100)
            progress_bar.setValue(0)
            status_label.setText("Starting download...")
            button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
            url_input.setEnabled(False)
            wav_radio.setEnabled(False)
            mp3_radio.setEnabled(False)

            worker = DownloadWorker(url, audio_format, CUSTOM_SONGS_PATH)

            def on_progress(percent): progress_bar.setValue(percent)
            def on_status(status):
                status_label.setText(status)
                if "Processing" in status:
                    progress_bar.setRange(0, 0)

            def on_finished(success, error_msg):
                if success:
                    status_label.setText("Download completed successfully!")
                    progress_bar.setVisible(False)
                    button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
                    url_input.setEnabled(True)
                    wav_radio.setEnabled(True)
                    mp3_radio.setEnabled(True)
                    dialog.accept()

                    def show_import(): self.import_after_download(CUSTOM_SONGS_PATH)
                    QTimer.singleShot(100, show_import)
                else:
                    status_label.setText("Download failed!")
                    QMessageBox.critical(dialog, "Download Failed", f"Error: {error_msg}")
                    self.reset_download_dialog(button_box, url_input, wav_radio, mp3_radio, progress_bar, status_label)

            worker.progress_updated.connect(on_progress)
            worker.status_updated.connect(on_status)
            worker.download_finished.connect(on_finished)
            worker.start()

        button_box.accepted.connect(download_song)
        button_box.rejected.connect(dialog.reject)
        dialog.exec()

    def reset_download_dialog(self, button_box, url_input, wav_radio, mp3_radio, progress_bar, status_label):
        progress_bar.setVisible(False)
        status_label.setText("")
        button_box.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        url_input.setEnabled(True)
        wav_radio.setEnabled(True)
        mp3_radio.setEnabled(True)

    def import_after_download(self, CUSTOM_SONGS_PATH):
        msg = QMessageBox(self)
        msg.setWindowTitle("Import Downloaded Songs")
        msg.setText("Download completed! Do you want to import the downloaded songs now?")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        show_modal(msg)
        if msg.result() == QMessageBox.StandardButton.Yes:
            self.import_custom_audio(CUSTOM_SONGS_PATH)

    def export_songs_dialog(self):
        # Show format selection dialog
        format_dialog = QDialog(self)
        format_dialog.setWindowTitle("Export Format")
        format_dialog.setFixedSize(300, 150)
        format_layout = QVBoxLayout(format_dialog)

        format_label = QLabel("Choose export format:")
        format_layout.addWidget(format_label)

        # Radio buttons for format selection
        zip_radio = QRadioButton("ZIP Archive (default)")
        zip_radio.setChecked(True)
        z_radio = QRadioButton("7z Archive (better compression)")

        format_layout.addWidget(zip_radio)
        format_layout.addWidget(z_radio)

        format_button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        format_layout.addWidget(format_button_box)

        format_button_box.accepted.connect(format_dialog.accept)
        format_button_box.rejected.connect(format_dialog.reject)

        if format_dialog.exec() != QDialog.Accepted:
            return

        # Determine selected format
        selected_format = "zip" if zip_radio.isChecked() else "7z"

        # Load previously selected songs
        previously_selected = set()
        try:
            if Path(EXPORT_STATE_FILE).exists():
                with open(EXPORT_STATE_FILE, "r", encoding="utf-8") as f:
                    previously_selected = set(json.load(f))
        except Exception as e:
            print(f"[Export] Failed to load previous selection: {e}")

        # Get songs from database
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT title, artist, audio, folder FROM songs")
            rows = cursor.fetchall()
            songs = []
            seen_paths = set()
            
            for r in rows:
                title, artist, audio, folder = r[0], r[1], r[2], r[3]
                audio_path = Path(folder) / audio
                
                # Skip if file doesn't exist
                if not audio_path.exists():
                    continue
                
                # Skip if we've already added this exact file path
                audio_path_str = str(audio_path.resolve())
                if audio_path_str in seen_paths:
                    continue
                    
                seen_paths.add(audio_path_str)
                songs.append({
                    "title": title,
                    "artist": artist,
                    "audio": audio,
                    "folder": folder,
                    "full_path": audio_path_str  # Store for uniqueness
                })

        if not songs:
            QMessageBox.information(self, "No Songs", "No songs found in the database.")
            return

        # Song selection dialog
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Export Songs as {selected_format.upper()}")
        dialog.setFixedSize(600, 400)
        layout = QVBoxLayout(dialog)

        search_bar = QLineEdit()
        search_bar.setPlaceholderText("Search songs…")
        layout.addWidget(search_bar)

        count_label = QLabel("0 / 0 selected")
        layout.addWidget(count_label)

        # Checkbox for bulk operations
        checkbox_row = QHBoxLayout()
        select_all_cb = QCheckBox("Select All")
        checkbox_row.addWidget(select_all_cb)
        checkbox_row.addStretch()
        layout.addLayout(checkbox_row)

        label = QLabel(f"Select songs to export as {selected_format.upper()}:")
        layout.addWidget(label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        song_checks = []
        for song in songs:
            checkbox = QCheckBox(f"{song['artist']} - {song['title']}")
            checkbox.song_data = song
            unique_key = song.get("full_path", f"{song['folder']}/{song['audio']}")
            checkbox.song_key = unique_key
            if unique_key in previously_selected:
                checkbox.setChecked(True)
            song_checks.append(checkbox)
            scroll_layout.addWidget(checkbox)

        scroll_content.setLayout(scroll_layout)
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(button_box)

        def update_count_label():
            visible_checks = [cb for cb in song_checks if cb.isVisible()]
            checked = sum(1 for cb in visible_checks if cb.isChecked())
            total = len(visible_checks)
            count_label.setText(f"{checked} / {total} selected")

        select_all_previous_state = [Qt.Unchecked]

        def handle_select_all(state):
            QApplication.setOverrideCursor(Qt.WaitCursor)
            select_all_cb.blockSignals(True)

            # Determine target based on what we're transitioning from
            if select_all_previous_state[0] == Qt.Checked:
                target_state = False
            else:
                target_state = True
            
            for i, cb in enumerate(song_checks):
                cb.blockSignals(True)
                cb.setChecked(target_state)
                cb.blockSignals(False)
                if i % 100 == 0:
                    QApplication.processEvents()
            
            select_all_cb.blockSignals(False)
            QApplication.restoreOverrideCursor()
            update_count_label()
            update_bulk_checkbox_state()
            select_all_previous_state[0] = select_all_cb.checkState()

        def update_bulk_checkbox_state():
            all_checks = song_checks
            all_checked = sum(1 for cb in song_checks if cb.isChecked())
            select_all_cb.blockSignals(True)
            
            if all_checked == 0:
                select_all_cb.setCheckState(Qt.Unchecked)
            elif all_checked == len(all_checks):
                select_all_cb.setCheckState(Qt.Checked)
            else:
                select_all_cb.setCheckState(Qt.PartiallyChecked)
            
            # Update the tracked state whenever the state changes
            select_all_previous_state[0] = select_all_cb.checkState()
            select_all_cb.blockSignals(False)

        def filter_checkboxes(text: str):
            lower = text.lower()
            for cb in song_checks:
                song = cb.song_data
                visible = lower in song["title"].lower() or lower in song["artist"].lower()
                cb.setVisible(visible)
            update_count_label()
            update_bulk_checkbox_state()

        select_all_cb.setTristate(True)

        for cb in song_checks:
            cb.toggled.connect(lambda: (update_count_label(), update_bulk_checkbox_state()))
        
        select_all_cb.stateChanged.connect(handle_select_all)
        search_bar.textChanged.connect(filter_checkboxes)

        QTimer.singleShot(0, lambda: (update_count_label(), update_bulk_checkbox_state()))

        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        if dialog.exec() != QDialog.Accepted:
            return

        selected_songs = [c.song_data for c in song_checks if c.isChecked()]
        if not selected_songs:
            QMessageBox.warning(self, "No Selection", "No songs selected for export.")
            return

        try:
            selected_keys = [c.song_key for c in song_checks if c.isChecked()]
            with open(EXPORT_STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(selected_keys, f, indent=2)
        except Exception as e:
            print(f"[Export] Failed to save export selection: {e}")

        # File save dialog with appropriate extension
        file_extension = "zip" if selected_format == "zip" else "7z"
        filter_text = f"{selected_format.upper()} Files (*.{file_extension})"
        default_filename = f"custom_songs_export.{file_extension}"

        path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export Songs As {selected_format.upper()}",
            str(BASE_PATH / default_filename),
            filter_text
        )
        if not path:
            return

        # Create progress dialog
        progress_dialog = QDialog(self)
        progress_dialog.setWindowTitle("Exporting Songs")
        progress_dialog.setFixedSize(500, 150)
        progress_dialog.setWindowModality(Qt.ApplicationModal)
        progress_layout = QVBoxLayout(progress_dialog)
        progress_label = QLabel(f"Creating {selected_format.upper()} archive...")
        progress_layout.addWidget(progress_label)
        progress_bar = QProgressBar()
        progress_bar.setRange(0, len(selected_songs))
        progress_bar.setValue(0)
        progress_layout.addWidget(progress_bar)
        current_file_label = QLabel("")
        current_file_label.setWordWrap(True)
        progress_layout.addWidget(current_file_label)
        progress_dialog.show()
        QApplication.processEvents()

        # Create worker thread for export
        worker = ExportWorker(selected_songs, path, selected_format)
        
        def on_progress(count, filename):
            progress_bar.setValue(count)
            current_file_label.setText(f"Adding: {filename}")
            QApplication.processEvents()
        
        def on_finished(success, message):
            progress_dialog.close()
            if success:
                QMessageBox.information(self, "Export Complete", 
                    f"{message}\nSaved to:\n{path}")
            else:
                QMessageBox.critical(self, "Export Failed", message)
        
        worker.progress_updated.connect(on_progress)
        worker.export_finished.connect(on_finished)
        worker.start()
        
        # Keep dialog open until worker finishes
        while worker.isRunning():
            QApplication.processEvents()
            worker.wait(50)