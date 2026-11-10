
import argparse
import json

import requests

from config import DEFAULT_SEARCHES
from database.db import initialize_database
from discovery.podcast_search import search_podcasts
from discovery.rss_reader import fetch_episodes

from discovery.source_manager import (
    approve_source,
    get_sources,
    list_sources,
    save_episodes,
    save_source,
    get_unranked_episodes,
    save_episode_rank,
    get_ranked_episodes,
    count_episodes,
    count_ranked_episodes,
)

from intelligence.episode_ranker import rank_episode


def show_sources():
    rows = list_sources()

    if not rows:
        print("No podcast sources saved yet.")
        return

    print("\nSAVED PODCAST SOURCES")
    print("-" * 100)

    for row in rows:
        print(
            f'[{row["id"]:>3}] {row["podcast_name"]} | '
            f'{row["permission_status"].upper()} | '
            f'{row["feed_url"]}'
        )


def index_saved_sources(sources):
    total_new_episodes = 0
    succeeded = 0
    failed = 0

    print(
        "\nReading public RSS episode metadata "
        "(no media is downloaded)..."
    )

    print(f"Feeds queued: {len(sources)}")

    try:
        for index, source in enumerate(sources, start=1):

            name = source["podcast_name"]

            print(f"\n[{index}/{len(sources)}] {name}")

            try:
                episodes = fetch_episodes(
                    source["feed_url"],
                    max_episodes=20
                )

                new_count = save_episodes(
                    source["id"],
                    episodes
                )

                total_new_episodes += new_count
                succeeded += 1

                print(
                    f"  OK: {len(episodes)} episodes read, "
                    f"{new_count} new records saved"
                )

            except KeyboardInterrupt:
                print(
                    "\nInterrupted by user. "
                    "Keeping everything saved so far."
                )
                break

            except (
                requests.RequestException,
                TimeoutError
            ) as exc:

                failed += 1
                print(f"  SKIPPED: network/timeout error: {exc}")

            except Exception as exc:

                failed += 1
                print(f"  SKIPPED: feed error: {exc}")

    except KeyboardInterrupt:
        print(
            "\nInterrupted by user. "
            "Keeping everything saved so far."
        )

    print("\nRSS INDEXING SUMMARY")
    print(f"Feeds processed successfully: {succeeded}")
    print(f"Feeds skipped due to errors: {failed}")
    print(f"New episode records saved: {total_new_episodes}")
    print("You can safely run --refresh-saved again later.")


def run_discovery(search_terms, limit):
    discovered = {}

    for term in search_terms:

        print(
            f"\nSearching Apple Podcasts directory for: {term}"
        )

        try:
            results = search_podcasts(
                term,
                limit=limit
            )

            print(f"  Found {len(results)} podcast listings")

            for source in results:
                discovered[source["feed_url"]] = source

        except KeyboardInterrupt:
            print(
                "\nSearch interrupted. "
                "Continuing with results already found."
            )
            break

        except Exception as exc:
            print(f"  Search failed: {exc}")

    saved_count = 0

    for source in discovered.values():

        try:
            save_source(source)
            saved_count += 1

            print(f'  Saved: {source["podcast_name"]}')

        except Exception as exc:
            print(
                f'  Could not save '
                f'{source.get("podcast_name")}: {exc}'
            )

    print(f"\nUnique podcast feeds discovered: {len(discovered)}")
    print(f"Podcast sources saved/updated: {saved_count}")

    index_saved_sources(get_sources())

    print(
        "\nAll sources remain UNREVIEWED until "
        "you confirm republishing permission."
    )


# -----------------------------
# EPISODE INTELLIGENCE
# -----------------------------

def format_duration(seconds):
    if seconds is None:
        return "Unknown"

    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "Unknown"

    if seconds < 0:
        return "Unknown"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    if hours:
        return f"{hours}h {minutes}m"

    return f"{minutes}m"


def rank_pending_episodes():
    pending = get_unranked_episodes()

    total = count_episodes()

    print("\nCLIPPULSE EPISODE INTELLIGENCE")
    print("=" * 65)

    print(f"Total episodes in database: {total}")
    print(f"Already ranked: {count_ranked_episodes()}")
    print(f"Waiting for ranking: {len(pending)}")

    if not pending:
        print("\nAll saved episodes have already been ranked.")
        return

    ranked_count = 0

    print("\nAnalysing episodes...\n")

    for index, episode in enumerate(pending, start=1):

        try:
            result = rank_episode(episode)

            save_episode_rank(
                episode["id"],
                result
            )

            ranked_count += 1

            print(
                f"[{index}/{len(pending)}] "
                f'{episode["title"][:65]} '
                f'-> {result["score"]}/100'
            )

        except KeyboardInterrupt:
            print(
                "\nRanking interrupted. "
                "Completed rankings have been saved."
            )
            break

        except Exception as exc:
            print(
                f'[ERROR] Episode {episode["id"]}: {exc}'
            )

    print("\nRANKING SUMMARY")
    print("-" * 65)
    print(f"Successfully ranked: {ranked_count}")
    print(f"Total ranked in database: {count_ranked_episodes()}")


def show_top_episodes(limit=25, minimum_score=0):

    episodes = get_ranked_episodes(
        limit=limit,
        minimum_score=minimum_score
    )

    print("\nTOP PODCAST EPISODES")
    print("=" * 100)

    if not episodes:
        print("No ranked episodes found.")
        print("Run: python main.py --rank-episodes")
        return

    for index, episode in enumerate(episodes, start=1):

        score = episode["rank_score"]
        tier = episode["rank_tier"]

        print("\n" + "=" * 100)

        print(
            f'#{index} | {score}/100 | {tier}'
        )

        print(f'Podcast: {episode["podcast_name"]}')
        print(f'Episode: {episode["title"]}')

        print(
            f'Duration: '
            f'{format_duration(episode["duration_seconds"])}'
        )

        print(
            f'Published: '
            f'{episode["published_at"] or "Unknown"}'
        )

        print(
            f'Permission: '
            f'{episode["permission_status"].upper()}'
        )

        print(
            f'Audio available: '
            f'{"YES" if episode["audio_url"] else "NO"}'
        )

        reasons = json.loads(
            episode["rank_reasons"] or "[]"
        )

        print("Why it ranked:")

        for reason in reasons:
            print(f"  - {reason}")

        print(f'Episode URL: {episode["episode_url"] or "N/A"}')

        print(
            f'Audio URL: '
            f'{episode["audio_url"] or "N/A"}'
        )

    print("\n" + "=" * 100)
    print(
        "Reminder: A HIGH relevance score does not mean "
        "the episode is cleared for republication."
    )


def run_episode_intelligence(limit, minimum_score):

    rank_pending_episodes()

    show_top_episodes(
        limit=limit,
        minimum_score=minimum_score
    )


# -----------------------------
# MAIN
# -----------------------------

def main():

    parser = argparse.ArgumentParser(
        description="ClipPulse - Podcast discovery and intelligence"
    )

    parser.add_argument(
        "--search",
        action="append",
        help="Search phrase. Repeat for multiple phrases."
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum podcast listings per search phrase (1-50)."
    )

    parser.add_argument(
        "--list-sources",
        action="store_true",
        help="List saved podcast sources and permission status."
    )

    parser.add_argument(
        "--refresh-saved",
        action="store_true",
        help="Refresh RSS metadata for saved sources."
    )

    parser.add_argument(
        "--approve-source",
        type=int,
        metavar="ID",
        help="Approve a source only if you have republishing permission."
    )

    parser.add_argument(
        "--permission-note",
        default="User confirmed permission to republish.",
        help="Record the basis for permission approval."
    )

    parser.add_argument(
        "--rank-episodes",
        action="store_true",
        help="Rank unranked episodes and display top candidates."
    )

    parser.add_argument(
        "--top",
        type=int,
        default=25,
        help="Number of top episodes to display."
    )

    parser.add_argument(
        "--min-score",
        type=int,
        default=0,
        help="Only display episodes with at least this score (0-100)."
    )

    args = parser.parse_args()

    initialize_database()

    if args.top < 1:
        parser.error("--top must be at least 1")

    if not 0 <= args.min_score <= 100:
        parser.error("--min-score must be between 0 and 100")

    if args.list_sources:
        show_sources()
        return

    if args.approve_source is not None:

        if approve_source(
            args.approve_source,
            args.permission_note
        ):

            print(
                f"Source {args.approve_source} marked APPROVED. "
                "Keep evidence of the creator's permission."
            )

        else:
            print(
                f"Source ID {args.approve_source} was not found."
            )

        return

    if args.rank_episodes:

        run_episode_intelligence(
            args.top,
            args.min_score
        )

        return

    if args.refresh_saved:
        index_saved_sources(get_sources())
        return

    terms = args.search or DEFAULT_SEARCHES

    run_discovery(
        terms,
        max(1, min(args.limit, 50))
    )

    show_sources()


if __name__ == "__main__":
    main()
