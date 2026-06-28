import re as _re
import sqlite3
import time
from contextlib import contextmanager
from typing import Iterator

from .config import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS books (
  id              TEXT PRIMARY KEY,
  title           TEXT NOT NULL,
  author          TEXT,
  language        TEXT,
  format          TEXT NOT NULL,
  paragraph_count INTEGER NOT NULL,
  added_at        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS progress (
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  book_id       TEXT    NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  paragraph_idx INTEGER NOT NULL DEFAULT 0,
  char_offset   INTEGER NOT NULL DEFAULT 0,
  last_read_at  INTEGER NOT NULL,
  PRIMARY KEY (user_id, book_id)
);

CREATE TABLE IF NOT EXISTS prefs (
  user_id     INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  voice_id    TEXT NOT NULL DEFAULT 'kokoro:af_heart',
  speed       REAL NOT NULL DEFAULT 0.9,
  font_size   INTEGER NOT NULL DEFAULT 18,
  line_height REAL NOT NULL DEFAULT 1.6,
  theme       TEXT NOT NULL DEFAULT 'auto'
);

CREATE TABLE IF NOT EXISTS quotes (
  id            INTEGER PRIMARY KEY,
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  book_id       TEXT    NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  paragraph_idx INTEGER NOT NULL,
  text          TEXT    NOT NULL,
  note          TEXT,
  created_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quotes_user_book ON quotes (user_id, book_id);
"""


def now() -> int:
    return int(time.time())


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path(), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
    finally:
        conn.close()


NEW_BOOK_COLUMNS = [
    ("description", "TEXT"),
    ("published_year", "INTEGER"),
    ("isbn", "TEXT"),
    ("genre", "TEXT"),
    ("word_count", "INTEGER"),
    ("metadata_source", "TEXT"),
    ("cover_active", "TEXT"),
]

NEW_PROGRESS_COLUMNS = [
    ("total_seconds", "INTEGER NOT NULL DEFAULT 0"),
]

NEW_PREFS_COLUMNS = [
    ("font_family", "TEXT NOT NULL DEFAULT 'serif'"),
    ("show_images", "INTEGER NOT NULL DEFAULT 1"),
]

# SQLite cannot parameterize DDL, so we manually validate column names and
# types at import time. Any new entry that doesn't match these patterns
# fails fast — preventing accidental injection if NEW_BOOK_COLUMNS ever
# starts being populated from config or user data.
_VALID_COL_NAME = _re.compile(r"^[a-z_][a-z0-9_]*$")
_VALID_COL_TYPES = {
    "TEXT",
    "INTEGER",
    "REAL",
    "BLOB",
    "INTEGER NOT NULL DEFAULT 0",
    "INTEGER NOT NULL DEFAULT 1",
    "TEXT NOT NULL DEFAULT 'serif'",
}
for _col, _ty in NEW_BOOK_COLUMNS + NEW_PROGRESS_COLUMNS + NEW_PREFS_COLUMNS:
    if not _VALID_COL_NAME.match(_col) or _ty not in _VALID_COL_TYPES:
        raise AssertionError(f"invalid migration column: {_col} {_ty}")


def init_db() -> None:
    with connect() as c:
        c.executescript(SCHEMA)
        for col, ty in NEW_BOOK_COLUMNS:
            try:
                c.execute(f"ALTER TABLE books ADD COLUMN {col} {ty}")
            except sqlite3.OperationalError:
                pass  # column already exists
        for col, ty in NEW_PROGRESS_COLUMNS:
            try:
                c.execute(f"ALTER TABLE progress ADD COLUMN {col} {ty}")
            except sqlite3.OperationalError:
                pass  # column already exists
        for col, ty in NEW_PREFS_COLUMNS:
            try:
                c.execute(f"ALTER TABLE prefs ADD COLUMN {col} {ty}")
            except sqlite3.OperationalError:
                pass  # column already exists
        # Migrate any legacy/non-kokoro voice id to the Kokoro default.
        # Idempotent: rows already on a kokoro id are left alone (kokoro:%
        # is excluded), everything else is remapped.
        c.execute(
            "UPDATE prefs SET voice_id = 'kokoro:af_heart' "
            "WHERE voice_id NOT LIKE 'kokoro:%'"
        )
