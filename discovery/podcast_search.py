import requests
from config import REQUEST_TIMEOUT, USER_AGENT

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"

def search_podcasts(term: str, limit: int = 10, country: str | None = None):
    params = {
        "term": term,
        "entity": "podcast",
        "limit": max(1, min(limit, 50)),
    }
    if country:
        params["country"] = country

    response = requests.get(
        ITUNES_SEARCH_URL,
        params=params,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    payload = response.json()

    results = []
    for item in payload.get("results", []):
        feed_url = item.get("feedUrl")
        if not feed_url:
            continue
        results.append({
            "podcast_name": item.get("collectionName") or "Unknown podcast",
            "creator_name": item.get("artistName"),
            "feed_url": feed_url,
            "country": item.get("country"),
            "genre": item.get("primaryGenreName"),
            "artwork_url": item.get("artworkUrl600") or item.get("artworkUrl100"),
        })
    return results
