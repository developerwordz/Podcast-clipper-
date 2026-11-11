
import argparse
import json
import subprocess
import sys
from pathlib import Path

import yt_dlp

from config import (
    VIDEO_DIR,
    AUDIO_DIR,
    TRANSCRIPT_DIR,
    OUTPUT_DIR,
)

from discovery.youtube_scout import get_top_youtube_videos
from intelligence.transcriber import transcribe_audio
from intelligence.analyze_episode import analyze_episode
from intelligence.video_renderer import render_episode_clips


def get_video_value(video, key, default=None):
    try:
        return video[key]
    except (KeyError, TypeError, IndexError):
        return getattr(video, key, default)


def is_non_podcast(video):
    reasons = get_video_value(video, "traction_reasons", "")

    if isinstance(reasons, str):
        try:
            reasons = json.loads(reasons)
        except (ValueError, TypeError):
            return False

    if isinstance(reasons, dict):
        return reasons.get("category") == "non_podcast"

    return False


def download_video(video_id, video_url):
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)

    output_template = str(VIDEO_DIR / f"{video_id}.%(ext)s")

    # Reuse an already downloaded video.
    existing = list(VIDEO_DIR.glob(f"{video_id}.*"))

    for path in existing:
        if path.suffix.lower() in {
            ".mp4", ".mkv", ".webm", ".mov"
        }:
            print(f"[CACHE] Existing video found: {path}")
            return path

    print("\n[DOWNLOAD] Downloading source video (maximum 480p)...")

    options = {
        # Prefer a single combined MP4 stream to avoid merging.
        # Fall back to separate streams if necessary.
        "format": (
            "best[height<=480][ext=mp4]/"
            "best[height<=480]/"
            "bestvideo[height<=480]+bestaudio/"
            "best[height<=480]"
        ),

        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "noplaylist": True,

        # Download reliability and speed.
        "retries": 10,
        "fragment_retries": 10,
        "concurrent_fragment_downloads": 4,
        "socket_timeout": 30,
        "continuedl": True,

        # Show download progress and speed.
        "quiet": False,
        "no_warnings": False,
        "progress": True,
    }

    with yt_dlp.YoutubeDL(options) as downloader:
        downloader.download([video_url])

    candidates = [
        path for path in VIDEO_DIR.glob(f"{video_id}.*")
        if path.suffix.lower() in {
            ".mp4", ".mkv", ".webm", ".mov"
        }
    ]

    if not candidates:
        raise RuntimeError(
            "Video download finished, but no usable video file was found."
        )

    result = max(candidates, key=lambda path: path.stat().st_size)

    print(
        f"[DOWNLOAD COMPLETE] {result.name} "
        f"({result.stat().st_size / (1024 * 1024):.1f} MB)"
    )

    return result



def extract_audio(video_path, video_id):
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    audio_path = AUDIO_DIR / f"{video_id}.wav"

    if audio_path.exists() and audio_path.stat().st_size > 1000:
        print(f"[CACHE] Existing audio found: {audio_path}")
        return audio_path

    print("\n[AUDIO] Extracting audio with FFmpeg...")

    command = [
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(audio_path),
    ]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg audio extraction failed:\n{result.stderr[-2000:]}"
        )

    if not audio_path.exists():
        raise RuntimeError("FFmpeg did not create the audio file.")

    return audio_path


def process_video(video, clip_count=3, min_score=0):
    video_id = get_video_value(video, "youtube_video_id")
    title = get_video_value(video, "title", "Untitled video")
    video_url = get_video_value(video, "video_url")

    if not video_id or not video_url:
        raise ValueError("Selected YouTube result has no video ID or URL.")

    print("\n" + "=" * 65)
    print(f"PROCESSING: {title}")
    print(f"VIDEO ID: {video_id}")
    print("=" * 65)

    # STEP 1: Get source video.
    video_path = download_video(video_id, video_url)

    print(f"\n[OK] Video: {video_path}")

    # STEP 2: Extract audio and transcribe.
    audio_path = extract_audio(video_path, video_id)

    print("\n[TRANSCRIPTION] Starting Whisper...")

    transcript = transcribe_audio(
        audio_path=audio_path,
        episode_id=video_id,
    )

    if not transcript or not transcript.get("segments"):
        raise RuntimeError("Whisper produced no usable transcript.")

    print(
        f"[OK] Transcribed {len(transcript['segments'])} segments."
    )

    # STEP 3: Gemini identifies compelling moments.
    print("\n[GEMINI] Finding compelling moments...")

    analyze_episode(
        episode_id=video_id,
        target_clips=clip_count,
    )

    clips_path = TRANSCRIPT_DIR / f"episode_{video_id}_clips.json"

    if not clips_path.exists():
        raise RuntimeError("Gemini did not produce a clips file.")

    with open(clips_path, "r", encoding="utf-8") as file:
        clip_data = json.load(file)

    if not clip_data.get("clips"):
        raise RuntimeError("Gemini found no usable clips.")

    # STEP 4: Render Shorts.
    print("\n[RENDER] Creating captioned vertical Shorts...")

    transcript_path = TRANSCRIPT_DIR / f"episode_{video_id}.json"

    rendered_files = render_episode_clips(
        video_path=video_path,
        transcript_path=transcript_path,
        clips_path=clips_path,
        min_score=min_score,
        max_clips=clip_count,
    )

    if not rendered_files:
        raise RuntimeError("No Shorts were rendered.")

    print("\n[COMPLETE] Generated Shorts:")

    for index, path in enumerate(rendered_files, start=1):
        print(f"{index}. {Path(path).resolve()}")

    return rendered_files


def run_autopilot(video_count=1, clip_count=3, min_score=0):
    print("\n" + "=" * 65)
    print("                 CLIPPULSE AUTOPILOT")
    print("=" * 65)

    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\n[SCOUT] Loading existing YouTube discoveries...")

    videos = get_top_youtube_videos(
        limit=max(video_count * 5, 10),
        minimum_score=0,
    )

    videos = [
        video for video in videos
        if not is_non_podcast(video)
        and get_video_value(video, "video_url")
        and get_video_value(video, "youtube_video_id")
    ]

    if not videos:
        raise RuntimeError(
            "No suitable YouTube discoveries found. "
            "Run the YouTube Scout first."
        )

    print(f"[SCOUT] Found {len(videos)} candidate videos.")

    successful = 0
    failed = 0

    for index, video in enumerate(videos[:video_count], start=1):
        print(f"\n\nCANDIDATE {index}/{min(video_count, len(videos))}")

        try:
            process_video(
                video,
                clip_count=clip_count,
                min_score=min_score,
            )
            successful += 1

        except Exception as exc:
            failed += 1
            print(f"\n[FAILED] {exc}")

    print("\n" + "=" * 65)
    print("                 AUTOPILOT SUMMARY")
    print("=" * 65)
    print(f"Videos processed successfully: {successful}")
    print(f"Videos failed: {failed}")
    print(f"Shorts directory: {OUTPUT_DIR.resolve()}")

    if successful == 0:
        raise RuntimeError(
            "Autopilot could not generate any Shorts. "
            "Check the error messages above."
        )


def main():
    parser = argparse.ArgumentParser(
        description="ClipPulse automatic YouTube Shorts generator."
    )

    parser.add_argument("--videos", type=int, default=1)
    parser.add_argument("--clips", type=int, default=3)
    parser.add_argument("--min-score", type=float, default=0)

    args = parser.parse_args()

    if args.videos < 1 or args.clips < 1:
        parser.error("--videos and --clips must be at least 1.")

    try:
        run_autopilot(
            video_count=args.videos,
            clip_count=args.clips,
            min_score=args.min_score,
        )

    except KeyboardInterrupt:
        print("\n[STOPPED] Autopilot interrupted.")
        sys.exit(1)

    except Exception as exc:
        print(f"\n[ERROR] AUTOPILOT FAILED: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
