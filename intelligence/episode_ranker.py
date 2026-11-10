
import re
import html


POSITIVE_TERMS = [
    "interview",
    "conversation",
    "guest",
    "founder",
    "ceo",
    "story",
    "journey",
    "career",
    "failure",
    "success",
    "debate",
    "controversial",
    "truth",
    "secret",
    "mistake",
    "money",
    "business",
    "psychology",
    "relationship",
    "technology",
    "science",
    "future",
    "challenge",
    "lesson",
    "advice",
    "explained",
    "deep dive",
    "case study",
    "startup",
    "entrepreneur",
    "innovation",
    "leadership",
    "history",
    "mystery",
    "survival",
    "crime",
    "investigation",
    "experiment",
    "discovery",
    "shocking",
    "surprising",
    "behind the scenes",
    "how i",
    "why",
    "what happened",
    "real story",
    "life changing",
    "unbelievable",
    "unpopular opinion",
    "mental models",
    "lessons learned",
    "personal experience",
    "expert",
    "celebrities",
    "politics",
    "culture",
]

NEGATIVE_TERMS = [
    "bedtime",
    "sleep story",
    "sleep stories",
    "sleep meditation",
    "nursery rhymes",
    "nursery",
    "fairy tales",
    "fairy tale",
    "kids podcast",
    "children's podcast",
    "children podcast",
    "bible study",
    "sermon",
    "worship",
    "prayer",
    "devotional",
    "english lesson",
    "english lessons",
    "learn english",
    "learning english",
    "grammar lesson",
    "grammar lessons",
    "pronunciation practice",
    "guided meditation",
    "daily meditation",
    "weather report",
    "daily weather",
    "daily news briefing",
    "news bulletin",
    "traffic report",
    "episode trailer",
    "podcast trailer",
    "sleep sounds",
    "white noise",
]

PODCAST_NEGATIVE_TERMS = [
    "for kids",
    "for children",
    "children's stories",
    "bible study",
    "english learning",
    "learn english",
    "bedtime stories",
    "sleep stories",
    "guided meditation",
]


def clean_text(value):
    """Convert HTML-like RSS descriptions into searchable plain text."""
    if not value:
        return ""

    value = html.unescape(str(value))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip().lower()


def find_matches(text, terms):
    """Find unique keyword/phrase matches without partial-word matches."""
    matches = []

    for term in terms:
        pattern = r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)"

        if re.search(pattern, text):
            matches.append(term)

    return matches


def get_duration_score(duration_seconds):
    if duration_seconds is None:
        return 0, None

    try:
        duration = int(duration_seconds)
    except (TypeError, ValueError):
        return 0, None

    if duration < 0:
        return 0, None

    minutes = duration / 60

    if 15 <= minutes <= 180:
        return 8, "Good long-form episode duration"

    if minutes < 5:
        return -12, "Very short episode"

    if minutes > 360:
        return -5, "Unusually long episode"

    if 5 <= minutes < 15:
        return 2, "Shorter episode"

    if 180 < minutes <= 360:
        return 3, "Long-form episode"

    return 0, None


def rank_episode(episode):
    """
    Calculate a transparent heuristic relevance score from 0 to 100.

    This estimates suitability for finding engaging podcast clips.
    It does not predict actual virality or guarantee clip quality.
    """

    title = clean_text(episode["title"])
    description = clean_text(episode["description"])
    podcast_name = clean_text(episode["podcast_name"])

    combined_text = f"{title} {description}"

    score = 35
    reasons = []

    # Positive title signals.
    title_matches = find_matches(title, POSITIVE_TERMS)
    title_points = min(len(title_matches) * 3, 28)
    score += title_points

    if title_matches:
        reasons.append(
            "Positive title signals: " + ", ".join(title_matches[:6])
        )

    # Positive description signals.
    description_matches = find_matches(
        description,
        POSITIVE_TERMS
    )

    description_points = min(
        len(description_matches) * 1.5,
        12
    )

    score += description_points

    if description_matches:
        reasons.append(
            "Relevant description signals: "
            + ", ".join(description_matches[:6])
        )

    # Negative content signals.
    negative_matches = find_matches(
        combined_text,
        NEGATIVE_TERMS
    )

    negative_penalty = min(
        len(negative_matches) * 5,
        45
    )

    score -= negative_penalty

    if negative_matches:
        reasons.append(
            "Irrelevant-content signals: "
            + ", ".join(negative_matches[:6])
        )

    # Podcast-level penalties.
    podcast_matches = find_matches(
        podcast_name,
        PODCAST_NEGATIVE_TERMS
    )

    podcast_penalty = min(
        len(podcast_matches) * 10,
        25
    )

    score -= podcast_penalty

    if podcast_matches:
        reasons.append(
            "Podcast category warning: "
            + ", ".join(podcast_matches)
        )

    # Rich descriptions provide more context for later clip extraction.
    if len(description) >= 500:
        score += 8
        reasons.append("Detailed episode description")

    elif len(description) >= 200:
        score += 4
        reasons.append("Useful episode description")

    # Episode duration.
    duration_points, duration_reason = get_duration_score(
        episode["duration_seconds"]
    )

    score += duration_points

    if duration_reason:
        reasons.append(duration_reason)

    # Audio availability.
    if episode["audio_url"]:
        score += 5
        reasons.append("Audio enclosure available")
    else:
        score -= 8
        reasons.append("No direct audio enclosure found")

    # Clamp score to 0–100.
    score = max(0, min(100, round(score)))

    if score >= 70:
        tier = "HIGH"
    elif score >= 50:
        tier = "MEDIUM"
    else:
        tier = "LOW"

    if not reasons:
        reasons.append("No strong relevance signals found")

    return {
        "score": score,
        "tier": tier,
        "reasons": reasons,
    }
