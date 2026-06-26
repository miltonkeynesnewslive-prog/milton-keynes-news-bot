import os
import re
import time
import feedparser
import requests
import smtplib
from html import escape as html_escape
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

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

# === GITHUB CONFIGURATION ===
GITHUB_TOKEN = os.environ.get("APPROVAL_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY")
APPROVAL_FILE = "approved.txt"
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


def fetch_latest_news():
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
        return None

    def entry_time(entry):
        t = entry.get("published_parsed") or entry.get("updated_parsed")
        try:
            return time.mktime(t) if t else 0
        except Exception:
            return 0

    all_entries.sort(key=entry_time, reverse=True)
    latest = all_entries[0]
    print(f"✅ Newest across all feeds: {latest.get('title', 'Untitled')}")
    return {
        "title": latest.get("title", "Milton Keynes News"),
        "content": latest.get("summary", latest.get("description", "")),
        "link": latest.get("link", ""),
        "published": latest.get("published", ""),
        "image": get_article_image(latest),
        "credit": get_image_credit(latest),
    }


# === STEP 2: Generate headline and caption with AI ===
def generate_with_ai(article):
    print("🤖 Generating headline and caption with AI...")
    if not OPENAI_API_KEY:
        print("⚠️ No OpenAI API key found. Using fallback text.")
        return {
            "headline": article["title"][:60],
            "caption": f"{article['title']}\n\nRead more: {article['link']} #MiltonKeynesNews",
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
                        "content": "You are a social media assistant. Create a short headline (max 8 words) and an engaging Instagram caption (under 150 words) with emojis. Format your response as: HEADLINE: ... CAPTION: ...",
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


# === STEP 3: Create a branded news graphic ===
def create_image(headline, image_url=None, credit=""):
    """Build a branded news graphic (article photo + logo + headline) via htmlcsstoimage.com."""
    print("🖼️ Creating branded image...")

    clean_headline = strip_emojis(headline) or "Milton Keynes News"
    # If the article had no photo, fall back to a dark branded background.
    bg = image_url or "https://placehold.co/1080x1080/111111/111111.png"

    html = f"""
    <div class="card">
      <div class="photo-blur" style="background-image:url('{bg}')"></div>
      <div class="photo" style="background-image:url('{bg}')"></div>
      <div class="overlay"></div>
      <div class="topbar">
        <div class="logo-badge"><img src="{LOGO_URL}" /></div>
      </div>
      <div class="bottom">
        <div class="accent"></div>
        <div class="headline">{html_escape(clean_headline)}</div>
      </div>
      <div class="credit">{html_escape(credit or "")}</div>
      <div class="footer"><span>@miltonkeynes_news</span></div>
    </div>
    """

    css = """
    * { margin:0; padding:0; box-sizing:border-box; font-family:'Oswald', sans-serif; }
    .card { position:relative; width:1080px; height:1080px; overflow:hidden; background:#111; }
    .photo-blur { position:absolute; top:0; left:0; right:0; bottom:0; background-size:cover; background-position:center; filter:blur(28px) brightness(0.55); transform:scale(1.12); }
    .photo { position:absolute; top:0; left:0; right:0; bottom:0; background-size:contain; background-repeat:no-repeat; background-position:center; }
    .overlay { position:absolute; top:0; left:0; right:0; bottom:0;
      background:linear-gradient(to bottom, rgba(0,0,0,0.10) 0%, rgba(0,0,0,0) 32%, rgba(0,0,0,0.60) 60%, rgba(0,0,0,0.97) 100%); }
    .topbar { position:absolute; top:42px; left:42px; }
    .logo-badge { background:#ffffff; border-radius:18px; padding:18px 24px; box-shadow:0 8px 22px rgba(0,0,0,0.35); }
    .logo-badge img { height:72px; width:auto; object-fit:contain; display:block; }
    .bottom { position:absolute; left:54px; right:54px; bottom:108px; }
    .accent { width:96px; height:11px; background:#cc0000; border-radius:6px; margin-bottom:26px; }
    .headline { color:#ffffff; font-weight:700; font-size:70px; line-height:1.08; text-transform:uppercase;
      text-shadow:0 3px 16px rgba(0,0,0,0.65);
      display:-webkit-box; -webkit-line-clamp:4; -webkit-box-orient:vertical; overflow:hidden; }
    .credit { position:absolute; right:30px; bottom:80px; color:rgba(255,255,255,0.65); font-size:22px; font-weight:300; }
    .footer { position:absolute; left:0; right:0; bottom:0; height:64px; background:#cc0000;
      display:flex; align-items:center; padding:0 54px; }
    .footer span { color:#ffffff; font-size:30px; font-weight:500; letter-spacing:1px; }
    """

    try:
        if not HTML_CSS_API_KEY or not HTML_CSS_USER_ID:
            raise ValueError("htmlcsstoimage credentials missing")
        resp = requests.post(
            "https://hcti.io/v1/image",
            auth=(HTML_CSS_USER_ID, HTML_CSS_API_KEY),
            data={
                "html": html,
                "css": css,
                "google_fonts": "Oswald",
                "selector": ".card",
                "viewport_width": 1080,
                "viewport_height": 1080,
                "device_scale": 1,
                "ms_delay": 600,
            },
            timeout=60,
        )
        if resp.status_code in (200, 201):
            url = resp.json().get("url")
            if url:
                print(f"✅ Branded image created: {url}")
                return url
        print(f"⚠️ Image API error {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"⚠️ Image generation failed: {e}")

    # Fallback: simple placeholder so the bot never fully breaks.
    print("↩️ Falling back to placeholder image.")
    encoded = requests.utils.quote(f"MK NEWS | {clean_headline}")
    return f"https://placehold.co/1080x1080/cc0000/ffffff?text={encoded}"


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

    article = fetch_latest_news()
    if not article:
        print("❌ No article found. Exiting.")
        return

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
    full_caption = f"{ai_content['caption']}\n\nRead more: {article['link']}"
    post_to_instagram(image_url, full_caption)


if __name__ == "__main__":
    main()
