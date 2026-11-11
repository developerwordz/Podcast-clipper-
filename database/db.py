
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
            CREATE TABLE IF NOT EXISTS youtube_stats_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                youtube_video_id TEXT NOT NULL,
                view_count INTEGER NOT NULL DEFAULT 0,
                like_count INTEGER NOT NULL DEFAULT 0,
                comment_count INTEGER NOT NULL DEFAULT 0,
                captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(youtube_video_id)
                    REFERENCES youtube_videos(youtube_video_id)
                    ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_youtube_history_video
    ON youtube_stats_history(youtube_video_id, captured_at);
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

            CREATE TABLE IF NOT EXISTS youtube_videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                youtube_video_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                description TEXT,
                channel_id TEXT,
                channel_title TEXT,
                published_at TEXT,
                duration_seconds INTEGER,
                video_url TEXT NOT NULL,
                thumbnail_url TEXT,
                view_count INTEGER NOT NULL DEFAULT 0,
                like_count INTEGER NOT NULL DEFAULT 0,
                comment_count INTEGER NOT NULL DEFAULT 0,
                traction_score REAL NOT NULL DEFAULT 0,
                traction_reasons TEXT,
                discovered_query TEXT,
                first_discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_checked_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_youtube_traction
                ON youtube_videos(traction_score);

            CREATE INDEX IF NOT EXISTS idx_youtube_published
                ON youtube_videos(published_at);
            """
        )

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
        