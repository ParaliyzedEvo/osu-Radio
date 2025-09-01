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

def safe_copy_file(src, dst, max_retries=3):
    """Safely copy a file with retries and better error handling."""
    for attempt in range(max_retries):
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            
            if not wait_for_unlock(src, timeout=10):
                log_print(f"⚠️ Source file locked: {src}")
                continue
            
            # Try different copy methods
            if attempt == 0:
                shutil.copy2(src, dst)
            elif attempt == 1:
                shutil.copy(src, dst)
            else:
                with open(src, 'rb') as src_file, open(dst, 'wb') as dst_file:
                    shutil.copyfileobj(src_file, dst_file)
            
            if os.path.exists(dst) and os.path.getsize(dst) > 0:
                log_print(f"✅ Successfully copied: {os.path.basename(src)} (attempt {attempt + 1})")
                return True
            else:
                log_print(f"⚠️ Copy verification failed for: {src}")
                
        except PermissionError as e:
            log_print(f"⚠️ Permission denied copying {src}: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
        except OSError as e:
            log_print(f"⚠️ OS error copying {src}: {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
        except Exception as e:
            log_print(f"⚠️ Unexpected error copying {src}: {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
    
    log_print(f"❌ Failed to copy after {max_retries} attempts: {src}")
    return False

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
            # Try to open the file in append mode (less intrusive than rename)
            with open(target_path, 'ab'):
                pass
            return True
        except (PermissionError, OSError) as e:
            log_print(f"Waiting for file unlock: {os.path.basename(target_path)} - {e}")
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
            # Wait for file to be unlocked before deleting
            wait_for_unlock(file_path, timeout=5)
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
copy_failures = []
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
        
        if not safe_copy_file(src_file, dst_file):
            copy_failures.append((src_file, dst_file))

# Report copy failures
if copy_failures:
    log_print(f"❌ {len(copy_failures)} files failed to copy:")
    for src, dst in copy_failures:
        log_print(f"   Failed: {os.path.basename(src)}")

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
        # Ensure the exe is executable
        if os.name == 'nt':
            os.startfile(exe_path)
        else:
            os.execv(exe_path, [exe_path])
    else:
        print(f"❌ Executable not found: {exe_path}")
        sys.exit(1)
except Exception as e:
    print(f"❌ Failed to relaunch app: {e}")
    sys.exit(1)