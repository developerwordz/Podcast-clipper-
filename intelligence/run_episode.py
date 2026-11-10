
import argparse
import json

from intelligence.audio_downloader import download_episode_audio
from intelligence.transcriber import transcribe_audio


def process_episode(episode_id):
    print(f"\n[ClipPulse] Processing episode #{episode_id}")

    print("\n[1/2] Downloading audio...")
    audio_path = download_episode_audio(episode_id)
    print(f"[OK] Audio saved: {audio_path}")

    print("\n[2/2] Transcribing audio...")
    transcript = transcribe_audio(audio_path, episode_id)

    print("\n[OK] Transcription complete.")
    print(f"Language: {transcript.get('language')}")
    print(f"Duration: {transcript.get('duration_seconds')} seconds")
    print(f"Transcript length: {len(transcript.get('full_text', ''))} characters")

    print("\nPreview:")
    print(transcript.get("full_text", "")[:1200])

    return transcript


def main():
    parser = argparse.ArgumentParser(
        description="Download and transcribe an approved ClipPulse episode."
    )
    parser.add_argument("--episode-id", type=int, required=True)
    args = parser.parse_args()

    try:
        process_episode(args.episode_id)
    except Exception as exc:
        print(f"\n[ERROR] {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
