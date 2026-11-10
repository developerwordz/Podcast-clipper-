
import sqlite3
from pathlib import Path

from config import DATABASE_PATH


def get_connection():
    Path(DATABASE_PATH).parent.mkdir(
        parents=True,
        exist_ok=True
    )

    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA foreign_keys = ON")

    return connection


def initialize_database():
    with get_connection() as conn:

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                podcast_name TEXT NOT NULL,
                creator_name TEXT,
                feed_url TEXT NOT NULL UNIQUE,
                country TEXT,
                genre TEXT,
                artwork_url TEXT,
                permission_status TEXT NOT NULL DEFAULT 'unreviewed',
                permission_notes TEXT,
                discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_checked_at TEXT
            );

            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER NOT NULL,
                episode_guid TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                published_at TEXT,
                duration_seconds INTEGER,
                episode_url TEXT,
                audio_url TEXT,
                discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source_id, episode_guid),
                FOREIGN KEY(source_id)
                    REFERENCES sources(id)
                    ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_episodes_published
                ON episodes(published_at);
            """
        )

        # Safely migrate existing databases.
        existing_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(episodes)"
            ).fetchall()
        }

        migrations = {
            "rank_score": "INTEGER",
            "rank_tier": "TEXT",
            "rank_reasons": "TEXT",
            "ranked_at": "TEXT",
        }

        for column_name, column_type in migrations.items():

            if column_name not in existing_columns:
                conn.execute(
                    f"""
                    ALTER TABLE episodes
                    ADD COLUMN {column_name} {column_type}
                    """
                )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_episodes_rank
            ON episodes(rank_score)
            """
        )
