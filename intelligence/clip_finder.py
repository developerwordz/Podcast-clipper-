
import json
import re
import time

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL


MAX_ATTEMPTS = 4
INITIAL_RETRY_DELAY = 3

# Reject clips that are technically valid but not entertaining enough.
MINIMUM_CLIP_SCORE = 7.0

MIN_CLIP_DURATION = 25
MAX_CLIP_DURATION = 60


def _get_client():
    if not GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY is missing. Add it to your .env file."
        )

    return genai.Client(api_key=GEMINI_API_KEY)


def _extract_json(text):
    if not text:
        raise ValueError("Gemini returned an empty response.")

    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    return json.loads(text)


def _generate_with_retry(client, prompt):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            print(
                f"[Gemini] Finding curiosity-driven moments "
                f"(attempt {attempt}/{MAX_ATTEMPTS})..."
            )

            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.35,
                ),
            )

            if not response.text:
                raise ValueError("Gemini returned an empty response.")

            return response.text

        except Exception as exc:
            error_message = str(exc)

            temporary_error = any(
                code in error_message
                for code in ["429", "500", "502", "503", "504"]
            )

            if not temporary_error or attempt == MAX_ATTEMPTS:
                raise

            delay = INITIAL_RETRY_DELAY * (2 ** (attempt - 1))

            print(
                f"[Gemini] Temporary API error. "
                f"Retrying in {delay} seconds..."
            )

            time.sleep(delay)

    raise RuntimeError("Gemini request failed after all attempts.")


def find_clips(transcript, target_clips=5):

    segments = transcript.get("segments", [])

    if not segments:
        raise ValueError("Transcript contains no segments.")

    duration = float(transcript.get("duration_seconds", 0))

    if duration <= 0:
        duration = max(
            float(segment["end"])
            for segment in segments
        )

    transcript_lines = []

    for segment in segments:
        try:
            start = float(segment["start"])
            end = float(segment["end"])
            text = str(segment["text"]).strip()

            if not text or end <= start:
                continue

            transcript_lines.append(
                f"[{start:.2f} - {end:.2f}] {text}"
            )

        except (KeyError, TypeError, ValueError):
            continue

    if not transcript_lines:
        raise ValueError("Transcript has no valid segments.")

    transcript_text = "\n".join(transcript_lines)

    prompt = f"""
You are a world-class viral short-form entertainment editor.

Your job is NOT to find educational highlights.

Your job is to find moments that make someone curious enough
to watch an entire YouTube Short, and then reward that curiosity
with a satisfying payoff.

Think like a storyteller, not a teacher.

EPISODE DURATION: {duration:.2f} seconds.

TARGET: Find up to {target_clips} exceptional clips.

TRANSCRIPT:
{transcript_text}


==================================================
WHAT MAKES A GREAT CLIP?
==================================================

Prioritize moments containing:

1. UNEXPECTED STORIES
   Strange experiences, unbelievable situations, personal
   confessions, unexpected encounters and coincidences.

2. CURIOSITY
   Information that makes viewers wonder what happened next,
   why something happened, or how something is possible.

3. TWISTS AND REVELATIONS
   A surprising reveal, unexpected consequence, contradiction
   or change in what the viewer expects.

4. HUMAN DRAMA
   Arguments, awkward moments, embarrassing experiences,
   unusual decisions, emotional reactions and disagreements.

5. ENTERTAINMENT
   Funny observations, bizarre situations, shocking admissions,
   fascinating experiences and memorable conversations.

Educational or technical content is acceptable ONLY when
the actual moment feels like an entertaining story or revelation.

DO NOT prioritize content simply because it is informative,
intelligent, motivational or spoken by a famous person.


==================================================
THE MOST IMPORTANT RULE: CURIOSITY + PAYOFF
==================================================

Every selected clip should work like a tiny story.

A strong clip generally has:

- A hook that makes the viewer wonder something.
- A build-up that gives the viewer a reason to keep watching.
- A payoff that answers the question or completes the story.

The viewer should feel:

"Wait, what happened?"
"I need to know."
"Ohhh, that's what happened!"

STRICTLY REJECT:

- Clips that start with a long introduction.
- Generic advice or motivational speeches.
- Long explanations with no surprising revelation.
- Stories that end before the interesting part.
- Hooks that promise something the clip never delivers.
- Clips that require substantial outside context.
- Moments where the supposed payoff is missing.
- Ordinary conversations with no memorable moment.


==================================================
CLIP SELECTION RULES
==================================================

- Prefer clips between {MIN_CLIP_DURATION} and
  {MAX_CLIP_DURATION} seconds.
- Use actual transcript timestamps.
- Start at a natural point, preferably near the beginning
  of the interesting statement or story.
- The first few seconds must contain a compelling hook.
- Include enough context to understand the situation.
- Include the actual reveal, punchline or conclusion.
- End shortly after the payoff.
- Never invent dialogue, events or timestamps.
- Never rearrange dialogue or combine separate moments.
- The clip must be one continuous section of the original video.
- Never exceed the episode duration.
- Avoid overlapping clips.
- Prefer fewer excellent clips over several mediocre ones.

IMPORTANT:
Do not force the requested number of clips.
If only two moments are genuinely entertaining, return two.


==================================================
TITLES: MAKE PEOPLE WANT TO CLICK
==================================================

Generate short, curiosity-driven titles.

GOOD TITLE STYLES:

- "He Couldn't Believe What Happened Next"
- "This Is Where Everything Went Wrong"
- "Nobody Expected Him to Say That"
- "The Weirdest Thing That Ever Happened to Her"
- "He Made One Decision He Instantly Regretted"
- "And Then Things Got Really Strange"

These are STYLE EXAMPLES ONLY.

Write titles that accurately represent the actual clip.
Do not copy these examples blindly.
Do not invent secrets, danger, controversy or revelations.
Do not reveal the entire payoff in the title.

The title should create curiosity.
The clip should satisfy it.


==================================================
SCORING: RATE EACH CATEGORY FROM 1 TO 10
==================================================

curiosity (25%):
How strongly does the moment make someone want to know more?

storytelling (25%):
Does it have a clear beginning, build-up and progression?

payoff (20%):
Does the clip deliver a satisfying answer, reveal or conclusion?

emotion (15%):
Does it create surprise, amusement, tension, excitement
or another genuine emotional reaction?

entertainment (15%):
Would someone watch this for enjoyment rather than education?

Calculate overall_score as the weighted average of these
five scores.

A score of 9-10 means exceptional.
A score of 7-8 means genuinely good.
A score below 7 means it is probably not worth clipping.


==================================================
OUTPUT FORMAT
==================================================

Return ONLY valid JSON.

Use exactly this structure:

{{
    "clips": [
        {{
            "start": 100.0,
            "end": 145.0,
            "hook": "The actual opening dialogue or moment",
            "title": "A curiosity-driven title",
            "reason": "Explain the hook, build-up and payoff.",
            "scores": {{
                "curiosity": 9,
                "storytelling": 9,
                "payoff": 9,
                "emotion": 8,
                "entertainment": 9
            }},
            "overall_score": 8.9
        }}
    ]
}}

Return an empty clips array if there are no worthwhile moments.
"""


    client = _get_client()

    response_text = _generate_with_retry(client, prompt)

    result = _extract_json(response_text)

    if not isinstance(result, dict):
        raise ValueError("Gemini returned an invalid JSON structure.")

    clips = result.get("clips", [])

    if not isinstance(clips, list):
        raise ValueError(
            "Gemini response does not contain a valid clips list."
        )

    validated = []

    for clip in clips:
        try:
            start = float(clip["start"])
            end = float(clip["end"])
            score = float(clip["overall_score"])

            if start < 0 or end <= start:
                continue

            if end > duration:
                continue

            clip_duration = end - start

            if not (
                MIN_CLIP_DURATION <= clip_duration <= MAX_CLIP_DURATION
            ):
                continue

            if score < MINIMUM_CLIP_SCORE or score > 10:
                continue

            if not clip.get("hook") or not clip.get("title"):
                continue

            scores = clip.get("scores", {})

            required_scores = [
                "curiosity",
                "storytelling",
                "payoff",
                "emotion",
                "entertainment",
            ]

            if not isinstance(scores, dict):
                continue

            if not all(key in scores for key in required_scores):
                continue

            if not all(
                1 <= float(scores[key]) <= 10
                for key in required_scores
            ):
                continue

            clip["start"] = start
            clip["end"] = end
            clip["overall_score"] = score

            validated.append(clip)

        except (KeyError, TypeError, ValueError):
            continue

    validated.sort(
        key=lambda clip: clip["overall_score"],
        reverse=True,
    )

    # Remove overlapping clips, keeping the highest-scoring ones.
    non_overlapping = []

    for clip in validated:
        overlaps = any(
            clip["start"] < existing["end"]
            and clip["end"] > existing["start"]
            for existing in non_overlapping
        )

        if not overlaps:
            non_overlapping.append(clip)

        if len(non_overlapping) >= target_clips:
            break

    print(
        f"\n[Gemini] Curiosity-driven selection complete."
        f"\n[Gemini] Candidates returned: {len(clips)}"
        f"\n[Gemini] Passed quality filter: {len(validated)}"
        f"\n[Gemini] Final clips selected: {len(non_overlapping)}"
    )

    for index, clip in enumerate(non_overlapping, 1):
        print(
            f"\n#{index} | Score: {clip['overall_score']}/10"
            f"\nTitle: {clip['title']}"
            f"\nDuration: {clip['end'] - clip['start']:.1f}s"
            f"\nReason: {clip.get('reason', '')}"
        )

    return non_overlapping
