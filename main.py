import argparse
from datetime import datetime

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
)

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
            f'{row["permission_status"].upper()} | {row["feed_url"]}'
        )

def run_discovery(search_terms, limit):
    discovered = {}
    for term in search_terms:
        print(f"\nSearching Apple Podcasts directory for: {term}")
        try:
            results = search_podcasts(term, limit=limit)
            print(f"  Found {len(results)} podcast listings")
            for source in results:
                discovered[source["feed_url"]] = source
        except Exception as exc:
            print(f"  Search failed: {exc}")

    saved = {}
    for source in discovered.values():
        try:
            source_id = save_source(source)
            saved[source_id] = source
            print(f'  Saved: {source["podcast_name"]}')
        except Exception as exc:
            print(f'  Could not save {source.get("podcast_name")}: {exc}')

    total_new_episodes = 0
    print("\nReading public RSS episode metadata (no media is downloaded)...")
    for source_id, source in saved.items():
        try:
            episodes = fetch_episodes(source["feed_url"], max_episodes=20)
            new_count = save_episodes(source_id, episodes)
            total_new_episodes += new_count
            print(
                f'  {source["podcast_name"]}: '
                f'{len(episodes)} listed, {new_count} new episodes saved'
            )
        except Exception as exc:
            print(f'  RSS failed for {source["podcast_name"]}: {exc}')

    print("\nDISCOVERY COMPLETE")
    print(f"Unique podcasts saved: {len(saved)}")
    print(f"New episode records: {total_new_episodes}")
    print("All sources remain UNREVIEWED until you confirm republishing permission.")

def main():
    parser = argparse.ArgumentParser(
        description="ClipPulse - podcast discovery prototype"
    )
    parser.add_argument(
        "--search",
        action="append",
        help='Search phrase. Repeat this option for multiple phrases.',
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum podcast listings per search phrase (1-50).",
    )
    parser.add_argument(
        "--list-sources",
        action="store_true",
        help="List saved podcast sources and permission status.",
    )
    parser.add_argument(
        "--approve-source",
        type=int,
        metavar="ID",
        help="Mark a source approved only if you have republishing permission.",
    )
    parser.add_argument(
        "--permission-note",
        default="User confirmed permission to republish.",
        help="Record the basis for the permission approval.",
    )
    args = parser.parse_args()

    initialize_database()

    if args.list_sources:
        show_sources()
        return

    if args.approve_source is not None:
        if approve_source(args.approve_source, args.permission_note):
            print(
                f"Source {args.approve_source} marked APPROVED. "
                "Keep evidence of the creator's permission."
            )
        else:
            print(f"Source ID {args.approve_source} was not found.")
        return

    terms = args.search or DEFAULT_SEARCHES
    run_discovery(terms, max(1, min(args.limit, 50)))
    show_sources()

if __name__ == "__main__":
    main()
