
import re
import requests

from pathlib import Path
from urllib.parse import urlparse

from config import (
    AUDIO_DIR,
    REQUEST_TIMEOUT,
    USER_AGENT,
    MAX_AUDIO_SIZE_MB,
)
from database.db import get_connection


AUDIO_EXTENSIONS = {
    ".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus"
}


def get_approved_episode(episode_id):
    """Retrieve an episode only if its source is approved."""

    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                e.id,
                e.title,
                e.audio_url,
                s.podcast_name,
                s.permission_status
            FROM episodes e
            JOIN sources s ON s.id = e.source_id
            WHERE e.id = ?
              AND s.permission_status = 'approved'
            """,
            (episode_id,),
        ).fetchone()


def _safe_filename(value):
    value = re.sub(r'[<>:"/\\|?*]', "_", str(value))
    value = re.sub(r"\s+", "_", value.strip())
    return value[:100] or "episode"


def _audio_extension(url):
    path = urlparse(url).path.lower()
    extension = Path(path).suffix

    if extension in AUDIO_EXTENSIONS:
        return extension

    return ".mp3"


def download_episode_audio(episode_id):
    episode = get_approved_episode(episode_id)

    if episode is None:
        raise PermissionError(
            "Episode not found or its source is not approved. "
            "Audio download blocked."
        )

    audio_url = episode["audio_url"]

    if not audio_url:
        raise ValueError("This episode has no audio enclosure URL.")

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    extension = _audio_extension(audio_url)

    filename = (
        f"{episode_id}_"
        f"{_safe_filename(episode['title'])}"
        f"{extension}"
    )

    output_path = AUDIO_DIR / filename
    temporary_path = output_path.with_suffix(
        output_path.suffix + ".part"
    )

    if output_path.exists() and output_path.stat().st_size > 0:
        print(f"Audio already downloaded: {output_path}")
        return output_path

    max_bytes = MAX_AUDIO_SIZE_MB * 1024 * 1024

    headers = {"User-Agent": USER_AGENT}

    print(f"Downloading: {episode['title']}")

    try:
        with requests.get(
            audio_url,
            headers=headers,
            stream=True,
            timeout=(10, REQUEST_TIMEOUT),
        ) as response:

            response.raise_for_status()

            content_length = response.headers.get(
                "Content-Length"
            )

            if content_length and int(content_length) > max_bytes:
                raise ValueError(
                    f"Audio exceeds the {MAX_AUDIO_SIZE_MB} MB limit."
                )

            downloaded = 0

            with open(temporary_path, "wb") as file:
                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):
                    if not chunk:
                        continue

                    downloaded += len(chunk)

                    if downloaded > max_bytes:
                        raise ValueError(
                            "Audio exceeded the configured size limit."
                        )

                    file.write(chunk)

        if downloaded == 0:
            raise ValueError("Downloaded audio file is empty.")

        temporary_path.replace(output_path)

        print(
            f"Download complete: "
            f"{downloaded / (1024 * 1024):.2f} MB"
        )

        return output_path

    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
