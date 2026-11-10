
import argparse
import json
from pathlib import Path

from config import TRANSCRIPT_DIR
from intelligence.clip_finder import find_clips


def analyze_episode(episode_id, target_clips):
    transcript_path = (
        TRANSCRIPT_DIR / f"episode_{episode_id}.json"
    )

    if not transcript_path.exists():
        raise FileNotFoundError(
            f"Transcript not found: {transcript_path}\n"
            "Transcribe the episode first."
        )

    with open(transcript_path, "r", encoding="utf-8") as file:
        transcript = json.load(file)

    print(f"\n[ClipPulse] Analyzing episode #{episode_id}")
    print("[Gemini] Finding compelling moments...")

    clips = find_clips(
        transcript,
        target_clips=target_clips,
    )

    output_path = (
        TRANSCRIPT_DIR / f"episode_{episode_id}_clips.json"
    )

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(
            {"episode_id": episode_id, "clips": clips},
            file,
            indent=4,
            ensure_ascii=False,
        )

    print(f"\nFound {len(clips)} potential clips.")

    for index, clip in enumerate(clips, start=1):
        print(f"\n{'=' * 50}")
        print(f"CLIP #{index}")
        print(f"Title: {clip['title']}")
        print(f"Time: {clip['start']:.2f}s - {clip['end']:.2f}s")
        print(f"Score: {clip.get('overall_score', 'N/A')}")
        print(f"Hook: {clip['hook']}")
        print(f"Reason: {clip.get('reason', '')}")

    print(f"\nSaved results to: {output_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode-id", type=int, required=True)
    parser.add_argument("--clips", type=int, default=5)

    args = parser.parse_args()

    try:
        analyze_episode(args.episode_id, args.clips)
    except Exception as exc:
        print(f"\n[ERROR] {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
