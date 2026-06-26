"""
Stage 1 of the daily reel: turn the day's Milton Keynes news into a spoken
news-bulletin MP3 using a natural British voice (edge-tts, free, no API key).

Outputs:
  reel_script.txt  - the spoken script (for review)
  reel_voice.mp3   - the narrated audio

Run locally:  python make_reel_voice.py
Or via the "Reel Voice Test" GitHub Action, which uploads both files as artifacts.
"""

import os
import re
import time
import asyncio

import feedparser
import requests
import edge_tts

# === CONFIG ===
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

RSS_FEEDS = [
    "https://www.miltonkeynes.co.uk/news/rss",
    "https://www.milton-keynes.gov.uk/news/rss.xml",
    "https://news.google.com/rss/search?q=Thames+Valley+Police+Milton+Keynes&hl=en-GB&gl=GB&ceid=GB:en",
]

# Natural British news-presenter voice. Alternatives you can try:
#   en-GB-RyanNeural   (male, warm)
#   en-GB-LibbyNeural  (female, younger/brighter)
#   en-GB-ThomasNeural (male, measured)
VOICE = "en-GB-SoniaNeural"
SPEAKING_RATE = "+3%"   # slight lift for energy; "+0%" for fully neutral

MAX_STORIES = 5
SCRIPT_OUT = "reel_script.txt"
AUDIO_OUT = "reel_voice.mp3"


# === Feed fetching (browser UA, like the main bot) ===
def load_feed(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200 and resp.content:
            feed = feedparser.parse(resp.content)
            if feed.entries:
                return feed
    except Exception as e:
        print(f"   ⚠️ Fetch failed for {url}: {e}")
    return feedparser.parse(url)


def _entry_time(entry):
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    try:
        return time.mktime(t) if t else 0
    except Exception:
        return 0


def _clean_title(title):
    # Google News appends " - Source Name"; drop it for a clean read.
    return re.sub(r"\s+-\s+[^-]+$", "", title).strip()


def _strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def get_today_stories(max_items=MAX_STORIES):
    print("📰 Gathering the day's news...")
    all_entries = []
    for url in RSS_FEEDS:
        feed = load_feed(url)
        if feed.entries:
            print(f"   ✅ {len(feed.entries)} from {url}")
            all_entries.extend(feed.entries)

    if not all_entries:
        return []

    all_entries.sort(key=_entry_time, reverse=True)

    # Prefer stories from the last 24h; if too few, just take the newest.
    cutoff = time.time() - 24 * 3600
    recent = [e for e in all_entries if _entry_time(e) >= cutoff]
    pool = recent if len(recent) >= 3 else all_entries

    seen, stories = set(), []
    for e in pool:
        title = _clean_title(e.get("title", ""))
        key = re.sub(r"[^a-z0-9]", "", title.lower())[:40]
        if not key or key in seen:
            continue
        seen.add(key)
        stories.append({
            "title": title,
            "summary": _strip_html(e.get("summary", e.get("description", "")))[:300],
        })
        if len(stories) >= max_items:
            break

    print(f"✅ Selected {len(stories)} stories.")
    return stories


# === Script writing ===
def write_script(stories):
    print("✍️ Writing the bulletin script...")
    story_block = "\n".join(
        f"{i+1}. {s['title']} — {s['summary']}" for i, s in enumerate(stories)
    )

    if not OPENAI_API_KEY:
        # Simple fallback if no AI key.
        lines = ["Good evening, Milton Keynes. Here's your news round-up for today."]
        for s in stories:
            lines.append(s["title"] + ".")
        lines.append("That's your update. We'll see you again tomorrow.")
        return " ".join(lines)

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are the scriptwriter for a daily Milton Keynes news reel on Instagram. "
                            "Write a SPOKEN script for a friendly, warm British news presenter to read aloud. "
                            "Constraints: about 110-130 words total (it must fit in ~45 seconds when spoken); "
                            "open with a warm greeting that mentions Milton Keynes and the evening; "
                            "cover each story in one or two natural sentences, in plain conversational English; "
                            "keep a credible but lively local-news tone; "
                            "end with a short friendly sign-off inviting people to follow for tomorrow's update. "
                            "IMPORTANT: output ONLY the words to be spoken. No emojis, no hashtags, no stage "
                            "directions, no headings, no markdown, no URLs."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Today's Milton Keynes stories:\n{story_block}\n\nWrite the script.",
                    },
                ],
            },
            timeout=40,
        )
        if resp.status_code == 200:
            script = resp.json()["choices"][0]["message"]["content"].strip()
            print("✅ Script ready.")
            return script
        else:
            print(f"⚠️ AI error {resp.status_code}; using simple fallback.")
    except Exception as e:
        print(f"⚠️ AI failed ({e}); using simple fallback.")

    return "Good evening, Milton Keynes. " + " ".join(s["title"] + "." for s in stories)


# === Voice synthesis ===
async def synthesize(text, path):
    print(f"🎙️ Synthesizing voice ({VOICE})...")
    communicate = edge_tts.Communicate(text, VOICE, rate=SPEAKING_RATE)
    await communicate.save(path)
    print(f"✅ Saved {path}")


def main():
    stories = get_today_stories()
    if not stories:
        print("❌ No stories found. Exiting.")
        return

    script = write_script(stories)

    with open(SCRIPT_OUT, "w", encoding="utf-8") as f:
        f.write(script)

    word_count = len(script.split())
    print("\n----- SCRIPT -----")
    print(script)
    print(f"------------------\n(~{word_count} words, roughly {round(word_count/2.4)} seconds spoken)\n")

    asyncio.run(synthesize(script, AUDIO_OUT))
    print("\n🎬 Stage 1 done. Listen to reel_voice.mp3 and check reel_script.txt.")


if __name__ == "__main__":
    main()
