import ffmpeg
import wave
import sys
import os
import tempfile
import subprocess
import tempfile
import hashlib
import sqlite3
import random
from time import monotonic
from pathlib import Path
from PySide6.QtCore import (
    QUrl, QTimer, Qt
)
from PySide6.QtWidgets import QMessageBox
from PySide6.QtGui import (
    QCursor
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput, QMediaDevices, QAudioFormat

from osuRadio.config import get_ffmpeg_bin_path, DATABASE_FILE
from osuRadio.db import get_audio_path

ffmpeg_path = str(get_ffmpeg_bin_path())
_original_popen = subprocess.Popen

# Patch ffmpeg-python’s internal Popen to suppress terminal (for stream.run())
def silent_popen(cmd, *args, **kwargs):
    if sys.platform.startswith("win"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return _original_popen(cmd, *args, **kwargs)

ffmpeg._run.Popen = silent_popen

# Helper for silent subprocess.run settings
def get_silent_subprocess_kwargs():
    if sys.platform.startswith("win"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {
            "startupinfo": si,
            "creationflags": subprocess.CREATE_NO_WINDOW,
        }
    return {}
    
def silent_global_popen(*args, **kwargs):
    if sys.platform.startswith("win"):
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        kwargs.setdefault("startupinfo", si)
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
    return _original_popen(*args, **kwargs)

subprocess.Popen = silent_global_popen

# Patch ffmpeg.run(...) to use subprocess.run with suppressed terminal
def custom_run(*args, **kwargs):
    cmd = [ffmpeg_path, *args[1:]]
    subprocess_kwargs = {
        "stdout": kwargs.get("stdout", subprocess.PIPE),
        "stderr": kwargs.get("stderr", subprocess.PIPE),
        "text": kwargs.get("text", False),
        "check": kwargs.get("check", True),
        **get_silent_subprocess_kwargs(),
    }
    return subprocess.run(cmd, **subprocess_kwargs)

ffmpeg.run = custom_run

class PitchAdjustedPlayer:
    def __init__(self, audio_output: QAudioOutput, parent=None):
        self.player = QMediaPlayer(parent)
        self.player.setAudioOutput(audio_output)
        self._last_path = None
        self.audio_output = audio_output
        self.current_temp = None
        self.last_temp = None
        self.playback_rate = 1.0
        self.preserve_pitch = True

        self.last_start_ms = 0
        self.was_playing_before_seek = False
        self._pending_play = False

        self.player.mediaStatusChanged.connect(self._start_after_load)

    def _get_wav_duration_ms(self, path):
        try:
            if path.endswith(".wav"):
                with wave.open(path, 'rb') as wf:
                    frames = wf.getnframes()
                    rate = wf.getframerate()
                    return int((frames / rate) * 1000)
            else:
                duration = get_audio_duration(path)
                return int(duration * 1000) if duration else 0
        except Exception as e:
            print(f"[Duration Error] Could not get duration for {path}: {e}")
            return 0

    def play(self, input_path: str, speed: float = 1.0, preserve_pitch: bool = True, start_ms: int = 0, force_play=False):
        if (
            self.player.mediaStatus() == QMediaPlayer.LoadedMedia
            and self._last_path == input_path
            and self.playback_rate == speed
            and self.preserve_pitch == preserve_pitch
        ):
            print(f"[Resume] Resuming existing playback at {start_ms} ms")
            if start_ms > 0:
                self.player.setPosition(start_ms)
            self.player.play()
            return

        self._last_path = input_path
        self.preserve_pitch = preserve_pitch
        self.playback_rate = speed
        self.last_start_ms = start_ms
        self.was_playing_before_seek = self.player.playbackState() == QMediaPlayer.PlayingState or force_play

        if self.last_temp and self.last_temp.exists() and self.last_temp != self.current_temp:
            try:
                os.remove(self.last_temp)
                print(f"[Cleanup] Deleted old cache: {self.last_temp}")
            except Exception as e:
                print(f"[Cleanup Error] Could not delete {self.last_temp}: {e}")

        if preserve_pitch:
            processed_file, _ = process_audio(input_path, speed=speed, adjust_pitch=True)
            self.current_temp = Path(processed_file)
            file_url = QUrl.fromLocalFile(str(processed_file))
            self.last_duration = self._get_wav_duration_ms(str(processed_file))
            self.player.setSource(file_url)
            self.player.setPlaybackRate(1.0)  # Always 1.0 when using FFmpeg
            self._pending_play = True
        else:
            file_url = QUrl.fromLocalFile(str(input_path))
            original_duration = self._get_wav_duration_ms(str(input_path))
            self.last_duration = int(original_duration / speed)
            self.player.setSource(file_url)
            self.player.setPlaybackRate(speed)
            self.player.setPosition(start_ms)
            self.player.play()
            self.current_temp = None
            self._pending_play = False

        self.last_temp = self.current_temp
    
    def _delayed_start(self):
        if self.was_playing_before_seek:
            self.player.play()
        else:
            self.player.pause()
        self._pending_play = False

    def _start_after_load(self, status):
        if status == QMediaPlayer.LoadedMedia and self._pending_play:
            print("[PitchPlayer] Media loaded, setting position")
            self.player.setPosition(self.last_start_ms)
            QTimer.singleShot(150, self._check_audio_after_load)

    def _check_audio_after_load(self):
        if self.was_playing_before_seek:
            self.player.play()
        else:
            self.player.pause()

        # Delay again to verify audio routing
        QTimer.singleShot(500, self._verify_audio_available)

    def _verify_audio_available(self):
        if not self.player.isAvailable():
            print("[PitchPlayer] No audio detected after load — retrying playback")
            self.player.setPosition(self.last_start_ms)
            self.player.play()

    def stop(self):
        self.player.stop()
        if self.current_temp and os.path.exists(self.current_temp):
            if self.current_temp != self.last_temp:
                try:
                    os.remove(self.current_temp)
                    print(f"[Stop] Deleted current temp: {self.current_temp}")
                except Exception as e:
                    print(f"[Stop] Failed to delete {self.current_temp}: {e}")
        self.current_temp = None

def get_audio_duration(file_path):
    try:
        probe = ffmpeg.probe(str(file_path))
        duration = float(probe['format']['duration'])
        return duration
    except Exception as e:
        print(f"Error getting duration: {e}")
        return None
    
def _hash_path(path: Path):
    return hashlib.md5(str(path.resolve()).encode("utf-8")).hexdigest()[:10]
    
def process_audio(input_file, speed=1.0, adjust_pitch=False, cache_dir=None):
    input_path = Path(input_file)
    if cache_dir is None:
        cache_dir = Path(tempfile.gettempdir()) / "OsuRadioCache"
    cache_dir.mkdir(exist_ok=True)

    unique_id = _hash_path(input_path)
    base_name = input_path.stem
    suffix = f"{speed:.2f}x_pitch" if adjust_pitch else f"{speed:.2f}x"
    output_file = cache_dir / f"{base_name}_{unique_id}_{suffix}.wav"

    if output_file.exists():
        return output_file, get_audio_duration(output_file)

    print(f"[FFmpeg] Processing '{input_file}' → '{output_file}' with speed={speed}, pitch_adjust={adjust_pitch}")

    stream = ffmpeg.input(str(input_file))

    if speed == 1.0:
        stream.output(str(output_file), format='wav', acodec="pcm_s16le", ac=2, ar=44100).run(overwrite_output=True, quiet=True)
    else:
        if adjust_pitch:
            remaining = speed
            while remaining < 0.5 or remaining > 2.0:
                factor = 0.5 if remaining < 0.5 else 2.0
                stream = stream.filter('atempo', factor)
                remaining /= factor
            stream = stream.filter('atempo', remaining)
        else:
            stream = stream.filter('rubberband', tempo=speed)

        stream.output(str(output_file), acodec="pcm_s16le", ac=2, ar=44100).run(overwrite_output=True, quiet=True)

    return output_file, get_audio_duration(output_file)

class PlayerMixin:
    def setup_media_players(self):
        output_device = QMediaDevices.defaultAudioOutput()

        audio_format = QAudioFormat()
        audio_format.setSampleRate(44100)
        audio_format.setChannelCount(2)
        audio_format.setSampleFormat(QAudioFormat.Int16)

        if not output_device.isFormatSupported(audio_format):
            print("❌ 44100Hz Int16 not supported — falling back to preferred format.")
            audio_format = output_device.preferredFormat()
        else:
            print("✅ Using 44100Hz Int16")

        print("[Audio Format] Using format:")
        print(f"  Sample Rate: {audio_format.sampleRate()}")
        print(f"  Channels:    {audio_format.channelCount()}")
        print(f"  Sample Type: {audio_format.sampleFormat()}")

        # Create QAudioSink and set volume here (not in __init__)
        self.audio_out = QAudioOutput(output_device, self)
        self.audio_out.setVolume(self.vol / 100)

        self.pitch_player = PitchAdjustedPlayer(self.audio_out, self)

    def connect_slider_signals(self):
        # Link slider drag behavior and update preview time.
        self.slider.sliderPressed.connect(lambda: setattr(self, "_user_dragging", True))
        self.slider.sliderReleased.connect(lambda: (setattr(self, "_user_dragging", False), self.seek(self.slider.value())))
        self.slider.valueChanged.connect(lambda v: self._update_elapsed_label(v))

    def update_position(self, pos):
        if not getattr(self, "_user_dragging", False):
            self.slider.setValue(pos)
            self.elapsed_label.setText(self.format_time(pos))

    def update_duration(self, duration):
        self.slider.setRange(0, duration)
        self.total_label.setText(self.format_time(duration))

    def _slider_jump_to_click(self):
        # Get position relative to the slider width
        mouse_pos = self.slider.mapFromGlobal(QCursor.pos()).x()
        ratio = mouse_pos / self.slider.width()
        new_pos = int(ratio * self.audio.duration())
        self.seek(new_pos)

    def _on_playback_state(self, state):
        if state == QMediaPlayer.EndOfMedia:
            self.next_song()

    def _tick_seekbar(self):
        player = self.pitch_player.player
        if (
            player.playbackState() == QMediaPlayer.PlayingState
            and (not player.isAvailable() or not player.isAvailable())
        ):
            print("[Tick] Detected silent playback with pitch adjustment — restarting audio")
            self.seek(self.slider.value())
        if self._playback_start_time is None:
            return
        speed = float(self.speed_combo.currentText().replace("x", ""))
        elapsed_ms = int((monotonic() - self._playback_start_time) * 1000 * speed)
        elapsed_ms = min(elapsed_ms, self.current_duration)
        if not getattr(self, "_user_dragging", False):
            self.slider.setValue(elapsed_ms)
            self.elapsed_label.setText(self.format_time(elapsed_ms))
        if elapsed_ms >= self.current_duration:
            self.playback_timer.stop()
            self.next_song()

    def loop_video(self, status):
        if status == QMediaPlayer.EndOfMedia:
            self.bg_player.setPosition(0)
            self.bg_player.play()

    def play_song(self, song):
        audio_path = get_audio_path(song)
        self.audio.setSource(QUrl.fromLocalFile(str(audio_path)))
        self.audio.play()
        self.now_lbl.setText(f"{song['artist']} - {song['title']}")
       
    def toggle_play(self):
        player = self.pitch_player.player
        state = player.playbackState()

        if state == QMediaPlayer.PlayingState:
            player.pause()
            self.playback_timer.stop()
            self.is_playing = False
        else:
            player.play()
            self.playback_timer.start(1000)
            self.is_playing = True

        self.update_play_pause_icon()
   
    def pause_song(self):
        self.pitch_player.player.pause()
        self.is_playing = False
        self.update_play_pause_icon()

    def play_song_at_index(self, index):
        if index >= len(self.queue):
            return
            
        self.current_index = index
        song = self.queue[index]
        path = get_audio_path(song)

        self.current_duration = song.get("length", 0)
        self._playback_start_time = monotonic()
        self.slider.setRange(0, self.current_duration)
        self.total_label.setText(self.format_time(self.current_duration))
        self.playback_timer.start()
        path = get_audio_path(song)

        # Debug logging
        print(f"▶▶ play_song_at_index: idx={index}, file={path!r}")
        print("    folder exists? ", os.path.isdir(song["folder"]))
        print("    file exists?   ", os.path.isfile(path))

        if not path.exists():
            print("⚠️  File not found, removing from queue:", path)
            
            # Remove the missing song from queue and library
            self.queue.pop(index)
            if song in self.library:
                self.library.remove(song)
            
            try:
                with sqlite3.connect(DATABASE_FILE) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        "DELETE FROM songs WHERE title = ? AND artist = ? AND audio = ? AND folder = ?",
                        (song["title"], song["artist"], song["audio"], song["folder"])
                    )
                    conn.commit()
                    print(f"[Cleanup] Removed missing song from database: {song['title']}")
            except Exception as e:
                print(f"[Cleanup] Failed to remove from database: {e}")
            
            # Update the UI
            self.populate_list(self.queue)
            self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
            
            QMessageBox.warning(
                self, 
                "Missing File Removed", 
                f"The file for '{song['artist']} - {song['title']}' was not found and has been removed from your queue."
            )
            
            self.now_lbl.setText("—")
            self.is_playing = False
            self.update_play_pause_icon()
            self.playback_timer.stop()

            if self.queue:
                if index >= len(self.queue):
                    self.current_index = len(self.queue) - 1
                else:
                    self.current_index = index
            
            return

        speed = float(self.speed_combo.currentText().replace("x", ""))
        self.pitch_player.was_playing_before_seek = True
        self.pitch_player.play(str(path), speed=speed, preserve_pitch=self.preserve_pitch, force_play=True)
        self.current_duration = self.pitch_player.last_duration
        self._playback_start_time = monotonic()
        self.slider.setRange(0, self.current_duration)
        self.total_label.setText(self.format_time(self.current_duration))
        self.elapsed_label.setText("0:00")
        self.slider.setValue(0)
        self.playback_timer.start()

        # Update UI
        self.now_lbl.setText(f"{song.get('title','')} — {song.get('artist','')}")
        self.song_list.setCurrentRow(index)
        self.is_playing = True
        self.update_play_pause_icon()

    def next_song(self):
        if self.loop_mode == 2:  # Loop single
            QTimer.singleShot(0, lambda: self.play_song_at_index(self.current_index))
        else:
            nxt = self.current_index + 1
            if nxt >= len(self.queue):
                if self.loop_mode == 1:  # Loop all
                    nxt = 0
                else:
                    return  # End of queue, do nothing
            self.play_song_at_index(nxt)

    def prev_song(self):
        idx = (self.current_index - 1) % len(self.queue)
        self.play_song_at_index(idx)

    def shuffle(self):
        random.shuffle(self.queue)
        self.populate_list(self.queue)
        self.queue_lbl.setText(f"Queue: {len(self.queue)} songs")
        self.song_list.setCurrentRow(self.current_index)
    
    def _finalize_seek_ui(self, pos):
        self.current_duration = self.pitch_player.last_duration
        self.slider.setRange(0, self.current_duration)
        self.slider.setValue(pos if pos <= self.current_duration else 0)
        self.elapsed_label.setText(self.format_time(pos if pos <= self.current_duration else 0))
        self.total_label.setText(self.format_time(self.current_duration))

    def seek(self, pos):
        if not self.queue or self.current_index >= len(self.queue):
            return
        
        song = self.queue[self.current_index]
        path = get_audio_path(song)
        speed = float(self.speed_combo.currentText().replace("x", ""))
        self._playback_start_time = monotonic() - (pos / 1000 / speed)
        self.pitch_player.play(
            str(path), 
            speed=speed, 
            preserve_pitch=self.preserve_pitch, 
            start_ms=pos, 
            force_play=self.is_playing
        )
        
        QTimer.singleShot(200, lambda: self._finalize_seek_ui(pos))