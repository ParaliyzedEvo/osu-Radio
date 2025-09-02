from .config import *
from PySide6.QtCore import (
    Qt, QMetaObject
)

def update_media_key_listener(main_window):
    try:
        if hasattr(main_window, 'media_key_listener') and main_window.media_key_listener:
            main_window.media_key_listener.stop()
            main_window.media_key_listener = None
            print("[Media Keys] Stopped existing listener")
    except Exception as e:
        print(f"[Media Keys] Failed to stop listener: {e}")
    
    if main_window.media_keys_enabled:
        try:
            from pynput import keyboard as kb
            
            def on_press(key):
                try:
                    if key == kb.Key.media_next:
                        QMetaObject.invokeMethod(main_window, "next_song", Qt.QueuedConnection)
                    elif key == kb.Key.media_previous:
                        QMetaObject.invokeMethod(main_window, "prev_song", Qt.QueuedConnection)
                    elif key == kb.Key.media_play_pause:
                        QMetaObject.invokeMethod(main_window, "toggle_play", Qt.QueuedConnection)
                except Exception as e:
                    print(f"[Media Keys] Error handling key press: {e}")
            
            main_window.media_key_listener = kb.Listener(on_press=on_press)
            main_window.media_key_listener.start()
            print("[Media Keys] Started pynput listener")
            
        except ImportError:
            print("[Media Keys] pynput not available, media keys disabled")
        except Exception as e:
            print(f"[Media Keys] Failed to start listener: {e}")
    else:
        print("[Media Keys] Media keys disabled in settings")