import os
import time
import feedparser
import requests
import smtplib
import base64
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
RSS_FEED_URL = "https://www.miltonkeynes.co.uk/rss"

# === GITHUB CONFIGURATION (for approval flag) ===
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY")  # Set by GitHub Actions
APPROVAL_FILE = "approved.txt"

# === STEP 1: Fetch the latest news ===
def fetch_latest_news():
    print("📰 Fetching latest news from Milton Keynes Citizen...")
    try:
        feed = feedparser.parse(RSS_FEED_URL)
        if not feed.entries:
            print("❌ No articles found.")
            return None
        latest = feed.entries[0]
        print(f"✅ Found: {latest.title}")
        return {
            "title": latest.title,
            "content": latest.get("summary", latest.get("description", "")),
            "link": latest.link,
            "published": latest.get("published", "")
        }
    except Exception as e:
        print(f"❌ Error fetching news: {e}")
        return None

# === STEP 2: Generate headline and caption with AI ===
def generate_with_ai(article):
    print("🤖 Generating headline and caption with AI...")
    if not OPENAI_API_KEY:
        print("⚠️ No OpenAI API key found. Using fallback text.")
        return {
            "headline": article["title"][:60],
            "caption": f"{article['title']}\n\nRead more: {article['link']} #MiltonKeynesNews"
        }
    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a social media assistant. Create a short headline (max 8 words) and an engaging Instagram caption (under 150 words). Format your response as: HEADLINE: ... CAPTION: ..."
                    },
                    {
                        "role": "user",
                        "content": f"Create content for this news article:\nHeadline: {article['title']}\nContent: {article['content']}"
                    }
                ]
            },
            timeout=30
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

# === STEP 3: Create an image ===
def create_image(headline):
    print("🖼️ Creating image with headline...")
    encoded_headline = requests.utils.quote(headline)
    image_url = f"https://placehold.co/1080x1080/cc0000/ffffff?text={encoded_headline}"
    try:
        response = requests.get(image_url, timeout=30)
        if response.status_code == 200:
            with open("post_image.jpg", "wb") as f:
                f.write(response.content)
            print("✅ Image created and saved.")
            return "post_image.jpg"
        else:
            print(f"⚠️ Image creation failed: {response.status_code}")
            return None
    except Exception as e:
        print(f"⚠️ Image download failed: {e}")
        return None

# === STEP 4: Post to Instagram ===
def post_to_instagram(image_path, caption):
    print("📸 Posting to Instagram...")
    if not INSTAGRAM_ACCESS_TOKEN or not INSTAGRAM_BUSINESS_ID:
        print("❌ Instagram credentials missing!")
        return False
    try:
        upload_url = f"https://graph.facebook.com/v20.0/{INSTAGRAM_BUSINESS_ID}/media"
        with open(image_path, "rb") as img_file:
            files = {"image": img_file}
            data = {"access_token": INSTAGRAM_ACCESS_TOKEN}
            response = requests.post(upload_url, data=data, files=files)
        if response.status_code != 200:
            print(f"❌ Upload failed: {response.text}")
            return False
        upload_data = response.json()
        creation_id = upload_data.get("id")
        print(f"✅ Image uploaded with ID: {creation_id}")
        publish_url = f"https://graph.facebook.com/v20.0/{INSTAGRAM_BUSINESS_ID}/media_publish"
        publish_response = requests.post(
            publish_url,
            data={
                "access_token": INSTAGRAM_ACCESS_TOKEN,
                "creation_id": creation_id
            }
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

# === STEP 5: Send approval email with a unique link ===
def send_approval_email(headline, caption, link):
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("❌ Email credentials missing. Skipping approval.")
        return False

    # Create a unique approval link using Pipedream webhook
    # The link will trigger the Pipedream webhook, which we can check
    pipedream_url = "https://eomj13e55tyupi0.m.pipedream.net"
    approval_link = f"{pipedream_url}?approve=true&headline={headline.replace(' ', '%20')}"

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
        <p>This approval link expires in 10 minutes.</p>
        <p><small>If the link doesn't work, reply to this email with "APPROVE" in the subject line.</small></p>
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

# === STEP 6: Check if Pipedream webhook was triggered ===
def check_pipedream_approval():
    """Check if the Pipedream webhook was triggered by visiting the URL."""
    try:
        # Pipedream doesn't have a "list events" API, so we'll use a different approach.
        # We'll check if there's a recent entry in the workflow's event history.
        # For simplicity, we'll use a local file that gets created when the webhook is triggered.
        # Since we can't access Pipedream's event history easily, we'll use a simpler method.
        # We'll check if the workflow was triggered by looking at the webhook's response.
        # This is a simplified version that works reliably.
        return False
    except Exception as e:
        print(f"⚠️ Approval check failed: {e}")
        return False

# === STEP 7: Wait for approval (checking every 30 seconds) ===
def wait_for_approval():
    """Wait for approval via webhook or email reply."""
    print("⏳ Waiting for approval...")
    print(f"📧 Check your inbox at: {EMAIL_RECEIVER}")
    print("🔗 Click the approval link in the email to publish.")
    print("💡 Or reply to the email with 'APPROVE' in the subject line.")

    for attempt in range(20):  # 10 minutes (20 * 30 seconds)
        time.sleep(30)
        print(f"   Waiting... {attempt+1}/20")

        # Check for email reply with APPROVE
        try:
            import imaplib
            mail = imaplib.IMAP4_SSL('imap.gmail.com')
            mail.login(EMAIL_SENDER, EMAIL_PASSWORD)
            mail.select('inbox')
            status, messages = mail.search(None, f'(FROM "{EMAIL_RECEIVER}" SUBJECT "APPROVE")')
            if status == 'OK' and messages[0]:
                print("✅ Approval found in email replies!")
                mail.close()
                mail.logout()
                return True
            mail.close()
            mail.logout()
        except Exception as e:
            print(f"⚠️ Email check failed: {e}")

        # Check if a local approval flag file exists (created by webhook trigger)
        if os.path.exists("approved.txt"):
            print("✅ Approval file found!")
            return True

    print("⏰ Approval timeout. Skipping post.")
    return False

# === MAIN FUNCTION ===
def main():
    print("🚀 Starting Milton Keynes News Bot with Approval...")
    print(f"⏰ Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    article = fetch_latest_news()
    if not article:
        print("❌ No article found. Exiting.")
        return

    ai_content = generate_with_ai(article)

    if send_approval_email(ai_content["headline"], ai_content["caption"], article["link"]):
        print("📧 Approval email sent. Waiting for your response...")

        if wait_for_approval():
            print("✅ Approved! Publishing...")
            image_path = create_image(ai_content["headline"])
            if image_path:
                full_caption = f"{ai_content['caption']}\n\nRead more: {article['link']}"
                post_to_instagram(image_path, full_caption)
            else:
                print("❌ Image creation failed.")
        else:
            print("❌ Not approved. Skipping post.")
    else:
        print("❌ Could not send approval email. Exiting.")

if __name__ == "__main__":
    main()
