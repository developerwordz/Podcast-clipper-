
import json

from database.db import get_connection


def save_source(source):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO sources
                (podcast_name, creator_name, feed_url, country, genre, artwork_url)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(feed_url) DO UPDATE SET
                podcast_name=excluded.podcast_name,
                creator_name=excluded.creator_name,
                country=excluded.country,
                genre=excluded.genre,
                artwork_url=excluded.artwork_url
            """,
            (
                source["podcast_name"],
                source.get("creator_name"),
                source["feed_url"],
                source.get("country"),
                source.get("genre"),
                source.get("artwork_url"),
            ),
        )

        row = conn.execute(
            "SELECT id FROM sources WHERE feed_url = ?",
            (source["feed_url"],),
        ).fetchone()

        return row["id"]


def list_sources():
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT id, podcast_name, creator_name,
                   permission_status, feed_url
            FROM sources
            ORDER BY podcast_name COLLATE NOCASE
            """
        ).fetchall()


def approve_source(source_id: int, permission_notes: str):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE sources
            SET permission_status='approved',
                permission_notes=?
            WHERE id=?
            """,
            (permission_notes, source_id),
        )

        return cursor.rowcount > 0


def get_sources():
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM sources ORDER BY id"
        ).fetchall()


def save_episodes(source_id: int, episodes):
    inserted = 0

    with get_connection() as conn:
        for episode in episodes:

            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO episodes
                    (
                        source_id,
                        episode_guid,
                        title,
                        description,
                        published_at,
                        duration_seconds,
                        episode_url,
                        audio_url
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_id,
                    episode["episode_guid"],
                    episode["title"],
                    episode["description"],
                    episode["published_at"],
                    episode["duration_seconds"],
                    episode["episode_url"],
                    episode["audio_url"],
                ),
            )

            inserted += cursor.rowcount

        conn.execute(
            """
            UPDATE sources
            SET last_checked_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (source_id,),
        )

    return inserted


# -----------------------------
# EPISODE INTELLIGENCE
# -----------------------------

def get_unranked_episodes():
    """Return episodes that have not yet received a ranking."""

    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                e.*,
                s.podcast_name,
                s.genre,
                s.permission_status
            FROM episodes e
            JOIN sources s ON s.id = e.source_id
            WHERE e.rank_score IS NULL
            ORDER BY e.published_at DESC
            """
        ).fetchall()


def save_episode_rank(episode_id, result):
    """Save an episode's score, tier and explanation."""

    reasons_json = json.dumps(
        result["reasons"],
        ensure_ascii=False
    )

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE episodes
            SET
                rank_score=?,
                rank_tier=?,
                rank_reasons=?,
                ranked_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                result["score"],
                result["tier"],
                reasons_json,
                episode_id,
            ),
        )


def get_ranked_episodes(limit=25, minimum_score=0):
    """Return the highest-scoring ranked episodes."""

    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                e.*,
                s.podcast_name,
                s.genre,
                s.permission_status
            FROM episodes e
            JOIN sources s ON s.id = e.source_id
            WHERE e.rank_score IS NOT NULL
              AND e.rank_score >= ?
            ORDER BY e.rank_score DESC,
                     e.published_at DESC
            LIMIT ?
            """,
            (minimum_score, limit),
        ).fetchall()


def count_episodes():
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total FROM episodes"
        ).fetchone()

        return row["total"]


def count_ranked_episodes():
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM episodes
            WHERE rank_score IS NOT NULL
            """
        ).fetchone()

        return row["total"]
