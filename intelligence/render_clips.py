
import argparse

from intelligence.video_renderer import (
    render_episode_clips,
)


def main():

    parser = argparse.ArgumentParser(
        description="ClipPulse video renderer"
    )

    parser.add_argument(
        "--video",
        required=True,
        help="Path to authorized source video",
    )

    parser.add_argument(
        "--transcript",
        required=True,
        help="Path to Whisper transcript JSON",
    )

    parser.add_argument(
        "--clips",
        required=True,
        help="Path to Gemini clip analysis JSON",
    )

    parser.add_argument(
        "--min-score",
        type=float,
        default=0,
    )

    parser.add_argument(
        "--max-clips",
        type=int,
        default=None,
    )

    args = parser.parse_args()

    try:

        results = render_episode_clips(
            video_path=args.video,
            transcript_path=args.transcript,
            clips_path=args.clips,
            min_score=args.min_score,
            max_clips=args.max_clips,
        )

        print(
            f"\nRendering complete: "
            f"{len(results)} videos created."
        )

    except Exception as exc:

        print(f"\n[ERROR] {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
