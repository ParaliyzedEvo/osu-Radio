import sys
import gzip
import shutil
from datetime import datetime
from pathlib import Path


def setup_logging(base_path: Path):
    log_dir = base_path / "logs"
    log_dir.mkdir(exist_ok=True)

    latest = log_dir / "latest.log"

    # Rotate previous session's log into a timestamped .gz archive
    if latest.exists() and latest.stat().st_size > 0:
        try:
            mtime = datetime.fromtimestamp(latest.stat().st_mtime)
            archive_name = mtime.strftime("%Y-%m-%d_%H-%M-%S") + ".log.gz"
            archive_path = log_dir / archive_name
            with latest.open("rb") as f_in, gzip.open(archive_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        except Exception as e:
            print(f"[Logger] Failed to archive previous log: {e}")

    # Open latest.log for this session (overwrite)
    try:
        log_file = latest.open("w", encoding="utf-8", buffering=1)
    except Exception as e:
        print(f"[Logger] Could not open latest.log for writing: {e}")
        return

    sys.stdout = _Tee(sys.stdout, log_file)
    sys.stderr = _Tee(sys.stderr, log_file)

    print(f"[Logger] Session started — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[Logger] Log file: {latest}")


class _Tee:
    def __init__(self, original, log_file):
        self._original = original
        self._log = log_file

    def write(self, data):
        try:
            self._original.write(data)
            self._original.flush()
        except Exception:
            pass
        try:
            self._log.write(data)
        except Exception:
            pass

    def flush(self):
        try:
            self._original.flush()
        except Exception:
            pass
        try:
            self._log.flush()
        except Exception:
            pass

    def fileno(self):
        return self._original.fileno()

    def __getattr__(self, name):
        return getattr(self._original, name)