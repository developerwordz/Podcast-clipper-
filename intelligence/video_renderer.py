
import json
import re
import subprocess
import tempfile
from pathlib import Path

from config import (
    OUTPUT_DIR,
    VIDEO_WIDTH,
    VIDEO_HEIGHT,
    VIDEO_FPS,
)


def run_command(command):
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg failed:\n{result.stderr[-4000:]}"
        )

    return result


def get_video_duration(video_path):
    result = run_command([
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ])

    return float(result.stdout.strip())


def format_ass_time(seconds):
    seconds = max(0, float(seconds))

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60

    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def escape_ass_text(text):
    text = str(text)
    text = text.replace("\\", r"\\")
    text = text.replace("{", r"\{")
    text = text.replace("}", r"\}")
    return text.replace("\n", " ")


def get_clip_words(transcript, clip_start, clip_end):

    words = []

    for segment in transcript.get("segments", []):

        for word in segment.get("words", []) or []:

            try:
                start = float(word["start"])
                end = float(word["end"])
                text = str(word["word"]).strip()

            except (KeyError, TypeError, ValueError):
                continue

            if not text:
                continue

            if end <= clip_start or start >= clip_end:
                continue

            words.append({
                "word": text,
                "start": max(start, clip_start) - clip_start,
                "end": min(end, clip_end) - clip_start,
            })

    return sorted(words, key=lambda item: item["start"])


def group_words(words, max_words=5):

    groups = []
    current = []

    for word in words:

        current.append(word)

        clean_word = word["word"].rstrip(
            "\"'”’)]}"
        )

        sentence_end = clean_word.endswith(
            (".", "?", "!")
        )

        if len(current) >= max_words or sentence_end:
            groups.append(current)
            current = []

    if current:
        groups.append(current)

    return groups


def create_ass_subtitles(
    transcript,
    clip_start,
    clip_end,
    output_path,
):

    words = get_clip_words(
        transcript,
        clip_start,
        clip_end,
    )

    if not words:
        raise ValueError(
            "No word timestamps found for this clip."
        )

    header = r"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,66,&H0000D7FF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,85,85,300,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []

    for group in group_words(words):

        start = group[0]["start"]
        end = max(group[-1]["end"], start + 0.12)

        karaoke_text = []

        for item in group:

            duration = max(
                1,
                round(
                    (item["end"] - item["start"]) * 100
                ),
            )

            karaoke_text.append(
                r"{\k" + str(duration) + "}"
                + escape_ass_text(item["word"])
            )

        line = " ".join(karaoke_text)

        events.append(
            f"Dialogue: 0,"
            f"{format_ass_time(start)},"
            f"{format_ass_time(end)},"
            f"Default,,0,0,0,,{line}"
        )

    output_path.write_text(
        header + "\n".join(events) + "\n",
        encoding="utf-8-sig",
    )


def escape_filter_path(path):

    path = str(Path(path).resolve())
    path = path.replace("\\", "/")
    path = path.replace(":", r"\:")
    path = path.replace("'", r"\'")

    return path


def render_clip(
    video_path,
    transcript,
    clip,
    output_path,
):

    video_path = Path(video_path)
    output_path = Path(output_path)

    if not video_path.exists():
        raise FileNotFoundError(video_path)

    start = float(clip["start"])
    end = float(clip["end"])

    if start < 0 or end <= start:
        raise ValueError("Invalid clip timestamps.")

    duration = get_video_duration(video_path)

    if end > duration:
        raise ValueError(
            f"Clip ends at {end:.2f}s, "
            f"but video duration is {duration:.2f}s."
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with tempfile.TemporaryDirectory() as temp_dir:

        ass_path = Path(temp_dir) / "captions.ass"

        create_ass_subtitles(
            transcript,
            start,
            end,
            ass_path,
        )

        subtitle_path = escape_filter_path(ass_path)

        filter_graph = (
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
            f"boxblur=24:12[background];"
            f"[fg]scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
            f"force_original_aspect_ratio=decrease[foreground];"
            f"[background][foreground]overlay="
            f"(W-w)/2:(H-h)/2,"
            f"subtitles='{subtitle_path}'[v]"
        )

        command = [
            "ffmpeg",
            "-y",

            "-ss", str(start),
            "-i", str(video_path),

            "-t", str(end - start),

            "-filter_complex",
            filter_graph,

            "-map", "[v]",
            "-map", "0:a?",

            "-r", str(VIDEO_FPS),

            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-pix_fmt", "yuv420p",

            "-c:a", "aac",
            "-b:a", "192k",

            "-movflags", "+faststart",

            str(output_path),
        ]

        run_command(command)

    return output_path


def render_episode_clips(
    video_path,
    transcript_path,
    clips_path,
    min_score=0,
    max_clips=None,
):

    video_path = Path(video_path)
    transcript_path = Path(transcript_path)
    clips_path = Path(clips_path)

    with open(transcript_path, encoding="utf-8") as file:
        transcript = json.load(file)

    with open(clips_path, encoding="utf-8") as file:
        clip_data = json.load(file)

    clips = clip_data.get("clips", [])

    selected = [
        clip for clip in clips
        if float(clip.get("overall_score", 0))
        >= min_score
    ]

    selected.sort(
        key=lambda item: float(
            item.get("overall_score", 0)
        ),
        reverse=True,
    )

    if max_clips is not None:
        selected = selected[:max_clips]

    if not selected:
        print("No matching clips found.")
        return []

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    rendered = []

    for index, clip in enumerate(selected, start=1):

        title = str(
            clip.get("title", f"clip_{index}")
        )

        safe_title = re.sub(
            r"[^A-Za-z0-9_-]+",
            "_",
            title,
        ).strip("_")[:55]

        output_path = (
            OUTPUT_DIR
            / f"{index:02d}_{safe_title}.mp4"
        )

        print(f"\nRendering clip {index}/{len(selected)}")
        print(f"Title: {title}")
        print(f"Score: {clip.get('overall_score', 'N/A')}")

        render_clip(
            video_path,
            transcript,
            clip,
            output_path,
        )

        rendered.append(output_path)

        print(f"[OK] Saved: {output_path}")

    return rendered
