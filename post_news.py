import os
import re
import time
import json
import base64
import feedparser
import requests
import smtplib
from io import BytesIO
from html import escape as html_escape
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

# === CONFIGURATION ===
INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_BUSINESS_ID = os.environ.get("INSTAGRAM_BUSINESS_ID")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")
RSS_FEEDS = [
    "https://www.miltonkeynes.co.uk/news/rss",
    "https://www.milton-keynes.gov.uk/news/rss.xml",
    # Police/crime news via Google News (the police site itself is behind a bot wall):
    "https://news.google.com/rss/search?q=Thames+Valley+Police+Milton+Keynes&hl=en-GB&gl=GB&ceid=GB:en",
]

# === IMAGE / BRANDING CONFIGURATION ===
HTML_CSS_API_KEY = os.environ.get("HTML_CSS_API_KEY")
HTML_CSS_USER_ID = os.environ.get("HTML_CSS_USER_ID")
# This logo file must be committed to the repo root so this raw URL works.
LOGO_URL = "https://raw.githubusercontent.com/miltonkeynesnewslive-prog/milton-keynes-news-bot/main/MK%20News%20Logo.png"

# Hashtags: 2 core tags always, plus a rotating pool so every post differs.
CORE_HASHTAGS = ["#MiltonKeynes", "#MKNews"]
ROTATING_HASHTAGS = [
    "#MiltonKeynesNews", "#Buckinghamshire", "#BucksNews", "#ThamesValley",
    "#LocalNews", "#MKCommunity", "#Bletchley", "#StonyStratford",
    "#Wolverton", "#NewportPagnell", "#CentralMK", "#MKLife",
]

# === GITHUB CONFIGURATION ===
GITHUB_TOKEN = os.environ.get("APPROVAL_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY")
APPROVAL_FILE = "approved.txt"
POSTED_FILE = "posted.json"
PIPEDREAM_URL = "https://eomj13e55tyupi0.m.pipedream.net"


# === HELPERS ===
def strip_emojis(text):
    """Remove emojis so the headline overlay renders cleanly (no boxes)."""
    if not text:
        return ""
    emoji_pattern = re.compile(
        "["
        "\U0001F000-\U0001FAFF"
        "\U00002600-\U000027BF"
        "\U0001F1E6-\U0001F1FF"
        "\U00002190-\U000021FF"
        "\U00002B00-\U00002BFF"
        "\uFE0F"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text).strip()


def get_article_image(entry):
    """Pull the article's own photo URL from the RSS entry."""
    try:
        if getattr(entry, "media_content", None):
            url = entry.media_content[0].get("url")
            if url:
                return url
    except Exception:
        pass
    try:
        if getattr(entry, "media_thumbnail", None):
            url = entry.media_thumbnail[0].get("url")
            if url:
                return url
    except Exception:
        pass
    for link in entry.get("links", []):
        if link.get("rel") == "enclosure" and "image" in link.get("type", ""):
            return link.get("href")
    match = re.search(r'<img[^>]+src="([^"]+)"', entry.get("summary", ""))
    if match:
        return match.group(1)
    return None


def get_image_credit(entry):
    """Best-effort photo credit for the corner of the graphic (blank if none)."""
    try:
        credit = entry.get("media_credit")
        if isinstance(credit, list) and credit:
            name = credit[0].get("content", "").strip()
            if name:
                return f"Photo: {name}"
    except Exception:
        pass
    return ""


# === STEP 1: Fetch the latest news ===
def load_feed(url):
    """Fetch a feed with a browser-style request, then parse it.

    Some sites block GitHub's data-centre IP range and return 403, or block
    feedparser's default request. We try a direct browser-style fetch first,
    then a public proxy (for IP-blocked sites), then feedparser directly.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }

    # 1) Direct fetch
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200 and resp.content:
            feed = feedparser.parse(resp.content)
            if feed.entries:
                return feed
        else:
            print(f"   ⚠️ HTTP {resp.status_code} from {url}")
    except Exception as e:
        print(f"   ⚠️ Direct fetch failed for {url}: {e}")

    # 2) Proxy fetch (for sites that block data-centre IPs, e.g. police)
    try:
        proxied = "https://api.allorigins.win/raw?url=" + requests.utils.quote(url, safe="")
        print(f"   ↪️ Retrying via proxy...")
        presp = requests.get(proxied, headers=headers, timeout=45)
        if presp.status_code == 200 and presp.content:
            feed = feedparser.parse(presp.content)
            if feed.entries:
                print(f"   ✅ Proxy worked for {url}")
                return feed
        else:
            print(f"   ⚠️ Proxy HTTP {presp.status_code} for {url}")
    except Exception as e:
        print(f"   ⚠️ Proxy fetch failed for {url}: {e}")

    # 3) Last resort: let feedparser fetch it directly.
    return feedparser.parse(url)


def _entry_time(entry):
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    try:
        return time.mktime(t) if t else 0
    except Exception:
        return 0


def fetch_news_candidates():
    """Return every article from all feeds, newest first, as a list of dicts."""
    print("📰 Fetching latest news from all sources...")
    all_entries = []
    for url in RSS_FEEDS:
        try:
            feed = load_feed(url)
            count = len(feed.entries)
            if count:
                print(f"   ✅ {count} entries from {url}")
                all_entries.extend(feed.entries)
            else:
                print(f"   ⚠️ No entries from {url}")
        except Exception as e:
            print(f"   ❌ Error reading {url}: {e}")

    if not all_entries:
        print("❌ No articles found in any feed.")
        return []

    all_entries.sort(key=_entry_time, reverse=True)
    candidates = []
    for e in all_entries:
        candidates.append({
            "title": e.get("title", "Milton Keynes News"),
            "content": e.get("summary", e.get("description", "")),
            "link": e.get("link", ""),
            "published": e.get("published", ""),
            "image": get_article_image(e),
            "credit": get_image_credit(e),
        })
    return candidates


# === Posted-history (so the same story is never offered twice) ===
def load_posted():
    """Return (list_of_posted_links, sha) from posted.json in the repo."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return [], None
    try:
        owner, repo = GITHUB_REPO.split('/')
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{POSTED_FILE}"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        }
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            data = r.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            return json.loads(content), data["sha"]
        return [], None
    except Exception as e:
        print(f"⚠️ Could not load posted history: {e}")
        return [], None


def save_posted(links, sha):
    """Write the posted-links list back to posted.json (keeps the last 200)."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return
    try:
        owner, repo = GITHUB_REPO.split('/')
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{POSTED_FILE}"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        }
        trimmed = links[-200:]
        content = base64.b64encode(
            json.dumps(trimmed, indent=2).encode("utf-8")
        ).decode("utf-8")
        payload = {"message": "Update posted history", "content": content}
        if sha:
            payload["sha"] = sha
        r = requests.put(url, headers=headers, json=payload)
        if r.status_code in (200, 201):
            print("📝 Updated posted history.")
        else:
            print(f"⚠️ Could not save posted history ({r.status_code}): {r.text[:150]}")
    except Exception as e:
        print(f"⚠️ Could not save posted history: {e}")


# === STEP 2: Generate headline and caption with AI ===
def generate_with_ai(article):
    print("🤖 Generating headline and caption with AI...")
    if not OPENAI_API_KEY:
        print("⚠️ No OpenAI API key found. Using fallback text.")
        return {
            "headline": article["title"][:60],
            "caption": article["title"],
        }
    try:
        response = requests.post(
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
                            "You are a local news editor for a Milton Keynes Instagram page writing for real "
                            "MK residents. Write a short factual headline (max 8 words) and a concise caption "
                            "(under 90 words). "
                            "Lead with the concrete facts — what happened, where in Milton Keynes, and when — "
                            "in plain, specific language. Do NOT sensationalise: avoid hype like 'chaos erupted', "
                            "'utter mayhem', or vague teasers. At most one or two subtle emojis. "
                            "Do NOT include any links, URLs, or 'read more'. "
                            "End the caption with ONE genuine, easy-to-answer question that invites locals to "
                            "comment, referencing the specific area where possible "
                            "(e.g. 'Were you near <area> when this happened?'). "
                            "Then on a new line add 3-4 hashtags specific to THIS story "
                            "(topic and neighbourhood), not generic filler. "
                            "Format your response exactly as: HEADLINE: ... CAPTION: ..."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Create content for this news article:\nHeadline: {article['title']}\nContent: {article['content']}",
                    },
                ],
            },
            timeout=30,
        )
        if response.status_code == 200:
            result = response.json()
            text = result["choices"][0]["message"]["content"]
            headline = "MK News"
            caption = text
            if "HEADLINE:" in text and "CAPTION:" in text:
                parts = text.split("CAPTION:")
                headline_part = parts[0].replace("HEADLINE:", "").strip()
                headline = headline_part[:60]
                caption = parts[1].strip()
            print("✅ AI generation complete.")
            return {"headline": headline, "caption": caption}
        else:
            print(f"⚠️ AI API error: {response.status_code}")
            return {"headline": article["title"][:60], "caption": article["title"]}
    except Exception as e:
        print(f"⚠️ AI generation failed: {e}")
        return {"headline": article["title"][:60], "caption": article["title"]}


def finalize_caption(caption):
    """Strip stray links, then build a tight, rotating hashtag set (~5-6 total)."""
    import random
    caption = re.sub(r"(?im)^\s*read more.*$", "", caption)
    caption = re.sub(r"https?://\S+", "", caption).strip()

    # Pull the AI's story-specific hashtags, then remove them from the body so
    # we control the final block.
    ai_tags, seen = [], set()
    for h in re.findall(r"#\w+", caption):
        low = h.lower()
        if low not in seen:
            seen.add(low)
            ai_tags.append(h)
    caption = re.sub(r"#\w+", "", caption).strip()
    caption = re.sub(r"[ \t]+\n", "\n", caption)
    caption = re.sub(r"\n{3,}", "\n\n", caption).strip()

    # Build final tags: core + up to 3 AI topical + 1 rotating pool tag.
    final, used = [], set()
    for h in CORE_HASHTAGS:
        final.append(h)
        used.add(h.lower())
    for h in ai_tags:
        if len(final) >= 5:
            break
        if h.lower() not in used:
            final.append(h)
            used.add(h.lower())
    pool = [h for h in ROTATING_HASHTAGS if h.lower() not in used]
    if pool:
        final.append(random.choice(pool))

    return (caption.rstrip() + "\n\n" + " ".join(final)).strip()


# === STEP 3: Create a branded news graphic (free, local, via Pillow) ===
IMG_W, IMG_H = 1080, 1350   # 4:5 feed post
HOST_IMG_PATH = "posts/latest.png"


def _img_font(size, bold=True):
    for p in ("oswald.ttf", "Oswald.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    base = "/usr/share/fonts/truetype/dejavu/"
    try:
        return ImageFont.truetype(base + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), size)
    except Exception:
        return ImageFont.load_default()


def _img_download(url):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        if r.status_code == 200 and r.content:
            return Image.open(BytesIO(r.content)).convert("RGB")
    except Exception:
        pass
    return None


def _img_vgrad(size, top, bottom):
    w, h = size
    g = Image.new("RGBA", (1, h))
    for y in range(h):
        f = y / max(h - 1, 1)
        g.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * f) for i in range(4)))
    return g.resize((w, h))


def _img_cover(img, size):
    tw, th = size
    iw, ih = img.size
    s = max(tw / iw, th / ih)
    img = img.resize((int(iw * s), int(ih * s)), Image.LANCZOS)
    l, t = (img.width - tw) // 2, (img.height - th) // 2
    return img.crop((l, t, l + tw, t + th))


def _img_fit(img, mw, mh):
    iw, ih = img.size
    s = min(mw / iw, mh / ih)
    return img.resize((max(int(iw * s), 1), max(int(ih * s), 1)), Image.LANCZOS)


def _img_wrap(draw, text, font, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _render_card(headline, image_url=None, credit=""):
    """Build the branded news card (matches the style you liked) with Pillow."""
    W, H = IMG_W, IMG_H
    RED = (204, 0, 0)
    WHITE = (255, 255, 255)
    card = Image.new("RGB", (W, H), (17, 17, 17))
    photo = _img_download(image_url) if image_url else None

    if photo is not None:
        blur = _img_cover(photo, (W, H)).filter(ImageFilter.GaussianBlur(40))
        blur = ImageEnhance.Brightness(blur).enhance(0.45)
        card.paste(blur, (0, 0))
        fitted = _img_fit(photo, W, int(H * 0.62))
        card.paste(fitted, ((W - fitted.width) // 2, 250))
    else:
        # Branded red gradient
        card.paste(_img_vgrad((W, H), (224, 0, 0, 255), (26, 0, 0, 255)).convert("RGB"), (0, 0))

    # Legibility overlays
    rgba = card.convert("RGBA")
    rgba = Image.alpha_composite(rgba, _img_vgrad((W, H), (0, 0, 0, 110), (0, 0, 0, 0)))
    rgba = Image.alpha_composite(rgba, _img_vgrad((W, H), (0, 0, 0, 0), (0, 0, 0, 240)))
    card = rgba.convert("RGB")
    draw = ImageDraw.Draw(card)

    # Faint MK watermark (only on the no-photo branded look)
    if photo is None:
        wm = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        wd = ImageDraw.Draw(wm)
        wf = _img_font(440)
        wd.text((W - 470, H - 640), "MK", font=wf, fill=(255, 255, 255, 20))
        card = Image.alpha_composite(card.convert("RGBA"), wm).convert("RGB")
        draw = ImageDraw.Draw(card)

    # Logo badge
    logo = _img_download(LOGO_URL)
    if logo is not None:
        logo = logo.convert("RGBA")
        lw = 200
        lr = lw / logo.width
        lh = int(logo.height * lr)
        logo_r = logo.resize((lw, lh), Image.LANCZOS)
        pad = 22
        draw.rounded_rectangle([54, 54, 54 + lw + pad * 2, 54 + lh + pad * 2], radius=20, fill=WHITE)
        card.paste(logo_r, (54 + pad, 54 + pad), logo_r)
        draw = ImageDraw.Draw(card)

    # Headline (bottom)
    clean = strip_emojis(headline) or "Milton Keynes News"
    hfont = _img_font(72)
    lines = _img_wrap(draw, clean.upper(), hfont, W - 130)[:5]
    line_h = hfont.size + 10
    y = H - 200 - line_h * len(lines)
    draw.rounded_rectangle([60, y - 44, 60 + 120, y - 30], radius=6, fill=RED)
    for ln in lines:
        draw.text((63, y + 3), ln, font=hfont, fill=(0, 0, 0))
        draw.text((60, y), ln, font=hfont, fill=WHITE)
        y += line_h

    # Credit
    if credit:
        cf = _img_font(24, bold=False)
        cw = draw.textlength(credit, font=cf)
        draw.text((W - cw - 30, H - 150), credit, font=cf, fill=(230, 230, 230))

    # Footer
    draw.rectangle([0, H - 88, W, H], fill=RED)
    draw.text((60, H - 72), "@miltonkeynes_news", font=_img_font(38), fill=WHITE)

    out = "post_image.png"
    card.save(out, "PNG")
    return out


def _host_image(path):
    """Commit the image into the repo and return its public raw URL."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return None
    try:
        owner, repo = GITHUB_REPO.split("/")
        api = f"https://api.github.com/repos/{owner}/{repo}/contents/{HOST_IMG_PATH}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
        sha = None
        r = requests.get(api, headers=headers)
        if r.status_code == 200:
            sha = r.json().get("sha")
        with open(path, "rb") as f:
            content = base64.b64encode(f.read()).decode("utf-8")
        payload = {"message": "Update post image", "content": content, "branch": "main"}
        if sha:
            payload["sha"] = sha
        r = requests.put(api, headers=headers, json=payload)
        if r.status_code in (200, 201):
            url = r.json()["content"]["download_url"]
            print(f"✅ Image hosted: {url}")
            return url
        print(f"⚠️ Image hosting failed ({r.status_code}): {r.text[:150]}")
    except Exception as e:
        print(f"⚠️ Image hosting error: {e}")
    return None


def create_image(headline, image_url=None, credit=""):
    """Generate the branded card locally (free) and host it for Instagram."""
    print("🖼️ Creating branded image (Pillow)...")
    try:
        path = _render_card(headline, image_url, credit)
        url = _host_image(path)
        if url:
            return url
    except Exception as e:
        print(f"⚠️ Local image generation failed: {e}")
    # Last-resort fallback so the bot never fully breaks.
    print("↩️ Falling back to placeholder image.")
    clean = strip_emojis(headline) or "Milton Keynes News"
    encoded = requests.utils.quote(f"MK NEWS | {clean}")
    return f"https://placehold.co/1080x1350/cc0000/ffffff?text={encoded}"


# === STEP 4: Post to Instagram ===
def post_to_instagram(image_url, caption):
    print("📸 Posting to Instagram...")
    if not INSTAGRAM_ACCESS_TOKEN or not INSTAGRAM_BUSINESS_ID:
        print("❌ Instagram credentials missing!")
        return False

    try:
        # Step 1: Upload the image
        upload_url = f"https://graph.facebook.com/v20.0/{INSTAGRAM_BUSINESS_ID}/media"
        data = {
            "access_token": INSTAGRAM_ACCESS_TOKEN,
            "image_url": image_url,
            "caption": caption,
        }

        print("📤 Uploading image...")
        response = requests.post(upload_url, data=data)

        if response.status_code != 200:
            print(f"❌ Upload failed: {response.text}")
            return False

        upload_data = response.json()
        creation_id = upload_data.get("id")

        if not creation_id:
            print(f"❌ No creation ID: {upload_data}")
            return False

        print(f"✅ Media container created with ID: {creation_id}")

        # Step 2: Wait for Instagram to process the image
        print("⏳ Waiting 10 seconds for Instagram to process the image...")
        time.sleep(10)

        # Step 3: Publish the post
        print("📤 Publishing...")
        publish_url = f"https://graph.facebook.com/v20.0/{INSTAGRAM_BUSINESS_ID}/media_publish"
        publish_response = requests.post(
            publish_url,
            data={
                "access_token": INSTAGRAM_ACCESS_TOKEN,
                "creation_id": creation_id,
            },
        )

        if publish_response.status_code == 200:
            print("✅ Post published successfully!")
            return True
        else:
            print(f"❌ Publish failed: {publish_response.text}")
            return False

    except Exception as e:
        print(f"❌ Posting error: {e}")
        return False


# === STEP 5: Send approval email ===
def send_approval_email(headline, caption, link):
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("❌ Email credentials missing. Skipping approval.")
        return False

    approval_link = PIPEDREAM_URL
    body = f"""
    <html>
    <body>
        <h2>📰 News Draft for Approval</h2>
        <p><strong>Headline:</strong> {headline}</p>
        <p><strong>Caption:</strong> {caption}</p>
        <p><strong>Link:</strong> <a href="{link}">{link}</a></p>
        <hr>
        <p><strong>Click the link below to approve and publish:</strong></p>
        <p><a href="{approval_link}" style="display:inline-block;background:#cc0000;color:white;padding:10px 20px;text-decoration:none;border-radius:5px;">✅ Approve & Publish</a></p>
        <p><small>You have 10 minutes to approve.</small></p>
    </body>
    </html>
    """

    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECEIVER
    msg['Subject'] = f"📰 News Approval Needed: {headline[:40]}..."
    msg.attach(MIMEText(body, 'html'))

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        print("✅ Approval email sent!")
        return True
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return False


# === STEP 6: Approval helpers (single-use approved.txt) ===
def get_approval_sha():
    """Return the sha of approved.txt if it exists in the repo, else None."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return "local" if os.path.exists(APPROVAL_FILE) else None
    try:
        owner, repo = GITHUB_REPO.split('/')
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{APPROVAL_FILE}"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        }
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get("sha")
        return None
    except Exception as e:
        print(f"⚠️ GitHub check failed: {e}")
        return None


def check_approval_in_github():
    return get_approval_sha() is not None


def clear_approval():
    """Delete approved.txt so each approval can only ever be used once."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        if os.path.exists(APPROVAL_FILE):
            try:
                os.remove(APPROVAL_FILE)
            except Exception:
                pass
        return
    sha = get_approval_sha()
    if not sha:
        return  # nothing to clear
    try:
        owner, repo = GITHUB_REPO.split('/')
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{APPROVAL_FILE}"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        }
        response = requests.delete(
            url,
            headers=headers,
            json={"message": "Consume approval (auto-cleared by bot)", "sha": sha},
        )
        if response.status_code in (200, 201):
            print("🧹 Cleared approved.txt — approval consumed.")
        else:
            print(f"⚠️ Could not clear approval ({response.status_code}): {response.text[:150]}")
    except Exception as e:
        print(f"⚠️ Could not clear approval: {e}")


# === STEP 7: Wait for approval ===
def wait_for_approval():
    print("⏳ Waiting for approval...")
    print(f"📧 Check your inbox at: {EMAIL_RECEIVER}")
    print("🔗 Click the approval link in the email.")

    for attempt in range(20):
        time.sleep(30)
        print(f"   Waiting... {attempt+1}/20")
        if check_approval_in_github():
            return True

    print("⏰ Approval timeout. Skipping post.")
    return False


# === MAIN ===
def main():
    print("🚀 Starting Milton Keynes News Bot...")
    print(f"⏰ Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if os.environ.get("APPROVE") == "yes":
        print("✅ Approval received via workflow input. Posting directly...")
    else:
        print("ℹ️ No approval provided. Will wait for email approval.")

    # Load history and pick the newest story we haven't posted yet.
    posted_links, posted_sha = load_posted()
    print(f"🗂️ {len(posted_links)} stories in posted history.")

    candidates = fetch_news_candidates()
    if not candidates:
        print("❌ No articles found. Exiting.")
        return

    article = next(
        (c for c in candidates if c["link"] and c["link"] not in posted_links),
        None,
    )
    if not article:
        print("✅ No new (unposted) stories right now. Nothing to do.")
        return
    print(f"📌 Selected newest unposted: {article['title']}")

    ai_content = generate_with_ai(article)
    print(f"📝 Headline: {ai_content['headline']}")

    if os.environ.get("APPROVE") != "yes":
        # Remove any leftover approval so only a fresh click counts this run.
        clear_approval()
        if send_approval_email(ai_content["headline"], ai_content["caption"], article["link"]):
            print("📧 Approval email sent. Waiting for your response...")
            if not wait_for_approval():
                print("❌ Not approved. Skipping post.")
                return
            # Approval granted — consume it immediately so it can't be reused.
            clear_approval()
        else:
            print("❌ Could not send approval email. Exiting.")
            return

    print("✅ Approved! Publishing...")
    image_url = create_image(
        ai_content["headline"],
        article.get("image"),
        article.get("credit", ""),
    )
    full_caption = finalize_caption(ai_content["caption"])
    success = post_to_instagram(image_url, full_caption)

    # Only record it as posted if it actually published — so a failed post
    # can be retried next run, and a successful one is never offered again.
    if success and article.get("link"):
        posted_links.append(article["link"])
        save_posted(posted_links, posted_sha)
    elif not success:
        print("⚠️ Post did not publish — not recording it, will retry next run.")


if __name__ == "__main__":
    main()
