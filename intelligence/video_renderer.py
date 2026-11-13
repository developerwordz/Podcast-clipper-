
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
# FFMPEG UTILITIES
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


def has_audio_stream(video_path):

    result = run_command([
        "ffprobe",
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=index",
        "-of", "csv=p=0",
        str(video_path),
    ])

    return bool(result.stdout.strip())


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

    text = text.replace("\\", "\\\\")
    text = text.replace("{", "\\{")
    text = text.replace("}", "\\}")

    text = text.replace("\n", " ")
    text = text.replace("\r", " ")

    return text.strip()


def clean_word_text(text):

    text = str(text).strip()

    if not text:
        return ""

    return re.sub(r"\s+", " ", text)


# ==========================================
# SEGMENT HANDLING
# ==========================================

def get_clip_segments(clip):

    raw_segments = clip.get("segments")

    # Backward compatibility with old single-range clips.
    if not raw_segments:
        raw_segments = [{
            "start": clip["start"],
            "end": clip["end"],
        }]

    segments = []

    for item in raw_segments:

        start = float(item["start"])
        end = float(item["end"])

        if start < 0 or end <= start:
            raise ValueError(
                f"Invalid segment: {start} - {end}"
            )

        segments.append({
            "start": start,
            "end": end,
        })

    if not segments:
        raise ValueError("Clip contains no segments.")

    # Segments must remain in original chronological order.
    segments.sort(key=lambda item: item["start"])

    for index in range(1, len(segments)):

        previous = segments[index - 1]
        current = segments[index]

        if current["start"] < previous["end"]:
            raise ValueError(
                "Clip segments overlap."
            )

    total_duration = sum(
        item["end"] - item["start"]
        for item in segments
    )

    if total_duration <= 0:
        raise ValueError("Invalid total clip duration.")

    return segments


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

            if confidence < MIN_WORD_CONFIDENCE:
                continue

            clipped_start = max(start, clip_start)
            clipped_end = min(end, clip_end)

            if clipped_end <= clipped_start:
                continue

            words.append({
                "word": text,
                "start": clipped_start - clip_start,
                "end": clipped_end - clip_start,
                "probability": confidence,
            })

    words.sort(key=lambda item: item["start"])

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


def get_segmented_clip_words(
    transcript,
    segments,
):

    all_words = []
    timeline_offset = 0.0

    for segment in segments:

        source_start = segment["start"]
        source_end = segment["end"]

        segment_words = get_clip_words(
            transcript,
            source_start,
            source_end,
        )

        # Shift source timestamps onto the joined video timeline.
        for word in segment_words:

            all_words.append({
                "word": word["word"],
                "start": word["start"] + timeline_offset,
                "end": word["end"] + timeline_offset,
                "probability": word["probability"],
            })

        timeline_offset += (
            source_end - source_start
        )

    all_words.sort(
        key=lambda item: item["start"]
    )

    return all_words


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

        if pause > MAX_PAUSE_GAP:
            groups.append(current)
            current = [word]
            continue

        if is_sentence_end(previous):
            groups.append(current)
            current = [word]
            continue

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
    segments=None,
):

    if segments:
        words = get_segmented_clip_words(
            transcript,
            segments,
        )
    else:
        words = get_clip_words(
            transcript,
            clip_start,
            clip_end,
        )

    if not words:
        raise ValueError(
            "No reliable word timestamps found for this clip."
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
    path = path.replace(":", r"\:")
    path = path.replace("'", r"\'")

    return path


# ==========================================
# VIDEO FILTER GRAPH
# ==========================================


def build_filter_graph(
    segments,
    subtitle_path,
    audio_enabled,
):

    filters = []

    segment_count = len(segments)

    if segment_count == 0:
        raise ValueError("No video segments provided.")

    # ======================================
    # VIDEO SEGMENTS
    # ======================================

    if segment_count == 1:

        segment = segments[0]

        filters.append(
            f"[0:v]"
            f"trim=start={segment['start']}:"
            f"end={segment['end']},"
            f"setpts=PTS-STARTPTS"
            f"[joined]"
        )

    else:

        split_outputs = "".join(
            f"[vsource{i}]"
            for i in range(segment_count)
        )

        filters.append(
            f"[0:v]split={segment_count}{split_outputs}"
        )

        video_labels = []

        for index, segment in enumerate(segments):

            output_label = f"v{index}"

            filters.append(
                f"[vsource{index}]"
                f"trim=start={segment['start']}:"
                f"end={segment['end']},"
                f"setpts=PTS-STARTPTS"
                f"[{output_label}]"
            )

            video_labels.append(
                f"[{output_label}]"
            )

        filters.append(
            "".join(video_labels)
            + f"concat=n={segment_count}:v=1:a=0[joined]"
        )

    # ======================================
    # AUDIO SEGMENTS
    # ======================================

    if audio_enabled:

        if segment_count == 1:

            segment = segments[0]

            filters.append(
                f"[0:a]"
                f"atrim=start={segment['start']}:"
                f"end={segment['end']},"
                f"asetpts=PTS-STARTPTS"
                f"[aout]"
            )

        else:

            split_outputs = "".join(
                f"[asource{i}]"
                for i in range(segment_count)
            )

            filters.append(
                f"[0:a]asplit={segment_count}{split_outputs}"
            )

            audio_labels = []

            for index, segment in enumerate(segments):

                output_label = f"a{index}"

                filters.append(
                    f"[asource{index}]"
                    f"atrim=start={segment['start']}:"
                    f"end={segment['end']},"
                    f"asetpts=PTS-STARTPTS"
                    f"[{output_label}]"
                )

                audio_labels.append(
                    f"[{output_label}]"
                )

            filters.append(
                "".join(audio_labels)
                + f"concat=n={segment_count}:v=0:a=1[aout]"
            )

    # ======================================
    # SUBTITLES
    # ======================================

    subtitle_path = escape_filter_path(
        subtitle_path
    )

    # ======================================
    # PORTRAIT COMPOSITION
    # ======================================

    filters.append(
        "[joined]split=2[bg][fg]"
    )

    # Blurred enlarged background.
    filters.append(
        f"[bg]"
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
        f"force_original_aspect_ratio=increase,"
        f"crop={VIDEO_WIDTH}:{VIDEO_HEIGHT},"
        f"boxblur=24:12,"
        f"eq=brightness=-0.12"
        f"[background]"
    )

    # Preserve the complete original frame.
    filters.append(
        f"[fg]"
        f"scale={VIDEO_WIDTH}:{VIDEO_HEIGHT}:"
        f"force_original_aspect_ratio=decrease"
        f"[foreground]"
    )

    # Combine background, foreground and captions.
    filters.append(
        "[background][foreground]"
        "overlay=(W-w)/2:(H-h)/2,"
        f"subtitles='{subtitle_path}'"
        "[vout]"
    )

    return ";".join(filters)
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

    segments = get_clip_segments(clip)

    source_duration = get_video_duration(
        video_path
    )

    for segment in segments:

        if segment["end"] > source_duration:

            raise ValueError(
                f"Segment ends at {segment['end']:.2f}s, "
                f"but video duration is "
                f"{source_duration:.2f}s."
            )

    total_duration = sum(
        item["end"] - item["start"]
        for item in segments
    )

    print(
        f"[Story Compression] "
        f"{len(segments)} segments | "
        f"{total_duration:.1f}s final duration"
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    audio_enabled = has_audio_stream(
        video_path
    )

    with tempfile.TemporaryDirectory() as temp_dir:

        ass_path = (
            Path(temp_dir) / "captions.ass"
        )

        create_ass_subtitles(
            transcript,
            segments[0]["start"],
            segments[-1]["end"],
            ass_path,
            segments=segments,
        )

        filter_graph = build_filter_graph(
            segments,
            ass_path,
            audio_enabled,
        )

        command = [
            "ffmpeg",
            "-y",

            "-i", str(video_path),

            "-filter_complex",
            filter_graph,

            "-map", "[vout]",
        ]

        if audio_enabled:
            command.extend([
                "-map", "[aout]",
                "-c:a", "aac",
                "-b:a", "192k",
            ])

        command.extend([
            "-r", str(VIDEO_FPS),

            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-pix_fmt", "yuv420p",

            "-movflags", "+faststart",

            str(output_path),
        ])

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
