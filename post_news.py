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

# === YOUR LOGO (Base64 Embedded) ===
LOGO_URL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAfQAAAH0CAYAAADL1t+KAAAACXBIWXMAAA7EAAAOxAGVKw4bAAAEsGlUWHRYTUw6Y29tLmFkb2JlLnhtcAAAAAAAPD94cGFja2V0IGJlZ2luPSfvu78nIGlkPSdXNU0wTXBDZWhpSHpyZVN6TlRjemtjOWQnPz4KPHg6eG1wbWV0YSB4bWxuczp4PSdhZG9iZTpuczptZXRhLyc+CjxyZGY6UkRGIHhtbG5zOnJkZj0naHR0cDovL3d3dy53My5vcmcvMTk5OS8wMi8yMi1yZGYtc3ludGF4LW5zIyc+CgogPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9JycKICB4bWxuczpBdHRyaWI9J2h0dHA6Ly9ucy5hdHRyaWJ1dGlvbi5jb20vYWRzLzEuMC8nPgogIDxBdHRyaWI6QWRzPgogICA8cmRmOlNlcT4KICAgIDxyZGY6bGkgcmRmOnBhcnNlVHlwZT0nUmVzb3VyY2UnPgogICAgIDxBdHRyaWI6Q3JlYXRlZD4yMDI0LTEyLTI0PC9BdHRyaWI6Q3JlYXRlZD4KICAgICA8QXR0cmliOkV4dElkPmM2YzY4ZjgyLTg4OTYtNDFmMS05NjYwLWEyZjc5ZGQ5NTAzOTwvQXR0cmliOkV4dElkPgogICAgIDxBdHRyaWI6RmJJZD41MjUyNjU5MTQxNzk1ODA8L0F0dHJpYjpGYklkPgogICAgIDxBdHRyaWI6VG91Y2hUeXBlPjI8L0F0dHJpYjpUb3VjaFR5cGU+CiAgICA8L3JkZjpsaT4KICAgPC9yZGY6U2VxPgogIDwvQXR0cmliOkFkcz4KIDwvcmRmOkRlc2NyaXB0aW9uPgoKIDxyZGY6RGVzY3JpcHRpb24gcmRmOmFib3V0PScnCiAgeG1sbnM6ZGM9J2h0dHA6Ly9wdXJsLm9yZy9kYy9lbGVtZW50cy8xLjEvJz4KICA8ZGM6dGl0bGU+CiAgIDxyZGY6QWx0PgogICAgPHJkZjpsaSB4bWw6bGFuZz0neC1kZWZhdWx0Jz5NaW5pbWFsaXN0IE1LIExldHRlciBMb2dvICAtIDE8L3JkZjpsaT4KICAgPC9yZGY6QWx0PgogIDwvZGM6dGl0bGU+CiA8L3JkZjpEZXNjcmlwdGlvbj4KCiA8cmRm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"

# === HTMLCSSTOIMAGE CONFIGURATION ===
HTML_CSS_API_KEY = os.environ.get("HTML_CSS_API_KEY")
HTML_CSS_USER_ID = os.environ.get("HTML_CSS_USER_ID")

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

# === STEP 3: Create branded image with logo ===
def create_branded_image(headline):
    print("🖼️ Creating branded image with logo...")
    
    if not HTML_CSS_API_KEY or not HTML_CSS_USER_ID:
        print("⚠️ HTMLCSSToImage credentials missing. Using fallback.")
        return create_placeholder_image(headline)
    
    # HTML template with your embedded logo
    html_template = f'''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                margin: 0;
                padding: 0;
                width: 1080px;
                height: 1080px;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                background: linear-gradient(135deg, #cc0000, #990000);
                font-family: 'Arial', sans-serif;
                color: white;
                text-align: center;
            }}
            .logo-container {{
                width: 180px;
                height: 180px;
                margin-bottom: 20px;
                display: flex;
                align-items: center;
                justify-content: center;
                background: white;
                border-radius: 50%;
                padding: 10px;
            }}
            .logo {{
                width: 100%;
                height: 100%;
                object-fit: contain;
                border-radius: 50%;
            }}
            .headline {{
                font-size: 48px;
                font-weight: 900;
                padding: 0 40px;
                margin: 10px 0;
                text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
                line-height: 1.2;
            }}
            .divider {{
                width: 200px;
                height: 3px;
                background: rgba(255,255,255,0.5);
                margin: 15px auto;
            }}
            .tagline {{
                font-size: 22px;
                opacity: 0.9;
                font-weight: 300;
                letter-spacing: 2px;
            }}
            .date {{
                font-size: 16px;
                opacity: 0.7;
                margin-top: 15px;
            }}
        </style>
    </head>
    <body>
        <div class="logo-container">
            <img src="{LOGO_URL}" alt="MK News Logo" class="logo">
        </div>
        <div class="headline">{headline}</div>
        <div class="divider"></div>
        <div class="tagline">📍 Milton Keynes News</div>
        <div class="date">{datetime.now().strftime('%B %d, %Y')}</div>
    </body>
    </html>
    '''
    
    try:
        response = requests.post(
            "https://api.htmlcsstoimage.com/v1/image",
            auth=(HTML_CSS_USER_ID, HTML_CSS_API_KEY),
            json={
                "html": html_template,
                "css": "",
                "google_fonts": "Arial"
            },
            timeout=60
        )
        
        if response.status_code == 200:
            data = response.json()
            image_url = data.get("url")
            print(f"✅ Branded image created: {image_url}")
            return image_url
        else:
            print(f"⚠️ HTMLCSSToImage error: {response.text}")
            return create_placeholder_image(headline)
    except Exception as e:
        print(f"⚠️ Image creation failed: {e}")
        return create_placeholder_image(headline)

# === STEP 4: Fallback image ===
def create_placeholder_image(headline):
    encoded_headline = requests.utils.quote(headline[:60])
    return f"https://placehold.co/1080x1080/cc0000/ffffff?text={encoded_headline}"

# === STEP 5: Post to Instagram ===
def post_to_instagram(image_url, caption):
    print("📸 Posting to Instagram...")
    if not INSTAGRAM_ACCESS_TOKEN or not INSTAGRAM_BUSINESS_ID:
        print("❌ Instagram credentials missing!")
        return False
    
    try:
        upload_url = f"https://graph.facebook.com/v20.0/{INSTAGRAM_BUSINESS_ID}/media"
        data = {
            "access_token": INSTAGRAM_ACCESS_TOKEN,
            "image_url": image_url,
            "caption": caption
        }
        
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

# === STEP 6: Send approval email ===
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

# === STEP 7: Check approval in GitHub ===
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

# === STEP 8: Wait for approval ===
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
    image_url = create_branded_image(ai_content["headline"])
    full_caption = f"{ai_content['caption']}\n\nRead more: {article['link']}"
    post_to_instagram(image_url, full_caption)

if __name__ == "__main__":
    main()
