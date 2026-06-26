"""
Daily Milton Keynes news reel builder (free tooling only).

Pipeline:
  1. Gather the day's news (3 feeds)
  2. Write a ~45s spoken bulletin script (GPT)
  3. Synthesize a natural British voice (edge-tts)  -> reel_voice.mp3
  4. Draw a branded 9:16 card per story (Pillow)    -> cards/*.png
  5. Animate cards (Ken Burns) + crossfades + voice (+ optional music) via FFmpeg
                                                     -> reel.mp4

Optional music: drop a royalty-free 'music.mp3' in the repo root and it will be
mixed quietly under the narration. Without it, you just get clean narration.

Run: python build_reel.py
"""

import os
import re
import time
import math
import asyncio
import subprocess
import textwrap

import feedparser
import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# === CONFIG ===
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

RSS_FEEDS = [
    "https://www.miltonkeynes.co.uk/news/rss",
    "https://www.milton-keynes.gov.uk/news/rss.xml",
    "https://news.google.com/rss/search?q=Thames+Valley+Police+Milton+Keynes&hl=en-GB&gl=GB&ceid=GB:en",
]

LOGO_URL = "https://raw.githubusercontent.com/miltonkeynesnewslive-prog/milton-keynes-news-bot/main/MK%20News%20Logo.png"

VOICE = "en-GB-SoniaNeural"
SPEAKING_RATE = "+3%"

MAX_STORIES = 5
W, H = 1080, 1920           # 9:16 reel
FPS = 30
TRANSITION = 0.6            # crossfade seconds between cards
INTRO_DUR = 2.2
OUTRO_DUR = 2.6

CARD_DIR = "cards"
VOICE_OUT = "reel_voice.mp3"
SCRIPT_OUT = "reel_script.txt"
VIDEO_OUT = "reel.mp4"
MUSIC_FILE = "music.mp3"    # optional
LOGO_FILE = "logo.png"

RED = (204, 0, 0)
WHITE = (255, 255, 255)


# ---------- Fonts ----------
def _font(size, bold=True):
    # Prefer Oswald if present in repo (oswald.ttf), else DejaVu (always available).
    for path in ("oswald.ttf", "Oswald.ttf"):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    base = "/usr/share/fonts/truetype/dejavu/"
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(base + name, size)
    except Exception:
        return ImageFont.load_default()


# ---------- Feeds ----------
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
    return re.sub(r"\s+-\s+[^-]+$", "", title).strip()


def _strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _article_image(entry):
    try:
        if getattr(entry, "media_content", None):
            u = entry.media_content[0].get("url")
            if u:
                return u
    except Exception:
        pass
    try:
        if getattr(entry, "media_thumbnail", None):
            u = entry.media_thumbnail[0].get("url")
            if u:
                return u
    except Exception:
        pass
    m = re.search(r'<img[^>]+src="([^"]+)"', entry.get("summary", ""))
    return m.group(1) if m else None


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
            "image": _article_image(e),
        })
        if len(stories) >= max_items:
            break
    print(f"✅ Selected {len(stories)} stories.")
    return stories


# ---------- Script ----------
def write_script(stories):
    print("✍️ Writing the bulletin script...")
    block = "\n".join(f"{i+1}. {s['title']} — {s['summary']}" for i, s in enumerate(stories))
    if OPENAI_API_KEY:
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": (
                            "You write a daily Milton Keynes news reel script for a friendly British presenter to read. "
                            "About 110-130 words (~45 seconds). Open with a warm evening greeting mentioning Milton Keynes. "
                            "Cover each story in one or two natural sentences. Credible but lively local-news tone. "
                            "End with a short friendly sign-off to follow for tomorrow. "
                            "Output ONLY spoken words: no emojis, hashtags, headings, stage directions, or URLs."
                        )},
                        {"role": "user", "content": f"Today's stories:\n{block}\n\nWrite the script."},
                    ],
                },
                timeout=40,
            )
            if resp.status_code == 200:
                print("✅ Script ready.")
                return resp.json()["choices"][0]["message"]["content"].strip()
            print(f"⚠️ AI error {resp.status_code}; using fallback.")
        except Exception as e:
            print(f"⚠️ AI failed ({e}); using fallback.")
    return "Good evening, Milton Keynes. " + " ".join(s["title"] + "." for s in stories) + " Follow us for tomorrow's update."


# ---------- Voice ----------
async def _synth(text, path):
    await edge_tts.Communicate(text, VOICE, rate=SPEAKING_RATE).save(path)


def synth_voice(script):
    print(f"🎙️ Synthesizing voice ({VOICE})...")
    asyncio.run(_synth(script, VOICE_OUT))
    print(f"✅ Saved {VOICE_OUT}")
    return VOICE_OUT


def audio_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except Exception:
        return 45.0


# ---------- Cards (Pillow) ----------
def _vertical_gradient(size, top_rgba, bottom_rgba):
    w, h = size
    grad = Image.new("RGBA", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        grad.putpixel((0, y), tuple(
            int(top_rgba[i] + (bottom_rgba[i] - top_rgba[i]) * t) for i in range(4)
        ))
    return grad.resize((w, h))


def _cover(img, size):
    """Resize+center-crop an image to fully cover the target size."""
    tw, th = size
    iw, ih = img.size
    scale = max(tw / iw, th / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    left, top = (nw - tw) // 2, (nh - th) // 2
    return img.crop((left, top, left + tw, top + th))


def _download_image(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 200 and r.content:
            from io import BytesIO
            return Image.open(BytesIO(r.content)).convert("RGB")
    except Exception as e:
        print(f"   ⚠️ image download failed: {e}")
    return None


def _wrap(draw, text, font, max_width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def make_card(story, path, logo_img):
    card = Image.new("RGB", (W, H), (17, 17, 17))

    # Background
    bg = None
    if story.get("image"):
        bg = _download_image(story["image"])
    if bg is not None:
        card.paste(_cover(bg, (W, H)), (0, 0))
    else:
        # Branded red->black vertical gradient
        grad = _vertical_gradient((W, H), (224, 0, 0, 255), (20, 0, 0, 255)).convert("RGB")
        card.paste(grad, (0, 0))

    # Dark overlay (top + heavy bottom) for legibility
    overlay = _vertical_gradient((W, H), (0, 0, 0, 90), (0, 0, 0, 0))
    bottom = _vertical_gradient((W, H), (0, 0, 0, 0), (0, 0, 0, 235))
    card_rgba = card.convert("RGBA")
    card_rgba = Image.alpha_composite(card_rgba, overlay)
    card_rgba = Image.alpha_composite(card_rgba, bottom)
    card = card_rgba.convert("RGB")

    draw = ImageDraw.Draw(card)

    # Logo badge (white rounded rect) top-left
    if logo_img is not None:
        badge_pad = 28
        lw = 230
        ratio = lw / logo_img.width
        lh = int(logo_img.height * ratio)
        logo_r = logo_img.resize((lw, lh), Image.LANCZOS)
        bx0, by0 = 60, 70
        bx1, by1 = bx0 + lw + badge_pad * 2, by0 + lh + badge_pad * 2
        draw.rounded_rectangle([bx0, by0, bx1, by1], radius=28, fill=WHITE)
        card.paste(logo_r, (bx0 + badge_pad, by0 + badge_pad),
                   logo_r if logo_r.mode == "RGBA" else None)
        draw = ImageDraw.Draw(card)

    # Kicker
    kfont = _font(40)
    draw.text((66, 360), "MILTON KEYNES NEWS", font=kfont, fill=(255, 255, 255))

    # Headline near bottom
    hfont = _font(82)
    headline = story["title"].upper()
    lines = _wrap(draw, headline, hfont, W - 130)[:5]
    line_h = hfont.size + 14
    total_h = line_h * len(lines)
    y = H - 360 - total_h
    # red accent
    draw.rounded_rectangle([66, y - 46, 66 + 120, y - 32], radius=6, fill=RED)
    for ln in lines:
        draw.text((66, y), ln, font=hfont, fill=WHITE)
        y += line_h

    # Footer
    draw.rectangle([0, H - 96, W, H], fill=RED)
    ffont = _font(40)
    draw.text((66, H - 80), "@miltonkeynes_news", font=ffont, fill=WHITE)

    card.save(path, "PNG")
    return path


def make_simple_card(top_text, big_text, path, logo_img, subtitle=""):
    card = Image.new("RGB", (W, H), (17, 17, 17))
    grad = _vertical_gradient((W, H), (224, 0, 0, 255), (20, 0, 0, 255)).convert("RGB")
    card.paste(grad, (0, 0))
    draw = ImageDraw.Draw(card)

    if logo_img is not None:
        lw = 360
        ratio = lw / logo_img.width
        lh = int(logo_img.height * ratio)
        logo_r = logo_img.resize((lw, lh), Image.LANCZOS)
        white = Image.new("RGB", (lw + 60, lh + 60), WHITE)
        wx = (W - white.width) // 2
        card.paste(white, (wx, 540))
        card.paste(logo_r, (wx + 30, 570), logo_r if logo_r.mode == "RGBA" else None)
        draw = ImageDraw.Draw(card)

    tfont = _font(46)
    tw = draw.textlength(top_text, font=tfont)
    draw.text(((W - tw) / 2, 470), top_text, font=tfont, fill=WHITE)

    bfont = _font(78)
    lines = _wrap(draw, big_text, bfont, W - 160)
    y = 940
    for ln in lines:
        lw2 = draw.textlength(ln, font=bfont)
        draw.text(((W - lw2) / 2, y), ln, font=bfont, fill=WHITE)
        y += bfont.size + 12

    if subtitle:
        sfont = _font(44, bold=False)
        sw = draw.textlength(subtitle, font=sfont)
        draw.text(((W - sw) / 2, y + 30), subtitle, font=sfont, fill=(255, 255, 255))

    card.save(path, "PNG")
    return path


# ---------- FFmpeg assembly ----------
def _clip_from_card(card_path, duration, out_path, zoom_in=True):
    """Make a Ken Burns clip from a still card."""
    frames = max(int(duration * FPS), 1)
    z = "min(zoom+0.0009,1.10)" if zoom_in else "if(eq(on,1),1.10,max(zoom-0.0009,1.0))"
    vf = (
        f"scale={int(W*1.10)}:{int(H*1.10)},"
        f"zoompan=z='{z}':d={frames}:s={W}x{H}:fps={FPS}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',"
        f"format=yuv420p"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", card_path,
         "-vf", vf, "-frames:v", str(frames), "-r", str(FPS),
         "-preset", "veryfast", "-an", out_path],
        check=True, capture_output=True,
    )
    return out_path


def assemble(card_paths, durations, audio_path, out_path, music_path=None):
    """Animate each card, crossfade them, and mux narration (+ optional music)."""
    print("🎞️ Rendering clips...")
    clips = []
    for i, (cp, d) in enumerate(zip(card_paths, durations)):
        clip = f"clip_{i}.mp4"
        _clip_from_card(cp, d + (TRANSITION if i < len(card_paths) - 1 else 0), clip,
                        zoom_in=(i % 2 == 0))
        clips.append(clip)

    print("🎚️ Crossfading + muxing audio...")
    inputs = []
    for c in clips:
        inputs += ["-i", c]
    inputs += ["-i", audio_path]
    audio_idx = len(clips)
    have_music = music_path and os.path.exists(music_path)
    if have_music:
        inputs += ["-stream_loop", "-1", "-i", music_path]
        music_idx = len(clips) + 1

    # Build xfade chain
    filt = ""
    if len(clips) == 1:
        filt += f"[0:v]format=yuv420p[v];"
    else:
        prev = "0:v"
        cum = durations[0]
        for j in range(1, len(clips)):
            off = cum - TRANSITION
            label = f"vx{j}"
            filt += (f"[{prev}][{j}:v]xfade=transition=fade:duration={TRANSITION}:"
                     f"offset={off:.3f}[{label}];")
            prev = label
            cum += durations[j]
        filt += f"[{prev}]format=yuv420p[v];"

    if have_music:
        filt += (f"[{music_idx}:a]volume=0.10[mus];"
                 f"[{audio_idx}:a][mus]amix=inputs=2:duration=first:dropout_transition=2[a]")
        amap = "[a]"
    else:
        amap = f"{audio_idx}:a"

    cmd = ["ffmpeg", "-y"] + inputs + [
        "-filter_complex", filt.rstrip(";"),
        "-map", "[v]", "-map", amap,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-shortest", out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"✅ Saved {out_path}")
    return out_path


# ---------- Main ----------
def main():
    os.makedirs(CARD_DIR, exist_ok=True)

    stories = get_today_stories()
    if not stories:
        print("❌ No stories. Exiting.")
        return

    script = write_script(stories)
    with open(SCRIPT_OUT, "w", encoding="utf-8") as f:
        f.write(script)
    print("\n----- SCRIPT -----\n" + script + "\n------------------\n")

    synth_voice(script)
    total = audio_duration(VOICE_OUT)
    print(f"🕒 Narration length: {total:.1f}s")

    # Logo
    logo_img = None
    li = _download_image(LOGO_URL)
    if li is not None:
        logo_img = li.convert("RGBA")

    # Build cards: intro + stories + outro
    from datetime import datetime
    date_str = datetime.now().strftime("%A %d %B")
    intro = make_simple_card("MILTON KEYNES NEWS", "EVENING UPDATE",
                             os.path.join(CARD_DIR, "intro.png"), logo_img, subtitle=date_str)
    story_cards = []
    for i, s in enumerate(stories):
        story_cards.append(make_card(s, os.path.join(CARD_DIR, f"story_{i}.png"), logo_img))
    outro = make_simple_card("THANKS FOR WATCHING", "FOLLOW FOR MORE",
                             os.path.join(CARD_DIR, "outro.png"), logo_img,
                             subtitle="@miltonkeynes_news")

    cards = [intro] + story_cards + [outro]

    # Allocate durations to match narration. Intro/outro fixed; stories share the rest.
    story_total = max(total - INTRO_DUR - OUTRO_DUR, len(story_cards) * 2.0)
    per_story = story_total / len(story_cards)
    durations = [INTRO_DUR] + [per_story] * len(story_cards) + [OUTRO_DUR]

    assemble(cards, durations, VOICE_OUT, VIDEO_OUT,
             music_path=MUSIC_FILE if os.path.exists(MUSIC_FILE) else None)

    print("\n🎬 Reel built: reel.mp4")


if __name__ == "__main__":
    main()
