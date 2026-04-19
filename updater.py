import time, shutil, os, sys, psutil, uuid, threading
import tkinter as tk
from tkinter import ttk

PRESERVE_FILES = {"songs.db", "settings.json"}
PRESERVE_DIRS = {"custom_songs", "logs"}

log_path = "updater_log.txt"
log = open(log_path, "w", encoding="utf-8")

def log_print(msg):
    print(msg)
    log.write(msg + "\n")
    log.flush()

# Progress UI
class UpdaterUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("osu!Radio Updater")
        self.root.geometry("480x160")
        self.root.resizable(False, False)
        self.root.configure(bg="#1a1a2e")
        # Centre on screen
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth()  - 480) // 2
        y = (self.root.winfo_screenheight() - 160) // 2
        self.root.geometry(f"480x160+{x}+{y}")
        # Prevent closing mid-update
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)

        tk.Label(
            self.root, text="osu!Radio  —  Updating",
            bg="#1a1a2e", fg="#a1c9ff",
            font=("Segoe UI", 13, "bold")
        ).pack(pady=(18, 4))

        self._status_var = tk.StringVar(value="Preparing…")
        tk.Label(
            self.root, textvariable=self._status_var,
            bg="#1a1a2e", fg="#cccccc",
            font=("Segoe UI", 9)
        ).pack(pady=(0, 8))

        style = ttk.Style(self.root)
        style.theme_use("default")
        style.configure(
            "osu.Horizontal.TProgressbar",
            troughcolor="#2a2a4a",
            background="#a1c9ff",
            bordercolor="#1a1a2e",
            lightcolor="#a1c9ff",
            darkcolor="#a1c9ff",
        )
        self._bar = ttk.Progressbar(
            self.root, style="osu.Horizontal.TProgressbar",
            orient="horizontal", length=420, mode="indeterminate"
        )
        self._bar.pack(pady=(0, 14))
        self._bar.start(12)

    def set_status(self, msg: str):
        self.root.after(0, self._status_var.set, msg)

    def finish(self):
        def _done():
            self._bar.stop()
            self._bar.configure(mode="determinate")
            self._bar["value"] = 100
            self._status_var.set("✅ Update complete! Relaunching…")
            self.root.after(1800, self.root.destroy)
        self.root.after(0, _done)

    def pump(self):
        try:
            self.root.update()
        except tk.TclError:
            pass

ui = UpdaterUI()

# Helpers
def safe_copy_file(src, dst, max_retries=3):
    for attempt in range(max_retries):
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if not wait_for_unlock(src, timeout=10):
                log_print(f"⚠️ Source file locked: {src}")
                continue
            if attempt == 0:
                shutil.copy2(src, dst)
            elif attempt == 1:
                shutil.copy(src, dst)
            else:
                with open(src, 'rb') as sf, open(dst, 'wb') as df:
                    shutil.copyfileobj(sf, df)
            if os.path.exists(dst) and os.path.getsize(dst) > 0:
                log_print(f"✅ Copied: {os.path.basename(src)} (attempt {attempt+1})")
                return True
            log_print(f"⚠️ Copy verification failed: {src}")
        except PermissionError as e:
            log_print(f"⚠️ Permission denied: {src}: {e}")
            if attempt < max_retries - 1: time.sleep(2)
        except OSError as e:
            log_print(f"⚠️ OS error: {src}: {e}")
            if attempt < max_retries - 1: time.sleep(1)
        except Exception as e:
            log_print(f"⚠️ Unexpected error: {src}: {e}")
            if attempt < max_retries - 1: time.sleep(1)
    log_print(f"❌ Failed after {max_retries} attempts: {src}")
    return False

def wait_for_unlock(target_path, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with open(target_path, 'ab'):
                pass
            return True
        except (PermissionError, OSError) as e:
            log_print(f"Waiting for unlock: {os.path.basename(target_path)} - {e}")
            time.sleep(0.5)
    log_print(f"❌ Timed out waiting for: {target_path}")
    return False

def should_preserve_path(path, base_dir):
    rel = os.path.relpath(path, base_dir)
    for part in rel.split(os.sep):
        if part in PRESERVE_DIRS:
            return True
    return os.path.basename(path) in PRESERVE_FILES

# Args
if len(sys.argv) < 5:
    log_print("❌ Not enough arguments. Expected: src_dir dst_dir exe_name pid")
    sys.exit(1)

src_dir      = sys.argv[1]
dst_dir      = sys.argv[2]
exe_name     = sys.argv[3]
pid_to_wait  = int(sys.argv[4])

# Wait for app to exit
ui.set_status(f"Waiting for osu!Radio to close (PID {pid_to_wait})…")
log_print(f"Waiting for PID {pid_to_wait} to exit…")

for _ in range(60):
    ui.pump()
    if not psutil.pid_exists(pid_to_wait):
        log_print(f"✅ PID {pid_to_wait} has exited.")
        break
    log_print(f"Process {pid_to_wait} still running…")
    time.sleep(0.5)
else:
    log_print(f"⚠️ Gave up waiting for PID {pid_to_wait}.")

ui.set_status("Waiting for files to be released…")
for _ in range(6):          # 3 s total, keep UI alive
    ui.pump()
    time.sleep(0.5)

# Delete old files
ui.set_status("Removing old files…")
log_print("Removing old files…")

for root, dirs, files in os.walk(dst_dir, topdown=True):
    dirs[:] = [d for d in dirs if d not in PRESERVE_DIRS]
    for file in files:
        ui.pump()
        fp = os.path.join(root, file)
        if should_preserve_path(fp, dst_dir):
            log_print(f"🛑 Preserved: {os.path.relpath(fp, dst_dir)}")
            continue
        try:
            wait_for_unlock(fp, timeout=5)
            os.remove(fp)
            log_print(f"Deleted: {os.path.relpath(fp, dst_dir)}")
        except Exception as e:
            log_print(f"⚠️ Failed to delete {file}: {e}")

for root, dirs, files in os.walk(dst_dir, topdown=False):
    for d in dirs:
        if d in PRESERVE_DIRS:
            continue
        full = os.path.join(root, d)
        try:
            if not os.listdir(full):
                os.rmdir(full)
                log_print(f"Removed empty dir: {os.path.relpath(full, dst_dir)}")
        except Exception as e:
            log_print(f"⚠️ Failed to remove dir {d}: {e}")

# Copy new files
# Count files first for a rough progress estimate
all_files = []
for root, _, files in os.walk(src_dir):
    for f in files:
        if f not in PRESERVE_FILES:
            all_files.append((os.path.join(root, f),
                              os.path.join(dst_dir,
                                           os.path.relpath(root, src_dir),
                                           f) if os.path.relpath(root, src_dir) != "."
                              else os.path.join(dst_dir, f)))

total     = max(len(all_files), 1)
copy_failures = []

for i, (src_file, dst_file) in enumerate(all_files, 1):
    ui.pump()
    pct = int(i / total * 100)
    ui.set_status(f"Copying files… {i}/{total}  ({pct}%)")
    os.makedirs(os.path.dirname(dst_file), exist_ok=True)
    if not safe_copy_file(src_file, dst_file):
        copy_failures.append((src_file, dst_file))

if copy_failures:
    log_print(f"❌ {len(copy_failures)} files failed to copy:")
    for s, d in copy_failures:
        log_print(f"   Failed: {os.path.basename(s)}")

# Cleanup temp
ui.set_status("Cleaning up…")
try:
    shutil.rmtree(src_dir, ignore_errors=True)
    log_print(f"🧹 Removed temp folder: {src_dir}")
except Exception as e:
    log_print(f"⚠️ Failed to remove temp folder: {e}")

exe_path = os.path.join(dst_dir, exe_name)
log_print(f"Relaunching: {exe_path}")

ui.finish()
deadline = time.time() + 2.5
while time.time() < deadline:
    ui.pump()
    time.sleep(0.05)

try:
    log.close()
except Exception:
    pass

try:
    if os.path.exists(exe_path):
        if os.name == 'nt':
            os.startfile(exe_path)
        else:
            os.execv(exe_path, [exe_path])
    else:
        print(f"❌ Executable not found: {exe_path}")
        sys.exit(1)
except Exception as e:
    print(f"❌ Failed to relaunch: {e}")
    sys.exit(1)