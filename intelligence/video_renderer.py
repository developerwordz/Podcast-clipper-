
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


# ==========================================
# CAPTION SETTINGS
# ==========================================

MIN_WORD_CONFIDENCE = 0.15

MAX_WORDS_PER_CAPTION = 5
MAX_CHARS_PER_CAPTION = 34

MAX_PAUSE_GAP = 0.55

MIN_WORD_DURATION = 0.04
MIN_CAPTION_DURATION = 0.12


# ==========================================
# FFmpeg UTILITIES
# ==========================================

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


# ==========================================
# SUBTITLE TEXT CLEANING
# ==========================================

def escape_ass_text(text):

    text = str(text)

    # Prevent subtitle text from being interpreted
    # as ASS override instructions.
    text = text.replace("\\", "\\\\")
    text = text.replace("{", "\\{")
    text = text.replace("}", "\\}")

    text = text.replace("\n", " ")
    text = text.replace("\r", " ")

    return text.strip()


def clean_word_text(text):

    text = str(text).strip()

    # Remove accidental empty tokens.
    if not text:
        return ""

    # Remove repeated whitespace.
    text = re.sub(r"\s+", " ", text)

    return text


# ==========================================
# WORD EXTRACTION
# ==========================================

def get_clip_words(
    transcript,
    clip_start,
    clip_end,
):

    words = []

    for segment in transcript.get("segments", []):

        for word in segment.get("words", []) or []:

            try:
                start = float(word["start"])
                end = float(word["end"])

                text = clean_word_text(
                    word["word"]
                )

                confidence = float(
                    word.get("probability", 1.0)
                )

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue

            if not text:
                continue

            if end <= clip_start:
                continue

            if start >= clip_end:
                continue

            # Remove extremely unreliable recognition.
            if confidence < MIN_WORD_CONFIDENCE:
                continue

            clipped_start = max(
                start,
                clip_start,
            )

            clipped_end = min(
                end,
                clip_end,
            )

            if clipped_end <= clipped_start:
                continue

            words.append({
                "word": text,

                "start": clipped_start - clip_start,
                "end": clipped_end - clip_start,

                "probability": confidence,
            })

    words.sort(
        key=lambda item: item["start"]
    )

    # Remove duplicate overlapping word detections.
    cleaned = []

    for word in words:

        if cleaned:

            previous = cleaned[-1]

            same_word = (
                word["word"].lower()
                == previous["word"].lower()
            )

            overlap = (
                word["start"] < previous["end"]
            )

            if same_word and overlap:
                continue

        cleaned.append(word)

    return cleaned


# ==========================================
# CAPTION GROUPING
# ==========================================

def is_sentence_end(word):

    text = word["word"].rstrip(
        "\"'”’)]}"
    )

    return text.endswith(
        (".", "?", "!")
    )


def group_words(
    words,
    max_words=MAX_WORDS_PER_CAPTION,
):

    groups = []
    current = []

    for word in words:

        if not current:
            current.append(word)
            continue

        previous = current[-1]

        pause = (
            word["start"] - previous["end"]
        )

        current_text = " ".join(
            item["word"] for item in current
        )

        proposed_length = (
            len(current_text)
            + 1
            + len(word["word"])
        )

        # Break on long silence.
        if pause > MAX_PAUSE_GAP:
            groups.append(current)
            current = [word]
            continue

        # Break after completed sentences.
        if is_sentence_end(previous):
            groups.append(current)
            current = [word]
            continue

        # Keep captions readable.
        if len(current) >= max_words:
            groups.append(current)
            current = [word]
            continue

        if proposed_length > MAX_CHARS_PER_CAPTION:
            groups.append(current)
            current = [word]
            continue

        current.append(word)

    if current:
        groups.append(current)

    return groups


# ==========================================
# KARAOKE SUBTITLE GENERATION
# ==========================================

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
            "No reliable word timestamps found "
            "for this clip."
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

    groups = group_words(words)

    for group in groups:

        start = group[0]["start"]

        end = max(
            group[-1]["end"],
            start + MIN_CAPTION_DURATION,
        )

        karaoke_text = []

        for index, item in enumerate(group):

            word_start = item["start"]
            word_end = item["end"]

            # Make karaoke timing follow actual word starts.
            # This prevents highlighting from drifting during pauses.
            if index + 1 < len(group):

                next_start = group[index + 1]["start"]

                duration_seconds = max(
                    MIN_WORD_DURATION,
                    next_start - word_start,
                )

            else:

                duration_seconds = max(
                    MIN_WORD_DURATION,
                    word_end - word_start,
                )

            duration_cs = max(
                1,
                round(duration_seconds * 100),
            )

            escaped_word = escape_ass_text(
                item["word"]
            )

            karaoke_text.append(
                r"{\kf"
                + str(duration_cs)
                + "}"
                + escaped_word
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

    print(
        f"[Captions] {len(words)} reliable words, "
        f"{len(groups)} caption groups"
    )


# ==========================================
# WINDOWS FILTER PATH HANDLING
# ==========================================

def escape_filter_path(path):

    path = str(
        Path(path).resolve()
    )

    path = path.replace("\\", "/")

    # FFmpeg filter syntax requires escaped drive colon.
    path = path.replace(":", r"\:")

    path = path.replace("'", r"\'")

    return path


# ==========================================
# VIDEO RENDERING
# ==========================================

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
        raise ValueError(
            "Invalid clip timestamps."
        )

    duration = get_video_duration(
        video_path
    )

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

        ass_path = (
            Path(temp_dir) / "captions.ass"
        )

        create_ass_subtitles(
            transcript,
            start,
            end,
            ass_path,
        )

        subtitle_path = escape_filter_path(
            ass_path
        )

        filter_graph = (
            f"[0:v]split=2[bg][fg];"

            # Background: fill portrait canvas.
            f"[bg]"
            f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
            f"boxblur=24:12,"
            f"eq=brightness=-0.12"
            f"[background];"

            # Foreground: preserve complete source frame.
            f"[fg]"
            f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
            f"force_original_aspect_ratio=decrease"
            f"[foreground];"

            # Center the original frame.
            f"[background][foreground]"
            f"overlay=(W-w)/2:(H-h)/2,"
            
            # Burn captions.
            f"subtitles='{subtitle_path}'"
            f"[v]"
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


# ==========================================
# EPISODE CLIP BATCH RENDERING
# ==========================================

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

    with open(
        transcript_path,
        encoding="utf-8",
    ) as file:

        transcript = json.load(file)

    with open(
        clips_path,
        encoding="utf-8",
    ) as file:

        clip_data = json.load(file)

    clips = clip_data.get("clips", [])

    selected = [
        clip
        for clip in clips

        if float(
            clip.get("overall_score", 0)
        ) >= min_score
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

    for index, clip in enumerate(
        selected,
        start=1,
    ):

        title = str(
            clip.get(
                "title",
                f"clip_{index}",
            )
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

        print(
            f"\nRendering clip {index}/{len(selected)}"
        )

        print(f"Title: {title}")

        print(
            f"Score: "
            f"{clip.get('overall_score', 'N/A')}"
        )

        render_clip(
            video_path,
            transcript,
            clip,
            output_path,
        )

        rendered.append(output_path)

        print(f"[OK] Saved: {output_path}")

    return rendered
