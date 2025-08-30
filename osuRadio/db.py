import os
import sqlite3
from pathlib import Path
from .config import *

def init_db():
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
                UNIQUE(title, artist, mapper)
            )""")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )""")
        conn.commit()

def load_cache(folder: str) -> list | None:
    if not DATABASE_FILE.exists():
        return None
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM metadata WHERE key = 'folder_mtime'")
            mtime = cursor.fetchone()
            if mtime and mtime[0] == str(os.path.getmtime(folder)):
                cursor.execute("SELECT title, artist, mapper, audio, background, length, osu_file, folder FROM songs")
                return [
                    dict(zip(["title", "artist", "mapper", "audio", "background", "length", "osu_file", "folder"], row))
                    for row in cursor.fetchall()
                ]
    except Exception as e:
        print(f"[load_cache] Error: {e}")
    return None

def save_cache(folder: str, maps: list):
    init_db()
    try:
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN TRANSACTION")
            for s in maps:
                cursor.execute("""
                    INSERT OR REPLACE INTO songs
                    (title, artist, mapper, audio, background, length, osu_file, folder)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (
                        s.get("title"), s.get("artist"), s.get("mapper"),
                        s.get("audio"), s.get("background"), s.get("length", 0),
                        s.get("osu_file"), s.get("folder")
                    ))
            cursor.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                           ('folder_mtime', str(os.path.getmtime(folder))))
            conn.commit()
    except Exception as e:
        print(f"[save_cache] Error: {e}")

def get_audio_path(song: dict) -> Path:
    return Path(song["folder"]) / song["audio"]