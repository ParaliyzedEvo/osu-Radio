import ffmpeg
import wave
import sys
import os
import tempfile
import subprocess
import tempfile
import hashlib
from pathlib import Path
from PySide6.QtCore import (
    QUrl, QTimer
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from .config import *

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
            print(f"[Resume] Resuming existing playback at {self.player.position()} ms")
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
            self.player.setSource(file_url)
            self._pending_play = True  # This triggers _start_after_load
        else:
            file_url = QUrl.fromLocalFile(str(input_path))
            self.player.setSource(file_url)
            self.player.setPlaybackRate(speed)
            self.player.setPosition(start_ms)
            self.player.play()
            print(f"[QMediaPlayer] 🎵 Now playing: {file_url.toString()}")
            self.current_temp = None
            self._pending_play = False

        self.last_temp = self.current_temp
        self.last_duration = self._get_wav_duration_ms(file_url.toLocalFile())
    
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