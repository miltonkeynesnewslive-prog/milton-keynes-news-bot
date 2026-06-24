import os
import time
import feedparser
import requests
import smtplib
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

# === GITHUB CONFIGURATION ===
GITHUB_TOKEN = os.environ.get("APPROVAL_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY")
APPROVAL_FILE = "approved.txt"
PIPEDREAM_URL = "https://eomj13e55tyupi0.m.pipedream.net"

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
                        "content": "You are a social media assistant. Create a short headline (max 8 words) and an engaging Instagram caption (under 150 words) with emojis. Format your response as: HEADLINE: ... CAPTION: ..."
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

# === STEP 3: Create image with placehold.co and logo text ===
def create_image(headline):
    print("🖼️ Creating image with logo text...")
    
    # Add "MK NEWS" as a logo prefix
    formatted_text = f"MK NEWS | {headline}"
    encoded_text = requests.utils.quote(formatted_text)
    
    # Use placehold.co with red background and white text
    image_url = f"https://placehold.co/1080x1080/cc0000/ffffff?text={encoded_text}"
    print(f"✅ Image URL created: {image_url}")
    return image_url

# === STEP 4: Post to Instagram ===
def post_to_instagram(image_url, caption):
    print("📸 Posting to Instagram...")
    if not INSTAGRAM_ACCESS_TOKEN or not INSTAGRAM_BUSINESS_ID:
        print("❌ Instagram credentials missing!")
        return False
    
    if not image_url:
        print("❌ No image URL provided!")
        return False
    
    try:
        # Step 1: Create media container with image_url
        upload_url = f"https://graph.facebook.com/v20.0/{INSTAGRAM_BUSINESS_ID}/media"
        data = {
            "access_token": INSTAGRAM_ACCESS_TOKEN,
            "image_url": image_url,
            "caption": caption
        }
        
        print(f"📤 Uploading image...")
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
        
        # Step 2: Publish the post
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

# === STEP 6: Check approval in GitHub ===
def check_approval_in_github():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return os.path.exists(APPROVAL_FILE)
    
    try:
        owner, repo = GITHUB_REPO.split('/')
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{APPROVAL_FILE}"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json"
        }
        response = requests.get(url, headers=headers)
        return response.status_code == 200
    except Exception as e:
        print(f"⚠️ GitHub check failed: {e}")
        return False

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
    print("🚀 Starting Milton Keynes News Bot with Branded Images...")
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
        if send_approval_email(ai_content["headline"], ai_content["caption"], article["link"]):
            print("📧 Approval email sent. Waiting for your response...")
            if not wait_for_approval():
                print("❌ Not approved. Skipping post.")
                return
        else:
            print("❌ Could not send approval email. Exiting.")
            return
    
    print("✅ Approved! Publishing...")
    image_url = create_image(ai_content["headline"])
    full_caption = f"{ai_content['caption']}\n\nRead more: {article['link']}"
    post_to_instagram(image_url, full_caption)

if __name__ == "__main__":
    main()
