from .config import *

def update_media_key_listener(self):
        try:
            if self.media_key_listener:
                self.media_key_listener.stop()
                self.media_key_listener = None
        except Exception as e:
            print("Failed to stop media key listener:", e)