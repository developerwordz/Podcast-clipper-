
import json

from pathlib import Path
from faster_whisper import WhisperModel

from config import (
    TRANSCRIPT_DIR,
    WHISPER_MODEL,
    WHISPER_DEVICE,
    WHISPER_COMPUTE_TYPE,
)


_model = None


def get_model():
    global _model

    if _model is None:
        print(
            f"Loading Whisper model: {WHISPER_MODEL} "
            f"({WHISPER_DEVICE})"
        )

        _model = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )

    return _model


def transcribe_audio(audio_path, episode_id):
    audio_path = Path(audio_path)

    if not audio_path.exists():
        raise FileNotFoundError(
            f"Audio file not found: {audio_path}"
        )

    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)

    output_path = (
        TRANSCRIPT_DIR / f"episode_{episode_id}.json"
    )

    if output_path.exists():
        print(f"Transcript already exists: {output_path}")

        with open(output_path, "r", encoding="utf-8") as file:
            return json.load(file)

    model = get_model()

    print(f"Transcribing episode {episode_id}...")

    segments, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        vad_filter=True,
        word_timestamps=True,
    )

    transcript_segments = []
    full_text = []

    for segment in segments:
        text = segment.text.strip()

        if not text:
            continue

        transcript_segments.append({
            "start": round(segment.start, 3),
            "end": round(segment.end, 3),
            "text": text,
            "words": [
                {
                    "word": word.word,
                    "start": round(word.start, 3),
                    "end": round(word.end, 3),
                    "probability": word.probability,
                }
                for word in (segment.words or [])
            ],
        })

        full_text.append(text)

    result = {
        "episode_id": episode_id,
        "language": info.language,
        "language_probability": info.language_probability,
        "duration_seconds": info.duration,
        "full_text": " ".join(full_text),
        "segments": transcript_segments,
    }

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(
        f"Transcription complete: "
        f"{len(transcript_segments)} segments"
    )

    print(f"Saved transcript: {output_path}")

    return result
