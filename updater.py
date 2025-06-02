import time, shutil, os, sys, psutil
MAX_RETRIES = 10

# Log file for debug info (next to the app)
log_path = "osu_radio_updater_log.txt"
log = open(log_path, "w", encoding="utf-8")

def log_print(msg):
    print(msg)
    log.write(msg + "\n")
    log.flush()
    
pid_to_wait = int(sys.argv[4])  # added PID param

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
pid = int(sys.argv[4])  # pass it from the app
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

# Copy files with overwrite, retries, and forced delete if needed
for root, dirs, files in os.walk(src_dir):
    rel_path = os.path.relpath(root, src_dir)
    dst_root = os.path.join(dst_dir, rel_path)
    os.makedirs(dst_root, exist_ok=True)

    for file in files:
        s = os.path.join(root, file)
        d = os.path.join(dst_root, file)

        for attempt in range(MAX_RETRIES):
            try:
                if os.path.exists(d):
                    wait_for_unlock(d)
                    os.remove(d)
                shutil.copy2(s, d)
                log_print(f"Copied: {s} -> {d}")
                break
            except Exception as e:
                log_print(f"[{attempt+1}/{MAX_RETRIES}] Failed to copy {s} → {d}: {e}")
                time.sleep(1)
        else:
            log_print(f"❌ Gave up copying {s}")

# Cleanup this script BEFORE launching app
try:
    os.remove(__file__)
except Exception as e:
    log_print(f"Failed to delete updater script: {e}")

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