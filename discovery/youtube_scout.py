
import ast
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone

import requests

from config import YOUTUBE_API_KEY, DEFAULT_YOUTUBE_SEARCHES
from database.db import get_connection


YOUTUBE_API = "https://www.googleapis.com/youtube/v3"

MAX_VIDEOS_PER_CHANNEL = 3

# Curiosity-first search strategy. Keep this list compact because each
# YouTube search.list request consumes API quota.
CURIOSITY_SEARCHES = [
    "podcast unbelievable true story full episode",
    "podcast shocking confession full interview",
    "podcast craziest thing that ever happened full episode",
    "podcast strange experience unbelievable story",
    "podcast biggest mistake disaster story interview",
    "podcast controversial opinion heated debate full episode",
    "podcast secret revelation nobody knows full interview",
    "podcast near death experience survival story interview",
    "founder business failure collapse story podcast",
    "celebrity awkward embarrassing story podcast interview",
    "wild coincidence unbelievable encounter podcast",
    "people tell their most insane story podcast",
]

# Metadata can only estimate story potential. Gemini validates the actual
# spoken moment later, using the transcript.
CURIOSITY_TERMS = {
    "unbelievable", "insane", "craziest", "shocking", "secret",
    "confession", "exposed", "truth", "nobody", "never",
    "unexpected", "mystery", "strange", "weird", "bizarre",
    "disaster", "collapse", "failure", "mistake", "regret",
    "embarrassing", "awkward", "controversial", "wild",
    "survived", "survival", "terrifying", "crazy", "happened",
}

STORY_TERMS = {
    "story", "happened", "experience", "moment", "day",
    "when", "almost", "once", "met", "found", "lost",
    "survived", "discovered", "confession", "regret",
    "incident", "encounter", "night", "first", "last",
}

EMOTION_TERMS = {
    "fear", "terrifying", "shocking", "angry", "crying",
    "regret", "heartbreaking", "humiliated", "betrayed",
    "insulted", "panic", "nightmare", "trauma", "revenge",
    "love", "hate", "jealous", "fired", "cheated",
}

ENTERTAINMENT_TERMS = {
    "funniest", "craziest", "wild", "awkward", "embarrassing",
    "ridiculous", "insane", "prank", "fight", "argument",
    "roast", "unfiltered", "drunk", "dating", "caught",
    "confronted", "reaction", "hilarious",
}

SURPRISE_TERMS = {
    "unexpected", "plot", "twist", "secret", "revealed",
    "turns", "turned", "instead", "nobody", "never",
    "suddenly", "shocking", "discovered", "exposed",
    "truth", "coincidence", "impossible", "against",
}

PODCAST_CHANNEL_HINTS = [
    "diary of a ceo",
    "raj shamani",
    "powerfuljre",
    "lex fridman",
    "huberman",
    "beerbiceps",
    "rich roll",
    "star talk",
    "startalk",
    "modern wisdom",
    "people by wtf",
    "nikhil kamath",
    "school of greatness",
    "triggernometry",
    "raw talks",
    "rawtalks",
    "the ranveer show",
    "think school",
    "the seen and the unseen",
    "unfiltered by samdish",
]

PODCAST_TERMS = [
    "podcast",
    "full episode",
    "episode #",
    "episode no",
    "ep.",
    "in conversation with",
    "conversation with",
    "interview with",
    "long form interview",
    "long-form interview",
    "sits down with",
    "talks with",
    "guest appearance",
    "full interview",
    "full conversation",
]

INTERVIEW_TERMS = [
    "interview",
    "conversation",
    "discuss",
    "talks about",
    "talks with",
    "explains",
    "guest",
    "hosted by",
]

NON_PODCAST_TERMS = [
    "trailer",
    "teaser",
    "official music video",
    "music video",
    "movie clip",
    "film trailer",
    "news bulletin",
    "breaking news",
    "news report",
    "documentary",
    "full documentary",
    "short film",
    "reaction compilation",
    "highlights compilation",
    "explained in",
    "last week tonight",
    "middle ground",
]


STOP_WORDS = {
    "the", "and", "for", "with", "from", "that", "this",
    "what", "when", "where", "why", "how", "who",
    "are", "was", "were", "will", "would", "could",
    "should", "about", "into", "your", "their", "have",
    "has", "had", "you", "they", "them", "his", "her",
    "its", "our", "not", "but", "all", "can", "full",
    "episode", "episodes", "podcast", "interview",
    "best", "new", "latest",
}

# Preserve meaningful short technical terms.
SHORT_TERMS = {
    "ai", "ml", "it", "uk", "us", "vr", "ar",
    "5g", "3d", "ceo", "cto", "cfo", "ipo",
    "gpu", "cpu", "llm", "agi",
}

# Edit these weights to prioritize the topics ClipPulse should discover.
TOPIC_PRIORITIES = {
    "ai": 1.15,
    "artificial intelligence": 1.15,
    "technology": 1.05,
    "business": 1.00,
    "entrepreneurship": 1.00,
    "science": 1.00,
}


def tokenize(text):

    words = re.findall(
        r"[a-zA-Z0-9]+",
        (text or "").lower()
    )

    return {
        word
        for word in words
        if (
            (len(word) > 2 or word in SHORT_TERMS)
            and word not in STOP_WORDS
        )
    }



class YouTubeAPIError(Exception):
    pass


# ==================================================
# GENERAL HELPERS
# ==================================================




def parse_duration(duration):

    if not duration:
        return 0

    match = re.fullmatch(
        r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        duration
    )

    if not match:
        return 0

    days, hours, minutes, seconds = [
        int(value or 0)
        for value in match.groups()
    ]

    return (
        days * 86400
        + hours * 3600
        + minutes * 60
        + seconds
    )


def parse_reasons(value):

    if not value:
        return {}

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        try:
            result = ast.literal_eval(value)
            return result if isinstance(result, dict) else {}
        except (ValueError, SyntaxError):
            return {}


def parse_timestamp(value):

    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed

    except (ValueError, TypeError, AttributeError):
        return None


# ==================================================
# YOUTUBE API
# ==================================================

def youtube_request(endpoint, params):

    if not YOUTUBE_API_KEY:
        raise YouTubeAPIError(
            "YOUTUBE_API_KEY is missing from .env"
        )

    response = requests.get(
        f"{YOUTUBE_API}/{endpoint}",
        params={
            **params,
            "key": YOUTUBE_API_KEY,
        },
        timeout=30,
    )

    if not response.ok:

        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = response.text[:300]

        raise YouTubeAPIError(
            f"HTTP {response.status_code}: {message}"
        )

    return response.json()


def search_youtube(query, limit=25):

    data = youtube_request(
        "search",
        {
            "part": "snippet",
            "q": query,
            "type": "video",
            "videoDuration": "long",
            "order": "viewCount",
            "maxResults": max(1, min(limit, 50)),
        }
    )

    results = []

    for item in data.get("items", []):

        video_id = item.get("id", {}).get("videoId")
        snippet = item.get("snippet", {})

        if not video_id:
            continue

        results.append({
            "youtube_video_id": video_id,
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "channel_id": snippet.get("channelId", ""),
            "channel_title": snippet.get("channelTitle", ""),
            "published_at": snippet.get("publishedAt"),
            "thumbnail_url": (
                snippet.get("thumbnails", {})
                .get("high", {})
                .get("url")
            ),
        })

    return results


def fetch_video_details(video_ids):

    results = []

    for start in range(0, len(video_ids), 50):

        batch = video_ids[start:start + 50]

        data = youtube_request(
            "videos",
            {
                "part": "snippet,contentDetails,statistics",
                "id": ",".join(batch),
                "maxResults": 50,
            }
        )

        results.extend(data.get("items", []))

    return results


# ==================================================
# PODCAST CLASSIFICATION
# ==================================================

def classify_video(title, description, channel):

    title_lower = (title or "").lower()
    description_lower = (description or "").lower()
    channel_lower = (channel or "").lower()

    combined = (
        title_lower + " " + description_lower
    )

    # Strong evidence of a non-podcast format.
    for term in NON_PODCAST_TERMS:

        if term in title_lower:
            return {
                "category": "non_podcast",
                "score": 0,
                "confidence": "high",
                "reason": f"Non-podcast title marker: {term}",
            }

    # Known podcast channels are strong evidence.
    for hint in PODCAST_CHANNEL_HINTS:

        if hint in channel_lower:

            return {
                "category": "podcast",
                "score": 100,
                "confidence": "high",
                "reason": f"Recognized podcast channel: {hint}",
            }

    score = 0
    reasons = []

    for term in PODCAST_TERMS:

        if term in title_lower:
            score += 35
            reasons.append(f"Title contains '{term}'")
            break

    for term in INTERVIEW_TERMS:

        if term in title_lower:
            score += 20
            reasons.append(f"Interview marker: '{term}'")
            break

    for term in PODCAST_TERMS:

        if term in description_lower:
            score += 20
            reasons.append("Podcast/interview marker in description")
            break

    if "host" in description_lower and "guest" in description_lower:
        score += 10
        reasons.append("Host and guest description")

    if re.search(r"\b(ep|episode)\s*#?\s*\d+\b", title_lower):
        score += 20
        reasons.append("Episode numbering")

    score = min(score, 100)

    if score >= 60:
        category = "podcast"
        confidence = "high"

    elif score >= 30:
        category = "probable_podcast"
        confidence = "medium"

    else:
        category = "uncertain"
        confidence = "low"

    return {
        "category": category,
        "score": score,
        "confidence": confidence,
        "reason": "; ".join(reasons) or "Insufficient format evidence",
    }


# ==================================================
# RELEVANCE
# ==================================================


TOPIC_ALIASES = {
    "ai": [
        "ai",
        "artificial intelligence",
        "machine learning",
        "generative ai",
        "large language model",
        "llm",
    ],
    "technology": [
        "technology",
        "tech",
        "software",
        "computer",
        "semiconductor",
        "robotics",
    ],
    "business": [
        "business",
        "company",
        "companies",
        "startup",
        "startups",
        "entrepreneur",
        "entrepreneurship",
        "founder",
        "founders",
        "billionaire",
    ],
    "science": [
        "science",
        "scientist",
        "scientific",
        "physics",
        "biology",
        "chemistry",
        "neuroscience",
        "research",
    ],
    "entrepreneurship": [
        "entrepreneur",
        "entrepreneurship",
        "founder",
        "founders",
        "startup",
        "startups",
        "business",
    ],
}


def phrase_present(phrase, text):

    return bool(
        re.search(
            r"(?<!\w)" + re.escape(phrase.lower()) + r"(?!\w)",
            (text or "").lower()
        )
    )


def calculate_relevance(title, description, queries):

    if isinstance(queries, str):
        queries = [
            item.strip()
            for item in queries.split(",")
            if item.strip()
        ]

    if not queries:
        return 0

    title_lower = (title or "").lower()
    description_lower = (description or "").lower()

    title_words = tokenize(title)
    description_words = tokenize(description)

    best_score = 0

    for query in queries:

        query_lower = query.lower()
        query_words = tokenize(query)

        if not query_words:
            continue

        # Basic keyword matching.
        title_matches = len(
            query_words & title_words
        )

        description_matches = len(
            query_words & description_words
        )

        title_score = (
            title_matches / len(query_words)
        ) * 75

        description_score = (
            description_matches / len(query_words)
        ) * 25

        score = title_score + description_score

        # Topic aliases help recognize related terminology.
        for topic, aliases in TOPIC_ALIASES.items():

            if not (
                topic in query_lower
                or any(
                    phrase_present(alias, query_lower)
                    for alias in aliases
                )
            ):
                continue

            alias_match = any(
                phrase_present(alias, title_lower)
                or phrase_present(alias, description_lower)
                for alias in aliases
            )

            if alias_match:
                score = max(score, 85)

        # Apply configurable topic priority.
        priority = 1.0

        for topic, weight in TOPIC_PRIORITIES.items():

            if phrase_present(topic, query_lower):
                priority = max(priority, weight)

        score *= priority

        best_score = max(best_score, score)

    return round(min(100, best_score), 2)


# ==================================================
# ENGAGEMENT AND RECENCY
# ==================================================

def calculate_engagement_rate(views, likes, comments):

    if views <= 0:
        return 0

    return ((likes + comments) / views) * 100


def calculate_engagement_score(rate):

    # Saturates rather than letting extreme engagement
    # completely dominate the ranking.
    return round(
        min(100, rate * 4),
        2
    )


def calculate_recency_score(published_at):

    published = parse_timestamp(published_at)

    if not published:
        return 0

    age_days = max(
        0,
        (
            datetime.now(timezone.utc) - published
        ).total_seconds() / 86400
    )

    return round(
        100 * math.exp(-age_days / 180),
        2
    )


# ==================================================
# HISTORICAL VELOCITY
# ==================================================

def calculate_velocity_from_snapshots(
    older_views,
    older_timestamp,
    newer_views,
    newer_timestamp,
):

    older_time = parse_timestamp(older_timestamp)
    newer_time = parse_timestamp(newer_timestamp)

    if not older_time or not newer_time:
        return None

    elapsed_days = (
        newer_time - older_time
    ).total_seconds() / 86400

    if elapsed_days <= 0:
        return None

    gained = max(
        0,
        newer_views - older_views
    )

    return round(gained / elapsed_days, 2)


def get_velocity_from_history(
    video_id,
    current_views=None,
    compare_current=False,
):

    with get_connection() as conn:

        rows = conn.execute(
            """
            SELECT view_count, captured_at
            FROM youtube_stats_history
            WHERE youtube_video_id = ?
            ORDER BY captured_at DESC, id DESC
            LIMIT 2
            """,
            (video_id,)
        ).fetchall()

    if compare_current:

        # Compare current API statistics against the
        # most recent previously stored snapshot.
        if not rows or current_views is None:
            return None

        return calculate_velocity_from_snapshots(
            rows[0]["view_count"],
            rows[0]["captured_at"],
            current_views,
            datetime.now(timezone.utc).isoformat(),
        )

    # Rescoring uses the two most recent historical snapshots.
    if len(rows) < 2:
        return None

    return calculate_velocity_from_snapshots(
        rows[1]["view_count"],
        rows[1]["captured_at"],
        rows[0]["view_count"],
        rows[0]["captured_at"],
    )



def calculate_momentum_score(views_per_day):

    if views_per_day is None:
        return None

    return round(
        min(
            100,
            (math.log10(views_per_day + 1) / 5) * 100
        ),
        2
    )


# ==================================================
# COMPOSITE RANKING
# ==================================================


def _keyword_score(text, terms, saturation=4):
    """Convert distinct title/description keyword hits into a 0-100 proxy."""
    words = set(re.findall(r"[a-zA-Z0-9']+", (text or "").lower()))
    hits = words & terms
    return round(min(100, (len(hits) / saturation) * 100), 2)


def calculate_curiosity_scores(title, description):
    """Estimate entertainment/story potential from public metadata only."""
    text = f"{title or ''} {description or ''}"

    return {
        "curiosity": _keyword_score(text, CURIOSITY_TERMS, saturation=4),
        "storytelling": _keyword_score(text, STORY_TERMS, saturation=4),
        "emotion": _keyword_score(text, EMOTION_TERMS, saturation=3),
        "entertainment": _keyword_score(text, ENTERTAINMENT_TERMS, saturation=3),
        "surprise": _keyword_score(text, SURPRISE_TERMS, saturation=3),
    }


def calculate_final_score(
    curiosity,
    storytelling,
    emotion,
    entertainment,
    surprise,
    traction,
):
    """Scout V4 weighted score: curiosity-first, not education-first."""
    score = (
        curiosity * 0.25
        + storytelling * 0.25
        + emotion * 0.15
        + entertainment * 0.15
        + surprise * 0.10
        + traction * 0.10
    )
    return round(score, 2)


def evaluate_video(video, views_per_day=None):

    classification = classify_video(
        video["title"],
        video["description"],
        video["channel_title"],
    )

    # Keep the existing relevance calculation for diagnostics, but do not
    # let broad AI/business keywords dominate the V4 curiosity score.
    relevance = calculate_relevance(
        video["title"],
        video["description"],
        video.get("discovered_query", ""),
    )

    engagement_rate = calculate_engagement_rate(
        video["view_count"],
        video["like_count"],
        video["comment_count"],
    )
    engagement = calculate_engagement_score(engagement_rate)
    recency = calculate_recency_score(video["published_at"])
    momentum = calculate_momentum_score(views_per_day)

    # Momentum is unavailable for a newly discovered video. Use a neutral
    # value rather than penalizing it or allowing it to dominate later.
    momentum_for_traction = momentum if momentum is not None else 50
    traction = round(
        engagement * 0.50
        + recency * 0.25
        + momentum_for_traction * 0.25,
        2,
    )

    curiosity_scores = calculate_curiosity_scores(
        video["title"],
        video["description"],
    )

    final_score = calculate_final_score(
        curiosity_scores["curiosity"],
        curiosity_scores["storytelling"],
        curiosity_scores["emotion"],
        curiosity_scores["entertainment"],
        curiosity_scores["surprise"],
        traction,
    )

    reasons = {
        "scout_version": 4,
        "category": classification["category"],
        "confidence": classification["confidence"],
        "classification_reason": classification["reason"],
        "relevance": relevance,
        **curiosity_scores,
        "traction": traction,
        "engagement": engagement,
        "engagement_rate": round(engagement_rate, 3),
        "recency": recency,
        "momentum": momentum,
        "views_per_day": views_per_day,
        "score": final_score,
        "scoring_note": "Metadata-based estimate; transcript review determines actual story quality.",
    }

    return final_score, reasons


# ==================================================
# DATABASE STORAGE
# ==================================================

def save_youtube_video(video):

    with get_connection() as conn:

        conn.execute(
            """
            INSERT INTO youtube_videos (
                youtube_video_id,
                title,
                description,
                channel_id,
                channel_title,
                published_at,
                duration_seconds,
                video_url,
                thumbnail_url,
                view_count,
                like_count,
                comment_count,
                traction_score,
                traction_reasons,
                discovered_query,
                last_checked_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                CURRENT_TIMESTAMP
            )
            ON CONFLICT(youtube_video_id) DO UPDATE SET
                title=excluded.title,
                description=excluded.description,
                channel_id=excluded.channel_id,
                channel_title=excluded.channel_title,
                published_at=excluded.published_at,
                duration_seconds=excluded.duration_seconds,
                video_url=excluded.video_url,
                thumbnail_url=excluded.thumbnail_url,
                view_count=excluded.view_count,
                like_count=excluded.like_count,
                comment_count=excluded.comment_count,
                traction_score=excluded.traction_score,
                traction_reasons=excluded.traction_reasons,
                discovered_query=excluded.discovered_query,
                last_checked_at=CURRENT_TIMESTAMP
            """,
            (
                video["youtube_video_id"],
                video["title"],
                video["description"],
                video["channel_id"],
                video["channel_title"],
                video["published_at"],
                video["duration_seconds"],
                video["video_url"],
                video["thumbnail_url"],
                video["view_count"],
                video["like_count"],
                video["comment_count"],
                video["traction_score"],
                json.dumps(video["traction_reasons"]),
                video["discovered_query"],
            )
        )


def save_statistics_snapshot(video):

    with get_connection() as conn:

        conn.execute(
            """
            INSERT INTO youtube_stats_history (
                youtube_video_id,
                view_count,
                like_count,
                comment_count
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                video["youtube_video_id"],
                video["view_count"],
                video["like_count"],
                video["comment_count"],
            )
        )


def count_youtube_videos():

    with get_connection() as conn:

        row = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM youtube_videos
            """
        ).fetchone()

        return row["total"]


def rescore_youtube_videos():

    print("\nCLIPPULSE — RESCORING SAVED YOUTUBE VIDEOS")
    print("=" * 65)

    with get_connection() as conn:

        videos = conn.execute(
            """
            SELECT *
            FROM youtube_videos
            """
        ).fetchall()

    updated = 0

    for row in videos:

        video = dict(row)

        views_per_day = get_velocity_from_history(
            video["youtube_video_id"]
        )

        score, reasons = evaluate_video(
            video,
            views_per_day
        )

        video["traction_score"] = score
        video["traction_reasons"] = reasons

        with get_connection() as conn:

            conn.execute(
                """
                UPDATE youtube_videos
                SET traction_score = ?,
                    traction_reasons = ?
                WHERE youtube_video_id = ?
                """,
                (
                    score,
                    json.dumps(reasons),
                    video["youtube_video_id"],
                )
            )

        updated += 1

    print(f"Videos rescored: {updated}")
    print("No YouTube API requests were made.")

    show_top_youtube_videos(limit=25)


# ==================================================
# RANKED SHORTLIST
# ==================================================

def get_top_youtube_videos(limit=25, minimum_score=0):

    with get_connection() as conn:

        return conn.execute(
            """
            SELECT *
            FROM youtube_videos
            WHERE traction_score >= ?
            ORDER BY traction_score DESC
            LIMIT ?
            """,
            (minimum_score, limit * 5)
        ).fetchall()


def show_top_youtube_videos(
    limit=25,
    minimum_score=0,
    diverse=True,
):

    videos = get_top_youtube_videos(
        limit=limit,
        minimum_score=minimum_score,
    )

    selected = []
    channel_counts = Counter()

    for video in videos:

        reasons = parse_reasons(
            video["traction_reasons"]
        )

        category = reasons.get(
            "category",
            "uncertain"
        )

        # Exclude confidently identified non-podcast formats.
        if category == "non_podcast":
            continue

        channel = (
            video["channel_id"]
            or video["channel_title"]
            or "unknown"
        )

        if (
            diverse
            and channel_counts[channel] >= MAX_VIDEOS_PER_CHANNEL
        ):
            continue

        selected.append((video, reasons))
        channel_counts[channel] += 1

        if len(selected) >= limit:
            break

    print("\nTOP YOUTUBE DISCOVERIES — SCOUT V4 | CURIOSITY-FIRST")
    print("=" * 100)

    if not selected:
        print("No suitable candidates found.")
        return

    for index, (video, reasons) in enumerate(selected, start=1):

        duration = video["duration_seconds"] or 0
        hours = duration // 3600
        minutes = (duration % 3600) // 60

        duration_text = (
            f"{hours}h {minutes}m"
            if hours else f"{minutes}m"
        )

        print("\n" + "-" * 100)

        print(
            f'#{index} | Score: {video["traction_score"]}/100'
        )

        print(f'Title: {video["title"]}')
        print(f'Channel: {video["channel_title"]}')
        print(f'Format: {reasons.get("category", "uncertain")}')
        print(f'Format confidence: {reasons.get("confidence", "unknown")}')
        print(f'Duration: {duration_text}')
        print(f'Published: {video["published_at"]}')
        print(f'Views: {video["view_count"]:,}')
        print(f'Likes: {video["like_count"]:,}')
        print(f'Comments: {video["comment_count"]:,}')

        print(f'Curiosity: {reasons.get("curiosity", 0)}/100')
        print(f'Storytelling proxy: {reasons.get("storytelling", 0)}/100')
        print(f'Emotion proxy: {reasons.get("emotion", 0)}/100')
        print(f'Entertainment proxy: {reasons.get("entertainment", 0)}/100')
        print(f'Surprise proxy: {reasons.get("surprise", 0)}/100')
        print(f'Traction: {reasons.get("traction", 0)}/100')
        print(f'Format confidence: {reasons.get("confidence", "unknown")}')

        momentum = reasons.get("momentum")

        print(
            f'Momentum: {momentum if momentum is not None else "Awaiting history"}'
        )

        print(
            f'Views/day: {reasons.get("views_per_day") or "Awaiting history"}'
        )

        print(
            f'Classification: {reasons.get("classification_reason", "")}'
        )

        print(f'Found through: {video["discovered_query"]}')
        print(f'URL: {video["video_url"]}')

    print("\n" + "=" * 100)
    print(
        "V4 scores estimate curiosity/story potential from public metadata. "
        "They do not verify the spoken story, audience retention, or "
        "permission to republish."
    )


# ==================================================
# MAIN SCOUT
# ==================================================

def run_youtube_scout(
    search_terms=None,
    results_per_query=25,
    minimum_duration_minutes=20,
    top=25,
):

    search_terms = search_terms or CURIOSITY_SEARCHES

    print("\nCLIPPULSE YOUTUBE SCOUT V4 — CURIOSITY-FIRST")
    print("=" * 65)

    discovered = {}

    # Search.
    for index, query in enumerate(search_terms, start=1):

        print(
            f"\n[{index}/{len(search_terms)}] Searching: {query}"
        )

        try:

            results = search_youtube(
                query,
                results_per_query
            )

            for result in results:

                video_id = result["youtube_video_id"]

                if video_id not in discovered:

                    discovered[video_id] = result
                    discovered[video_id]["queries"] = []

                if query not in discovered[video_id]["queries"]:
                    discovered[video_id]["queries"].append(query)

            print(f"Found {len(results)} results")

        except (
            YouTubeAPIError,
            requests.RequestException
        ) as exc:

            print(f"Search error: {exc}")

            if (
                "quota" in str(exc).lower()
                or "403" in str(exc)
            ):
                print("Stopping search due to API access/quota error.")
                break

    video_ids = list(discovered.keys())

    print(f"\nUnique videos: {len(video_ids)}")

    if not video_ids:
        print("No videos discovered.")
        return

    # Fetch public statistics.
    try:

        details = fetch_video_details(video_ids)

    except (
        YouTubeAPIError,
        requests.RequestException
    ) as exc:

        print(f"Could not fetch statistics: {exc}")
        return

    saved = 0
    skipped = 0

    for item in details:

        video_id = item.get("id")
        candidate = discovered.get(video_id)

        if not candidate:
            continue

        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        content = item.get("contentDetails", {})

        duration = parse_duration(
            content.get("duration")
        )

        if duration < minimum_duration_minutes * 60:
            skipped += 1
            continue

        video = {
            "youtube_video_id": video_id,
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "channel_id": snippet.get("channelId", ""),
            "channel_title": snippet.get("channelTitle", ""),
            "published_at": snippet.get("publishedAt"),
            "duration_seconds": duration,
            "video_url": (
                f"https://www.youtube.com/watch?v={video_id}"
            ),
            "thumbnail_url": (
                snippet.get("thumbnails", {})
                .get("high", {})
                .get("url")
            ),
            "view_count": int(
                statistics.get("viewCount", 0)
            ),
            "like_count": int(
                statistics.get("likeCount", 0)
            ),
            "comment_count": int(
                statistics.get("commentCount", 0)
            ),
            "discovered_query": ", ".join(
                candidate["queries"]
            ),
        }

        # Compare the two most recent stored snapshots.
        views_per_day = get_velocity_from_history(
        video_id,
        current_views=video["view_count"],
        compare_current=True,
        )

        score, reasons = evaluate_video(
            video,
            views_per_day
        )

        video["traction_score"] = score
        video["traction_reasons"] = reasons

        try:

            save_youtube_video(video)
            save_statistics_snapshot(video)
            saved += 1

        except Exception as exc:
            print(f"Database save error for {video_id}: {exc}")

    print("\nDISCOVERY SUMMARY")
    print("-" * 65)
    print(f"Unique videos discovered: {len(video_ids)}")
    print(f"Videos saved/updated: {saved}")
    print(f"Videos skipped (too short): {skipped}")
    print(f"Total videos in database: {count_youtube_videos()}")

    show_top_youtube_videos(limit=top)
