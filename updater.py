import time, shutil, os, sys, psutil, uuid

PRESERVE_FILES = {"songs.db", "settings.json"}
PRESERVE_DIRS = {"custom_songs"}

# Log file for debug info
log_path = "updater_log.txt"
log = open(log_path, "w", encoding="utf-8")

def log_print(msg):
    print(msg)
    log.write(msg + "\n")
    log.flush()

if len(sys.argv) < 5:
    log_print("❌ Not enough arguments provided. Expected: src_dir dst_dir exe_name pid")
    sys.exit(1)

src_dir = sys.argv[1]
dst_dir = sys.argv[2]
exe_name = sys.argv[3]
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

def wait_for_unlock(target_path, timeout=30):
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

# Helper function to check if a path should be preserved
def should_preserve_path(path, base_dir):
    rel_path = os.path.relpath(path, base_dir)
    path_parts = rel_path.split(os.sep)
    
    for part in path_parts:
        if part in PRESERVE_DIRS:
            return True
    
    filename = os.path.basename(path)
    if filename in PRESERVE_FILES:
        return True
    
    return False

# Delete everything except preserved files/dirs
for root, dirs, files in os.walk(dst_dir, topdown=True):
    dirs[:] = [d for d in dirs if d not in PRESERVE_DIRS]
    
    for file in files:
        file_path = os.path.join(root, file)
        if should_preserve_path(file_path, dst_dir):
            log_print(f"🛑 Preserved file: {os.path.relpath(file_path, dst_dir)}")
            continue
        try:
            os.remove(file_path)
            log_print(f"Deleted file: {os.path.relpath(file_path, dst_dir)}")
        except Exception as e:
            log_print(f"⚠️ Failed to delete file {file}: {e}")

for root, dirs, files in os.walk(dst_dir, topdown=False):
    for dir in dirs:
        if dir in PRESERVE_DIRS:
            log_print(f"🛑 Preserved folder: {dir}")
            continue
        
        full_dir = os.path.join(root, dir)
        try:
            # Only remove if directory is empty
            if not os.listdir(full_dir):
                os.rmdir(full_dir)
                log_print(f"Removed empty directory: {os.path.relpath(full_dir, dst_dir)}")
        except Exception as e:
            log_print(f"⚠️ Failed to remove directory {dir}: {e}")

# Copy all files from src_dir into dst_dir
for root, dirs, files in os.walk(src_dir):
    rel_path = os.path.relpath(root, src_dir)
    target_root = os.path.join(dst_dir, rel_path) if rel_path != "." else dst_dir
    os.makedirs(target_root, exist_ok=True)
    
    for file in files:
        if file in PRESERVE_FILES:
            log_print(f"🛑 Preserved (not copied): {file}")
            continue
        
        src_file = os.path.join(root, file)
        dst_file = os.path.join(target_root, file)
        
        try:
            shutil.copy2(src_file, dst_file)
            log_print(f"Copied: {os.path.relpath(src_file, src_dir)} -> {os.path.relpath(dst_file, dst_dir)}")
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
log_print(f"Preparing to launch: {exe_path}")

# Close log
try:
    log.close()
except Exception as e:
    print(f"Warning: Failed to close log file: {e}")

# Relaunch the app (replaces this process)
try:
    if os.path.exists(exe_path):
        os.execv(exe_path, [exe_path])
    else:
        print(f"❌ Executable not found: {exe_path}")
        sys.exit(1)
except Exception as e:
    print(f"❌ Failed to relaunch app: {e}")
    sys.exit(1)