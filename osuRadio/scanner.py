import os
from pathlib import Path
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QProgressDialog
from osuRadio.config import BASE_PATH, CUSTOM_SONGS_PATH
from osuRadio.msg import show_modal
from osuRadio.parser import OsuParser
from osuRadio.db import (
    load_cache, save_cache, validate_cache, 
    remove_missing_songs
)

class LibraryScanner(QThread):
    done = Signal(list)
    progress_update = Signal(str)

    def __init__(self, folder):
        super().__init__()
        self.folder = folder

    def run(self):
        uniq = {}
        print(f"[LibraryScanner] Starting scan for folder: {self.folder}")
        
        total_files = 0
        for root, _, files in os.walk(self.folder):
            total_files += sum(1 for f in files if f.lower().endswith(".osu"))
        
        self.progress_update.emit(f"🔍 Scanning folder... (found {total_files} .osu files)")
        
        processed = 0
        skipped_no_audio = 0
        
        for root, _, files in os.walk(self.folder):
            if self.isInterruptionRequested():
                print("[LibraryScanner] Interruption requested, stopping scan.")
                return
                
            for fn in files:
                if self.isInterruptionRequested():
                    print("[LibraryScanner] Interruption requested, stopping scan.")
                    return
                    
                if fn.lower().endswith(".osu"):
                    processed += 1
                    full_path = os.path.join(root, fn)
                    try:
                        s = OsuParser.parse(full_path)
                        title = s.get("title", f"Unknown Title - {fn}")
                        artist = s.get("artist", "Unknown Artist")
                        mapper = s.get("mapper", "Unknown Mapper")
                        audio_file = s.get("audio", "")
                        folder = s.get("folder", "")
                        if audio_file and folder:
                            audio_path = Path(folder) / audio_file
                            if not audio_path.exists():
                                print(f"[LibraryScanner] Skipping {title} - audio file not found: {audio_file}")
                                skipped_no_audio += 1
                                continue
                        elif not audio_file:
                            print(f"[LibraryScanner] Skipping {title} - no audio file specified")
                            skipped_no_audio += 1
                            continue
                        
                        key = (title, artist, mapper)
                        if key not in uniq:
                            uniq[key] = s
                            
                        if processed % 10 == 0:
                            msg = f"🎵 Processing: {artist} - {title} ({processed}/{total_files})"
                            self.progress_update.emit(msg)
                            
                    except Exception as e:
                        print(f"[LibraryScanner] Error parsing {full_path}: {e}")

        if self.isInterruptionRequested():
            print("[LibraryScanner] Interruption requested before saving cache.")
            return

        library = list(uniq.values())
        self.progress_update.emit(f"💾 Saving {len(library)} valid beatmaps to cache...")
        if skipped_no_audio > 0:
            print(f"[LibraryScanner] Skipped {skipped_no_audio} beatmaps with missing/no audio files.")
        
        save_cache(self.folder, library)
        
        if self.isInterruptionRequested():
            print("[LibraryScanner] Interruption requested before emitting 'done' signal.")
            return

        self.progress_update.emit(f"✅ Import complete! ({len(library)} beatmaps)")
        self.done.emit(library)
        print("[LibraryScanner] 'done' signal emitted.")

class LibraryMixin:
    def reload_songs(self, force_rescan=False):
        self._progress_user_closed = False

        is_valid, status_msg, missing_songs = validate_cache(self.osu_folder)
        print(f"[reload_songs] Cache validation: {status_msg}")
        
        if not force_rescan and is_valid:
            if missing_songs:
                print(f"[reload_songs] Cache has {len(missing_songs)} missing songs")
                
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Question)
                msg.setWindowTitle("Cache Cleanup Available")
                msg.setText(
                    f"Found {len(missing_songs)} missing songs in cache.\n\n"
                    "What would you like to do?"
                )
                clean_btn = msg.addButton("Clean Up (Quick)", QMessageBox.AcceptRole)
                rescan_btn = msg.addButton("Full Rescan (Thorough)", QMessageBox.ActionRole)
                cancel_btn = msg.addButton("Cancel", QMessageBox.RejectRole)
                show_modal(msg)
                
                clicked = msg.clickedButton()
                
                if clicked == clean_btn:
                    # Just remove missing songs
                    removed = remove_missing_songs(missing_songs)
                    osu_cache = load_cache(self.osu_folder)
                    custom_cache = load_cache(BASE_PATH / "custom_songs")
                    combined_cache = (osu_cache or []) + (custom_cache or [])
                    
                    if combined_cache:
                        self.library = combined_cache
                        self.queue = list(combined_cache)
                        self.populate_list(self.queue)
                        self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
                        
                        QMessageBox.information(
                            self, 
                            "Cleanup Complete",
                            f"Removed {removed} missing song(s) from cache.\n"
                            f"Library now has {len(combined_cache)} songs."
                        )
                        return
                        
                elif clicked == rescan_btn:
                    print("[reload_songs] User requested full rescan")
                else:
                    return
            else:
                print("[reload_songs] Cache is valid, loading from cache")
                osu_cache = load_cache(self.osu_folder)
                custom_cache = load_cache(BASE_PATH / "custom_songs")
                combined_cache = (osu_cache or []) + (custom_cache or [])
                
                if combined_cache:
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Question)
                    msg.setWindowTitle("Cache is Up to Date")
                    msg.setText(
                        f"Your song cache is up to date with {len(combined_cache)} songs.\n\n"
                        "Do you want to rescan anyway?\n"
                    )
                    msg.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
                    show_modal(msg)
                    
                    if msg.result() == QMessageBox.Yes:
                        print("[reload_songs] User requested force rescan despite valid cache")
                    else:
                        self.library = combined_cache
                        self.queue = list(combined_cache)
                        self.populate_list(self.queue)
                        self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
                        return
        
        print(f"[reload_songs] {'Force rescanning' if force_rescan else 'Cache invalid, rescanning'} folder: {self.osu_folder}")
        
        # Stop previous scan if running
        if hasattr(self, "_scanner") and self._scanner.isRunning():
            print("[reload_songs] Interrupting previous scanner...")
            self._scanner.requestInterruption()
            if not self._scanner.wait(5000):
                print("[reload_songs] Forcing scanner termination...")
                self._scanner.terminate()
                self._scanner.wait()

        rescan_reason = "Full rescan requested" if force_rescan else status_msg
        self.progress = QProgressDialog("Importing beatmaps...", None, 0, 0, self)
        self.progress.setWindowModality(Qt.ApplicationModal)
        self.progress.setWindowTitle("osu!Radio - Scanning Maps")
        self.progress.setFixedSize(500, 100)
        self.progress.setCancelButton(None)
        self.progress.setMinimumDuration(0)
        self.progress_label = QLabel(f"📂 {rescan_reason}\nStarting scan…")
        self.progress.setLabel(self.progress_label)

        def handle_close(ev):
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Question)
            msg.setWindowTitle("Cancel Beatmap Scan?")
            msg.setText(
                "Are you sure you want to cancel scanning for beatmaps?\n\n"
                "The scan is in progress and cancelling may leave your library incomplete.\n"
                "To run it again later, click 'Reload Maps' in the top right."
            )
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

        self._scanner = LibraryScanner(self.osu_folder)
        self._scanner.progress_update.connect(self.progress_label.setText)
        self._scanner.done.connect(self._on_reload_complete)
        self._scanner.start()
        
    def _on_reload_complete(self, library):
        valid_library = []
        missing_count = 0
        
        for song in library:
            audio_path = Path(song.get("folder", "")) / song.get("audio", "")
            if audio_path.exists():
                valid_library.append(song)
            else:
                missing_count += 1
                print(f"[reload_complete] WARNING: Song in cache but audio missing: {song.get('title')}")
        
        library = valid_library
        
        if missing_count > 0:
            print(f"[reload_complete] ⚠️ Found {len(library)} beatmaps, but {missing_count} have missing audio files")
        else:
            print(f"[reload_complete] ✅ Found {len(valid_library)} songs from osu! folder.")
        
        CUSTOM_SONGS_PATH = BASE_PATH / "custom_songs"
        if CUSTOM_SONGS_PATH.exists() and any(CUSTOM_SONGS_PATH.iterdir()):
            self.progress_label.setText("📥 Scanning custom songs folder...")
            QApplication.processEvents()
            
            print("[reload_complete] 📥 Scanning custom_songs folder...")
            
            # Check if custom songs are already in cache
            custom_cache = load_cache(CUSTOM_SONGS_PATH)
            
            if not custom_cache or not hasattr(self, '_scanner'):
                print("[reload_complete] Importing custom audio files...")
                self.import_custom_audio(CUSTOM_SONGS_PATH)
                custom_cache = load_cache(CUSTOM_SONGS_PATH)
            else:
                print(f"[reload_complete] Loaded {len(custom_cache)} custom songs from cache")
            
            combined_library = library + (custom_cache or [])
        else:
            combined_library = library
        
        self.library = combined_library
        self.queue = list(combined_library)
        self.populate_list(self.queue)
        self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
        
        print(f"[reload_complete] ✅ Total: {len(combined_library)} songs in library.")

        # Close progress dialog
        if hasattr(self, "progress") and self.progress:
            self.progress.closeEvent = lambda ev: ev.accept()  # disable cancel check
            self.progress.close()
            self.progress = None

        if not getattr(self, "_progress_user_closed", False):
            osu_count = len(library)
            custom_count = len(combined_library) - len(library)
            
            msg_text = (
                f"✅ Successfully imported {len(combined_library)} songs!\n\n"
                f"• osu! beatmaps: {osu_count}\n"
                f"• Custom songs: {custom_count}\n"
            )
            
            if missing_count > 0:
                msg_text += f"\n⚠️ Skipped {missing_count} beatmaps with missing audio files"
            
            msg_text += "\n\nYour library is now up to date."
            
            QMessageBox.information(self, "Import Complete", msg_text)
    
    def check_and_update_cache(self):
        is_valid, status_msg, missing_songs = validate_cache(self.osu_folder)
        
        if is_valid and not missing_songs:
            print(f"[check_and_update_cache] {status_msg}")
            osu_cache = load_cache(self.osu_folder)
            custom_cache = load_cache(BASE_PATH / "custom_songs")
            combined_cache = (osu_cache or []) + (custom_cache or [])
            
            if combined_cache:
                self.library = combined_cache
                self.queue = list(combined_cache)
                self.populate_list(self.queue)
                self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
                print(f"[check_and_update_cache] Loaded {len(combined_cache)} songs from cache")
                return True
        
        elif is_valid and missing_songs:
            print(f"[check_and_update_cache] {status_msg}, cleaning up...")
            
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Information)
            msg.setWindowTitle("Cache Cleanup")
            msg.setText(
                f"Detected {len(missing_songs)} missing song(s) in cache.\n\n"
                "Would you like to:\n"
                "• Clean up: Remove missing songs from cache (quick)\n"
                "• Rescan: Perform a full rescan of your songs folder (thorough)"
            )
            msg.addButton("Clean Up", QMessageBox.AcceptRole)
            msg.addButton("Rescan", QMessageBox.ActionRole)
            msg.addButton("Cancel", QMessageBox.RejectRole)
            show_modal(msg)
            
            choice = msg.result()
            
            if choice == 0:  # Clean up
                removed = remove_missing_songs(missing_songs)
                osu_cache = load_cache(self.osu_folder)
                custom_cache = load_cache(BASE_PATH / "custom_songs")
                combined_cache = (osu_cache or []) + (custom_cache or [])
                
                if combined_cache:
                    self.library = combined_cache
                    self.queue = list(combined_cache)
                    self.populate_list(self.queue)
                    self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
                    print(f"[check_and_update_cache] Cleaned cache: removed {removed}, kept {len(combined_cache)}")
                    return True
            elif choice == 1:  # Rescan
                self.reload_songs(force_rescan=True)
                return True
            else:  # Cancel
                return False
        
        else:
            print(f"[check_and_update_cache] {status_msg}")
            
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Cache Invalid")
            msg.setText(
                f"{status_msg}\n\n"
                "A full rescan is recommended.\n"
                "Would you like to scan your songs folder now?"
            )
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            show_modal(msg)
            
            if msg.result() == QMessageBox.Yes:
                self.reload_songs(force_rescan=True)
                return True
            else:
                return False
        
        return False