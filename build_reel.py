"""
Daily Milton Keynes news reel builder (free tooling only).

Key design:
  - Each story is narrated as its OWN audio segment, so each card is shown for
    exactly as long as its story is spoken (perfect audio/visual sync).
  - Photos are shown WHOLE (fit, not cropped) over a blurred fill of themselves.
  - Subtle Ken Burns motion + hard cuts (clean, reliable, perfectly synced).

Outputs: reel.mp4, reel_script.txt
Optional: drop a royalty-free 'music.mp3' in the repo root to mix it under the voice.
Optional: drop 'oswald.ttf' in the repo root for the Oswald font (else DejaVu).

Run: python build_reel.py
"""

import os
import re
import json
import time
import asyncio
import subprocess
from io import BytesIO
from datetime import datetime

import feedparser
import requests
import edge_tts
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

# === CONFIG ===
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

RSS_FEEDS = [
    "https://www.miltonkeynes.co.uk/news/rss",
    "https://www.milton-keynes.gov.uk/news/rss.xml",
    "https://news.google.com/rss/search?q=Thames+Valley+Police+Milton+Keynes&hl=en-GB&gl=GB&ceid=GB:en",
]

LOGO_URL = "https://raw.githubusercontent.com/miltonkeynesnewslive-prog/milton-keynes-news-bot/main/MK%20News%20Logo.png"

VOICE = "en-GB-SoniaNeural"
SPEAKING_RATE = "+6%"

MAX_STORIES = 5
W, H = 1080, 1920
FPS = 30
GAP = 0.30          # silence between spoken segments
TAIL = 0.6          # silence after the last segment
ZOOM_MAX = 1.05     # gentle Ken Burns

CARD_DIR = "cards"
CLIP_DIR = "clips"
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY")
STOPWORDS = set("the a an of to in on for and or with after before over under from into "
                "man woman say says new news milton keynes as at by is are was were has have".split())
VOICE_OUT = "reel_voice.mp3"
SCRIPT_OUT = "reel_script.txt"
VIDEO_OUT = "reel.mp4"
MUSIC_FILE = "music.mp3"

RED = (204, 0, 0)
WHITE = (255, 255, 255)


# ---------- Fonts ----------
def _font(size, bold=True):
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
    return re.sub(r"\s+-\s+[^-]+$", "", title or "").strip()


def _strip_html(text):
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _dedupe_key(title):
    words = re.findall(r"[a-z0-9]+", title.lower())
    return " ".join(words[:5])   # first 5 significant words


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

    seen_keys, stories = [], []
    for e in pool:
        title = _clean_title(e.get("title", ""))
        if not title:
            continue
        key = _dedupe_key(title)
        # skip if this key matches, or is contained in, an already-chosen one
        if any(key == k or key in k or k in key for k in seen_keys):
            continue
        seen_keys.append(key)
        stories.append({
            "title": title,
            "summary": _strip_html(e.get("summary", e.get("description", "")))[:300],
            "image": _article_image(e),
        })
        if len(stories) >= max_items:
            break
    print(f"✅ Selected {len(stories)} stories.")
    return stories


# ---------- Script (structured per-segment) ----------
def write_script_parts(stories):
    """Return (hook_text, [story_text,...], outro_text)."""
    print("✍️ Writing the bulletin script...")
    n = len(stories)
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
                            "You script a fast, punchy daily Milton Keynes news reel for Instagram, "
                            "read by a British presenter. Retention is everything: NO greetings, NO 'good "
                            "evening', NO 'welcome'. "
                            "Respond with ONLY valid JSON, no markdown, in this shape: "
                            '{"hook": "...", "stories": ["...", "..."], "outro": "..."}. '
                            f'"hook" is ONE short scroll-stopping sentence (max ~12 words) that makes people '
                            f"stop and watch — either tease the single most surprising story, or say something "
                            f'punchy like "Milton Keynes, {n} things you need to know today". '
                            f'"stories" must have EXACTLY {n} items in the given order, each ONE tight, natural '
                            "spoken sentence (no waffle). "
                            'The "outro" is one short line telling people to follow for more. '
                            "No emojis, hashtags, numbering, or URLs anywhere."
                        )},
                        {"role": "user", "content": f"Today's stories:\n{block}"},
                    ],
                },
                timeout=45,
            )
            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"].strip()
                raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
                data = json.loads(raw)
                hook = str(data.get("hook", data.get("intro", ""))).strip()
                outro = str(data.get("outro", "")).strip()
                s_lines = [str(x).strip() for x in data.get("stories", []) if str(x).strip()]
                if hook and outro and len(s_lines) == n:
                    print("✅ Script ready.")
                    return hook, s_lines, outro
                print("⚠️ Script JSON shape unexpected; using fallback.")
            else:
                print(f"⚠️ AI error {resp.status_code}; using fallback.")
        except Exception as e:
            print(f"⚠️ AI failed ({e}); using fallback.")

    # Deterministic fallback
    hook = f"Milton Keynes, {n} stories you need to know today."
    s_lines = [s["title"] + "." for s in stories]
    outro = "Follow us for more, every weekday."
    return hook, s_lines, outro


# ---------- Voice (per segment) ----------
async def _synth(text, path):
    await edge_tts.Communicate(text, VOICE, rate=SPEAKING_RATE).save(path)


def audio_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except Exception:
        return 4.0


def build_narration(segment_texts):
    """Synthesize each segment, measure it, and stitch into one voice track.
    Returns (voice_path, [card_duration_per_segment])."""
    print(f"🎙️ Synthesizing {len(segment_texts)} voice segments ({VOICE})...")
    seg_files, durs = [], []
    for i, t in enumerate(segment_texts):
        p = f"seg_{i}.mp3"
        asyncio.run(_synth(t, p))
        seg_files.append(p)
        durs.append(audio_duration(p))

    # Silence clips matched to edge-tts format (24kHz mono mp3) for clean concat.
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                    "-t", str(GAP), "-ar", "24000", "-ac", "1", "-b:a", "48k", "sil.mp3"],
                   check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                    "-t", str(TAIL), "-ar", "24000", "-ac", "1", "-b:a", "48k", "tail.mp3"],
                   check=True, capture_output=True)

    # Order: seg0, sil, seg1, sil, ..., segLast, tail
    order = []
    for i, sf in enumerate(seg_files):
        order.append(sf)
        order.append("sil.mp3" if i < len(seg_files) - 1 else "tail.mp3")

    with open("audio_list.txt", "w") as f:
        for p in order:
            f.write(f"file '{p}'\n")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "audio_list.txt",
                    "-c", "copy", VOICE_OUT], check=True, capture_output=True)

    card_durations = []
    for i, d in enumerate(durs):
        card_durations.append(d + (GAP if i < len(durs) - 1 else TAIL))
    print(f"✅ Narration built ({sum(card_durations):.1f}s).")
    return VOICE_OUT, card_durations


# ---------- Image helpers ----------
def _download_image(url):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if r.status_code == 200 and r.content:
            return Image.open(BytesIO(r.content)).convert("RGB")
    except Exception as e:
        print(f"   ⚠️ image download failed: {e}")
    return None


def _vertical_gradient(size, top_rgba, bottom_rgba):
    w, h = size
    grad = Image.new("RGBA", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        grad.putpixel((0, y), tuple(int(top_rgba[i] + (bottom_rgba[i] - top_rgba[i]) * t) for i in range(4)))
    return grad.resize((w, h))


def _cover(img, size):
    tw, th = size
    iw, ih = img.size
    scale = max(tw / iw, th / ih)
    img = img.resize((int(iw * scale), int(ih * scale)), Image.LANCZOS)
    left, top = (img.width - tw) // 2, (img.height - th) // 2
    return img.crop((left, top, left + tw, top + th))


def _fit_within(img, max_w, max_h):
    iw, ih = img.size
    scale = min(max_w / iw, max_h / ih)
    return img.resize((max(int(iw * scale), 1), max(int(ih * scale), 1)), Image.LANCZOS)


def _wrap(draw, text, font, max_width):
    words, lines, cur = text.split(), [], ""
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


def _logo_badge(card, logo_img, x, y, logo_w):
    """Paste a white rounded badge containing the logo; return (badge_w, badge_h)."""
    pad = 26
    ratio = logo_w / logo_img.width
    lh = int(logo_img.height * ratio)
    logo_r = logo_img.resize((logo_w, lh), Image.LANCZOS)
    bw, bh = logo_w + pad * 2, lh + pad * 2
    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle([x, y, x + bw, y + bh], radius=24, fill=WHITE)
    card.paste(logo_r, (x + pad, y + pad), logo_r if logo_r.mode == "RGBA" else None)
    return bw, bh


# ---------- Story card ----------
def make_card(story, path, logo_img, photo=None):
    card = Image.new("RGB", (W, H), (17, 17, 17))
    if photo is None:
        photo = _download_image(story["image"]) if story.get("image") else None

    if photo is not None:
        # Blurred, darkened fill behind…
        blur = _cover(photo, (W, H)).filter(ImageFilter.GaussianBlur(45))
        blur = ImageEnhance.Brightness(blur).enhance(0.45)
        card.paste(blur, (0, 0))
        # …with the WHOLE photo shown (not cropped) on top.
        fitted = _fit_within(photo, W, 960)
        card.paste(fitted, ((W - fitted.width) // 2, 330))
    else:
        grad = _vertical_gradient((W, H), (224, 0, 0, 255), (20, 0, 0, 255)).convert("RGB")
        card.paste(grad, (0, 0))

    # Legibility overlays: light at top, heavy at bottom
    rgba = card.convert("RGBA")
    rgba = Image.alpha_composite(rgba, _vertical_gradient((W, H), (0, 0, 0, 110), (0, 0, 0, 0)))
    rgba = Image.alpha_composite(rgba, _vertical_gradient((W, H), (0, 0, 0, 0), (0, 0, 0, 245)))
    card = rgba.convert("RGB")

    # Logo
    if logo_img is not None:
        _logo_badge(card, logo_img, 60, 70, 200)
    draw = ImageDraw.Draw(card)

    # Headline (bottom)
    hfont = _font(72)
    lines = _wrap(draw, story["title"].upper(), hfont, W - 130)[:5]
    line_h = hfont.size + 10
    y = H - 320 - line_h * len(lines)
    draw.rounded_rectangle([66, y - 42, 66 + 120, y - 28], radius=6, fill=RED)
    for ln in lines:
        draw.text((66, y), ln, font=hfont, fill=WHITE)
        y += line_h

    # Footer
    draw.rectangle([0, H - 96, W, H], fill=RED)
    draw.text((66, H - 80), "@miltonkeynes_news", font=_font(40), fill=WHITE)

    card.save(path, "PNG")
    return path


# ---------- Intro / outro card (centered, no overlap) ----------
def make_title_card(kicker, big_text, subtitle, path, logo_img):
    card = Image.new("RGB", (W, H), (17, 17, 17))
    # Rich diagonal-ish red gradient
    grad = _vertical_gradient((W, H), (224, 0, 0, 255), (28, 0, 0, 255)).convert("RGB")
    card.paste(grad, (0, 0))
    draw = ImageDraw.Draw(card)

    kfont = _font(46)
    bfont = _font(86)
    sfont = _font(44, bold=False)

    # Measure logo badge
    logo_w = 320
    pad = 30
    if logo_img is not None:
        ratio = logo_w / logo_img.width
        lh = int(logo_img.height * ratio)
        badge_h = lh + pad * 2
    else:
        badge_h = 0

    big_lines = _wrap(draw, big_text, bfont, W - 160)
    gap = 46
    kicker_h = kfont.size
    big_h = (bfont.size + 14) * len(big_lines)
    sub_h = sfont.size if subtitle else 0

    total = kicker_h + gap + badge_h + gap + big_h + (gap + sub_h if subtitle else 0)
    y = (H - total) // 2

    # Kicker
    kw = draw.textlength(kicker, font=kfont)
    draw.text(((W - kw) / 2, y), kicker, font=kfont, fill=WHITE)
    y += kicker_h + gap

    # Logo badge centered
    if logo_img is not None:
        bw = logo_w + pad * 2
        _logo_badge(card, logo_img, (W - bw) // 2, y, logo_w)
        draw = ImageDraw.Draw(card)
        y += badge_h + gap

    # Red accent
    draw.rounded_rectangle([(W - 110) // 2, y - 24, (W + 110) // 2, y - 12], radius=6, fill=(255, 255, 255))

    # Big text
    for ln in big_lines:
        lw = draw.textlength(ln, font=bfont)
        draw.text(((W - lw) / 2, y), ln, font=bfont, fill=WHITE)
        y += bfont.size + 14

    # Subtitle
    if subtitle:
        y += gap - 14
        sw = draw.textlength(subtitle, font=sfont)
        draw.text(((W - sw) / 2, y), subtitle, font=sfont, fill=(255, 235, 235))

    card.save(path, "PNG")
    return path


# ---------- FFmpeg ----------
def story_query(headline):
    words = [w for w in re.findall(r"[A-Za-z]+", headline)
             if len(w) > 3 and w.lower() not in STOPWORDS]
    return " ".join(words[:2]) if words else "Milton Keynes"


def pexels_clip(query, out_path):
    """Best-effort: download a portrait stock clip for a keyword. Returns path or None."""
    if not PEXELS_API_KEY or not query:
        return None
    try:
        r = requests.get("https://api.pexels.com/videos/search",
                         headers={"Authorization": PEXELS_API_KEY},
                         params={"query": query, "orientation": "portrait",
                                 "per_page": 5, "size": "medium"}, timeout=25)
        if r.status_code != 200:
            return None
        for v in r.json().get("videos", []):
            files = [f for f in v.get("video_files", [])
                     if f.get("file_type") == "video/mp4" and f.get("link")]
            if not files:
                continue
            files.sort(key=lambda f: abs((f.get("height") or 0) - 1920))
            data = requests.get(files[0]["link"], timeout=90)
            if data.status_code == 200 and data.content:
                with open(out_path, "wb") as fh:
                    fh.write(data.content)
                print(f"   🎬 filler clip for '{query}'")
                return out_path
    except Exception as e:
        print(f"   ⚠️ Pexels '{query}': {e}")
    return None


def make_story_overlay(story, logo_img, path):
    """Transparent text layer (scrim + logo + headline + footer) for use over footage."""
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov = Image.alpha_composite(ov, _vertical_gradient((W, H), (0, 0, 0, 110), (0, 0, 0, 0)))
    ov = Image.alpha_composite(ov, _vertical_gradient((W, H), (0, 0, 0, 0), (0, 0, 0, 245)))
    if logo_img is not None:
        _logo_badge(ov, logo_img, 60, 70, 200)
    draw = ImageDraw.Draw(ov)
    hfont = _font(72)
    lines = _wrap(draw, story["title"].upper(), hfont, W - 130)[:5]
    line_h = hfont.size + 10
    y = H - 320 - line_h * len(lines)
    draw.rounded_rectangle([66, y - 42, 66 + 120, y - 28], radius=6, fill=RED)
    for ln in lines:
        draw.text((69, y + 3), ln, font=hfont, fill=(0, 0, 0, 190))  # shadow
        draw.text((66, y), ln, font=hfont, fill=WHITE)
        y += line_h
    draw.rectangle([0, H - 96, W, H], fill=RED)
    draw.text((66, H - 80), "@miltonkeynes_news", font=_font(40), fill=WHITE)
    ov.save(path)
    return path


def build_overlay_clip(bg_video, gradient_png, overlay_png, duration, out_path):
    """A clip = footage (or red gradient) with a transparent text overlay on top."""
    if bg_video and os.path.exists(bg_video):
        vf = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
              "crop=1080:1920,setsar=1,eq=brightness=-0.05[bg];"
              "[bg][1:v]overlay=0:0,format=yuv420p[v]")
        cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", bg_video, "-i", overlay_png,
               "-filter_complex", vf, "-map", "[v]", "-an", "-r", str(FPS),
               "-t", f"{duration:.3f}", "-preset", "veryfast", out_path]
    else:
        vf = "[0:v][1:v]overlay=0:0,format=yuv420p[v]"
        cmd = ["ffmpeg", "-y", "-loop", "1", "-t", f"{duration:.3f}", "-i", gradient_png,
               "-i", overlay_png, "-filter_complex", vf, "-map", "[v]", "-an",
               "-r", str(FPS), "-preset", "veryfast", out_path]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def _clip_from_card(card_path, duration, out_path, zoom_in=True):
    frames = max(int(duration * FPS), 1)
    z = f"min(zoom+0.00035,{ZOOM_MAX})" if zoom_in else f"if(eq(on,1),{ZOOM_MAX},max(zoom-0.00035,1.0))"
    vf = (
        f"scale={int(W*1.08)}:{int(H*1.08)},"
        f"zoompan=z='{z}':d={frames}:s={W}x{H}:fps={FPS}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',format=yuv420p"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", card_path, "-vf", vf,
         "-frames:v", str(frames), "-r", str(FPS), "-preset", "veryfast", "-an", out_path],
        check=True, capture_output=True,
    )
    return out_path


def mux(clips, audio_path, out_path, music_path=None):
    with open("video_list.txt", "w") as f:
        for c in clips:
            f.write(f"file '{c}'\n")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "video_list.txt",
                    "-c", "copy", "silent.mp4"], check=True, capture_output=True)
    print("🎚️ Muxing audio...")
    have_music = music_path and os.path.exists(music_path)
    cmd = ["ffmpeg", "-y", "-i", "silent.mp4", "-i", audio_path]
    if have_music:
        cmd += ["-stream_loop", "-1", "-i", music_path,
                "-filter_complex", "[2:a]volume=0.10[m];[1:a][m]amix=inputs=2:duration=first:dropout_transition=2[a]",
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out_path]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"✅ Saved {out_path}")
    return out_path


def assemble(card_paths, durations, audio_path, out_path, music_path=None):
    print("🎞️ Rendering clips...")
    clips = []
    for i, (cp, d) in enumerate(zip(card_paths, durations)):
        clip = f"clip_{i}.mp4"
        _clip_from_card(cp, d, clip, zoom_in=(i % 2 == 0))
        clips.append(clip)

    with open("video_list.txt", "w") as f:
        for c in clips:
            f.write(f"file '{c}'\n")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "video_list.txt",
                    "-c", "copy", "silent.mp4"], check=True, capture_output=True)

    print("🎚️ Muxing audio...")
    have_music = music_path and os.path.exists(music_path)
    cmd = ["ffmpeg", "-y", "-i", "silent.mp4", "-i", audio_path]
    if have_music:
        cmd += ["-stream_loop", "-1", "-i", music_path,
                "-filter_complex", "[2:a]volume=0.10[m];[1:a][m]amix=inputs=2:duration=first:dropout_transition=2[a]",
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", out_path]
    subprocess.run(cmd, check=True, capture_output=True)
    print(f"✅ Saved {out_path}")
    return out_path


# ---------- Main ----------
def main():
    os.makedirs(CARD_DIR, exist_ok=True)

    stories = get_today_stories()
    if not stories:
        print("❌ No stories. Exiting.")
        return []

    hook, story_lines, outro = write_script_parts(stories)
    segment_texts = [hook] + story_lines + [outro]

    with open(SCRIPT_OUT, "w", encoding="utf-8") as f:
        f.write(hook + "\n\n" + "\n\n".join(story_lines) + "\n\n" + outro)
    print("\n----- SCRIPT -----\n" + hook)
    for s in story_lines:
        print(" • " + s)
    print(outro + "\n------------------\n")

    voice, card_durations = build_narration(segment_texts)

    # Logo
    li = _download_image(LOGO_URL)
    logo_img = li.convert("RGBA") if li is not None else None
    os.makedirs(CLIP_DIR, exist_ok=True)

    n = len(stories)
    noun = "THING" if n == 1 else "THINGS"
    clips = []

    # Intro clip
    intro_png = make_title_card("MILTON KEYNES NEWS", f"{n} {noun} TODAY",
                                datetime.now().strftime("%A %d %B"),
                                os.path.join(CARD_DIR, "intro.png"), logo_img)
    clips.append(_clip_from_card(intro_png, card_durations[0], "clip_0.mp4", zoom_in=True))

    # Story clips — prefer the article's own photo; Pexels footage only as filler
    for i, s in enumerate(stories):
        d = card_durations[1 + i]
        out = f"clip_{1 + i}.mp4"
        photo = _download_image(s["image"]) if s.get("image") else None
        if photo is not None:
            card = make_card(s, os.path.join(CARD_DIR, f"story_{i}.png"), logo_img, photo=photo)
            _clip_from_card(card, d, out, zoom_in=(i % 2 == 0))
        else:
            overlay = make_story_overlay(s, logo_img, os.path.join(CARD_DIR, f"story_{i}_ov.png"))
            grad = os.path.join(CARD_DIR, f"story_{i}_grad.png")
            _vertical_gradient((W, H), (224, 0, 0, 255), (20, 0, 0, 255)).convert("RGB").save(grad)
            bg = (pexels_clip(story_query(s["title"]), os.path.join(CLIP_DIR, f"story_{i}.mp4"))
                  or pexels_clip("Milton Keynes England", os.path.join(CLIP_DIR, f"story_{i}.mp4")))
            build_overlay_clip(bg, grad, overlay, d, out)
        clips.append(out)

    # Outro clip
    outro_png = make_title_card("THANKS FOR WATCHING", "FOLLOW FOR MORE", "@miltonkeynes_news",
                                os.path.join(CARD_DIR, "outro.png"), logo_img)
    clips.append(_clip_from_card(outro_png, card_durations[-1], f"clip_{len(clips)}.mp4", zoom_in=False))

    mux(clips, voice, VIDEO_OUT, music_path=MUSIC_FILE if os.path.exists(MUSIC_FILE) else None)
    print("\n🎬 Reel built: reel.mp4")
    return stories


if __name__ == "__main__":
    main()
