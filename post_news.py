import os
import feedparser
import requests
import json
from datetime import datetime

# === CONFIGURATION ===
RSS_FEED_URL = "https://www.miltonkeynes.co.uk/rss"
INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_BUSINESS_ID = os.environ.get("INSTAGRAM_BUSINESS_ID")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# === STEP 1: Fetch the latest news ===
def fetch_latest_news():
    print("📰 Fetching latest news from Milton Keynes Citizen...")
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

# === STEP 2: Generate headline and caption with AI ===
def generate_with_ai(article):
    print("🤖 Generating headline and caption with AI...")
    
    # If no OpenAI key, use fallback
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
            
            # Extract headline and caption
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
    
    # Use placehold.co with the headline
    encoded_headline = requests.utils.quote(headline)
    image_url = f"https://placehold.co/1080x1080/cc0000/ffffff?text={encoded_headline}"
    
    # Download the image to post
    try:
        response = requests.get(image_url, timeout=30)
        if response.status_code == 200:
            # Save image locally
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
        # Step 4a: Upload the image
        print("⬆️ Uploading image...")
        upload_url = f"https://graph.facebook.com/v20.0/{INSTAGRAM_BUSINESS_ID}/media"
        
        # Read the image file
        with open(image_path, "rb") as img_file:
            files = {
                "image": img_file
            }
            data = {
                "access_token": INSTAGRAM_ACCESS_TOKEN,
                "caption": caption,
                "image_url": None  # We're using file upload
            }
            
            # Try with file upload first
            response = requests.post(upload_url, data={"access_token": INSTAGRAM_ACCESS_TOKEN}, files=files)
            
            # If that fails, try with URL
            if response.status_code != 200:
                print("⚠️ File upload failed, trying URL method...")
                # Re-encode the image to a URL
                img_url = f"https://placehold.co/1080x1080/cc0000/ffffff?text={requests.utils.quote(caption[:30])}"
                response = requests.post(
                    upload_url,
                    data={
                        "access_token": INSTAGRAM_ACCESS_TOKEN,
                        "image_url": img_url,
                        "caption": caption
                    }
                )
        
        if response.status_code != 200:
            print(f"❌ Upload failed: {response.text}")
            return False
        
        upload_data = response.json()
        creation_id = upload_data.get("id")
        print(f"✅ Image uploaded with ID: {creation_id}")
        
        # Step 4b: Publish the post
        print("📤 Publishing...")
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

# === MAIN ===
def main():
    print("🚀 Starting Milton Keynes News Bot...")
    print(f"⏰ Run at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Step 1: Fetch news
    article = fetch_latest_news()
    if not article:
        print("❌ No article found. Exiting.")
        return
    
    # Step 2: Generate AI content
    ai_content = generate_with_ai(article)
    
    # Step 3: Create image
    image_path = create_image(ai_content["headline"])
    if not image_path:
        print("❌ Image creation failed. Exiting.")
        return
    
    # Step 4: Post to Instagram
    full_caption = f"{ai_content['caption']}\n\nRead more: {article['link']}"
    success = post_to_instagram(image_path, full_caption)
    
    if success:
        print("✅ All done! News posted successfully!")
    else:
        print("❌ Posting failed.")
    
    # Clean up
    if os.path.exists("post_image.jpg"):
        os.remove("post_image.jpg")

if __name__ == "__main__":
    main()
