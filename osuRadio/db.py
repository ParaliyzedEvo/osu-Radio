import os
import sqlite3
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from osuRadio.config import DATABASE_FILE

def init_db():
    """Initialize the database with songs and metadata tables."""
    with sqlite3.connect(DATABASE_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                artist TEXT,
                mapper TEXT,
                audio TEXT,
                background TEXT,
                length INTEGER,
                osu_file TEXT,
                folder TEXT,
                source_folder TEXT,
                UNIQUE(title, artist, mapper, source_folder)
            )""")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )""")
        try:
            cursor.execute("ALTER TABLE songs ADD COLUMN source_folder TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists
        conn.commit()

def validate_cache(folder) -> Tuple[bool, str, List[Dict]]:
    if not DATABASE_FILE.exists():
        return False, "No cache database found", []
    
    # Convert Path to string if needed
    folder_str = str(folder) if isinstance(folder, Path) else folder
    
    if not os.path.exists(folder_str):
        return False, f"Folder not found: {folder_str}", []
    
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='metadata'")
            if not cursor.fetchone():
                return False, "Cache database is outdated (missing metadata table)", []
            
            cursor.execute("SELECT value FROM metadata WHERE key = ?", (f'folder_mtime_{folder_str}',))
            stored_mtime = cursor.fetchone()
            current_mtime = str(os.path.getmtime(folder_str))
            
            cursor.execute(
                "SELECT title, artist, mapper, audio, background, length, osu_file, folder, source_folder FROM songs WHERE source_folder = ? OR source_folder IS NULL",
                (folder_str,)
            )
            cached_songs = [
                dict(zip(["title", "artist", "mapper", "audio", "background", "length", "osu_file", "folder", "source_folder"], row))
                for row in cursor.fetchall()
            ]
            
            if not cached_songs:
                return False, f"No songs cached for folder: {folder_str}", []
            
            missing_songs = []
            valid_songs = 0
            
            for song in cached_songs:
                osu_file_path = Path(song.get("folder", "")) / song.get("osu_file", "")
                if not osu_file_path.exists():
                    missing_songs.append(song)
                else:
                    valid_songs += 1
            
            missing_count = len(missing_songs)
            total_count = len(cached_songs)
            
            if missing_count == 0:
                if stored_mtime and stored_mtime[0] == current_mtime:
                    return True, f"Cache is up to date ({total_count} songs)", []
                else:
                    return True, f"Cache is valid but folder was modified ({total_count} songs)", []
            elif missing_count < total_count * 0.3:  # Less than 30% missing
                return True, f"Cache needs cleanup ({missing_count} missing, {valid_songs} valid songs)", missing_songs
            else:
                return False, f"Too many songs missing ({missing_count}/{total_count}) - full rescan recommended", missing_songs
                
    except Exception as e:
        print(f"[validate_cache] Error: {e}")
        return False, f"Cache validation error: {str(e)}", []

def load_cache(folder) -> Optional[List[Dict]]:
    if not DATABASE_FILE.exists():
        return None
    
    # Convert Path to string if needed
    folder_str = str(folder) if isinstance(folder, Path) else folder
    
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT title, artist, mapper, audio, background, length, osu_file, folder 
                FROM songs 
                WHERE source_folder = ? OR (source_folder IS NULL AND folder LIKE ?)
            """, (folder_str, f"{folder_str}%"))
            
            songs = [
                dict(zip(["title", "artist", "mapper", "audio", "background", "length", "osu_file", "folder"], row))
                for row in cursor.fetchall()
            ]

            valid_songs = []
            for song in songs:
                osu_file_path = Path(song.get("folder", "")) / song.get("osu_file", "")
                if osu_file_path.exists():
                    valid_songs.append(song)
            
            return valid_songs if valid_songs else None
            
    except Exception as e:
        print(f"[load_cache] Error: {e}")
        return None

def remove_missing_songs(missing_songs: List[Dict]) -> int:
    if not missing_songs:
        return 0
    
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            removed_count = 0
            
            for song in missing_songs:
                cursor.execute("""
                    DELETE FROM songs 
                    WHERE title = ? AND artist = ? AND mapper = ?
                """, (song.get("title"), song.get("artist"), song.get("mapper")))
                removed_count += cursor.rowcount
            
            conn.commit()
            print(f"[remove_missing_songs] Removed {removed_count} missing songs from cache")
            return removed_count
            
    except Exception as e:
        print(f"[remove_missing_songs] Error: {e}")
        return 0

def update_folder_mtime(folder: str):
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (f'folder_mtime_{folder}', str(os.path.getmtime(folder)))
            )
            conn.commit()
    except Exception as e:
        print(f"[update_folder_mtime] Error: {e}")

def save_cache(folder, maps: List[Dict]):
    init_db()
    folder_str = str(folder) if isinstance(folder, Path) else folder
    
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN TRANSACTION")
            
            for s in maps:
                cursor.execute("""
                    INSERT OR REPLACE INTO songs
                    (title, artist, mapper, audio, background, length, osu_file, folder, source_folder)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                        s.get("title"), s.get("artist"), s.get("mapper"),
                        s.get("audio"), s.get("background"), s.get("length", 0),
                        s.get("osu_file"), s.get("folder"), folder_str
                    ))
            
            cursor.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (f'folder_mtime_{folder_str}', str(os.path.getmtime(folder_str)))
            )
            
            conn.commit()
            print(f"[save_cache] Saved {len(maps)} songs to cache for folder: {folder_str}")
            
    except Exception as e:
        print(f"[save_cache] Error: {e}")

def clear_cache(folder: Optional[str] = None):
    if not DATABASE_FILE.exists():
        return
    
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            
            if folder:
                cursor.execute("DELETE FROM songs WHERE source_folder = ?", (folder,))
                cursor.execute("DELETE FROM metadata WHERE key = ?", (f'folder_mtime_{folder}',))
                print(f"[clear_cache] Cleared cache for folder: {folder}")
            else:
                cursor.execute("DELETE FROM songs")
                cursor.execute("DELETE FROM metadata")
                print("[clear_cache] Cleared entire cache database")
            
            conn.commit()
            
    except Exception as e:
        print(f"[clear_cache] Error: {e}")

def get_cache_stats() -> Dict:
    if not DATABASE_FILE.exists():
        return {"total_songs": 0, "folders": []}
    
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            
            # Total songs
            cursor.execute("SELECT COUNT(*) FROM songs")
            total = cursor.fetchone()[0]
            
            # Songs per folder
            cursor.execute("""
                SELECT source_folder, COUNT(*) 
                FROM songs 
                GROUP BY source_folder
            """)
            folders = [{"folder": row[0] or "Unknown", "count": row[1]} for row in cursor.fetchall()]
            
            return {"total_songs": total, "folders": folders}
            
    except Exception as e:
        print(f"[get_cache_stats] Error: {e}")
        return {"total_songs": 0, "folders": []}

def get_audio_path(song: Dict) -> Path:
    return Path(song["folder"]) / song["audio"]