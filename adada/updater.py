import time, shutil, os, sys, psutil, uuid
PRESERVE_FILES = {"songs.db", "settings.json"}

# Log file for debug info
log_path = "updater_log.txt"
log = open(log_path, "w", encoding="utf-8")

def log_print(msg):
    print(msg)
    log.write(msg + "\n")
    log.flush()
    
pid_to_wait = int(sys.argv[4])

log_print(f"Waiting for PID {pid_to_wait} to exit...")

# Wait up to 30 seconds for the process to close
for _ in range(60):
    if not psutil.pid_exists(pid_to_wait):
        log_print(f"✅ PID {pid_to_wait} has exited.")
        break
    log_print(f"Process {pid_to_wait} still running...")
    time.sleep(0.5)
else:
    log_print(f"⚠️ Gave up waiting for PID {pid_to_wait} to close.")

time.sleep(3.0)  # Increase delay for safety

src_dir = sys.argv[1]
dst_dir = sys.argv[2]
exe_name = sys.argv[3]

# Before copy
pid = int(sys.argv[4])
while psutil.pid_exists(pid):
    log_print(f"Waiting for PID {pid} to exit...")
    time.sleep(0.5)

def wait_for_unlock(target_path, timeout=30):
    # Wait until the file at target_path is no longer locked.
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            os.rename(target_path, target_path)  # no-op if not locked
            return True
        except Exception as e:
            log_print(f"Waiting for file unlock: {target_path} - {e}")
            time.sleep(0.5)
    log_print(f"❌ Timed out waiting for unlock: {target_path}")
    return False

# Delete everything
for root, dirs, files in os.walk(dst_dir, topdown=False):
    for file in files:
        rel_path = os.path.relpath(os.path.join(root, file), dst_dir)
        if os.path.basename(rel_path) in PRESERVE_FILES:
            log_print(f"🛑 Preserved: {rel_path}")
            continue
        try:
            os.remove(os.path.join(root, file))
        except Exception as e:
            log_print(f"⚠️ Failed to delete file {file}: {e}")

    for dir in dirs:
        try:
            full_dir = os.path.join(root, dir)
            # Skip folders containing preserved files
            if any(os.path.isfile(os.path.join(full_dir, f)) and f in PRESERVE_FILES for f in os.listdir(full_dir)):
                log_print(f"🛑 Skipped deleting folder containing preserved files: {full_dir}")
                continue
            shutil.rmtree(full_dir, ignore_errors=True)
        except Exception as e:
            log_print(f"⚠️ Failed to delete folder {dir}: {e}")

# Copy all files from src_dir into dst_dir
for root, dirs, files in os.walk(src_dir):
    rel_path = os.path.relpath(root, src_dir)
    target_root = os.path.join(dst_dir, rel_path)
    os.makedirs(target_root, exist_ok=True)

    for file in files:
        src_file = os.path.join(root, file)
        dst_file = os.path.join(target_root, file)

        try:
            shutil.copy2(src_file, dst_file)
            log_print(f"Copied: {src_file} -> {dst_file}")
        except Exception as e:
            log_print(f"❌ Failed to copy {src_file} → {dst_file}: {e}")

# Remove temp files
try:
    shutil.rmtree(src_dir, ignore_errors=True)
    log_print(f"🧹 Removed temporary update folder: {src_dir}")
except Exception as e:
    log_print(f"⚠️ Failed to remove temporary update folder: {e}")

# Relaunch the app
exe_path = os.path.join(dst_dir, exe_name)
try:
    os.execv(exe_path, [exe_path])
    log_print(f"Launching: {exe_path}")
except Exception as e:
    log_print(f"Failed to relaunch app: {e}")

try:
    log.close()
    os.remove(log_path)
except:
    pass