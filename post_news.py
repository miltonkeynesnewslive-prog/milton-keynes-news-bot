import os
import smtplib
import imaplib
import email
import time
import requests
import feedparser
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# === CONFIGURATION ===
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")
INSTAGRAM_ACCESS_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_BUSINESS_ID = os.environ.get("INSTAGRAM_BUSINESS_ID")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# === EMAIL APPROVAL FUNCTIONS ===

def send_approval_email(headline, caption, link):
    """Send an email with the draft and an approval link."""
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("❌ Email credentials missing. Skipping approval.")
        return False
    
    # Create a unique approval ID
    approval_id = str(int(time.time()))
    
    # In a real implementation, you would store this approval ID in a database or file.
    # For GitHub Actions, we'll use a simple file-based approach.
    with open("approval_id.txt", "w") as f:
        f.write(approval_id)
    
    # Create the email body
    body = f"""
    <html>
    <body>
        <h2>📰 News Draft for Approval</h2>
        <p><strong>Headline:</strong> {headline}</p>
        <p><strong>Caption:</strong> {caption}</p>
        <p><strong>Link:</strong> <a href="{link}">{link}</a></p>
        <hr>
        <p><strong>Click the link below to approve and publish:</strong></p>
        <p><a href="https://your-approval-service.com/approve?id={approval_id}">✅ Approve & Publish</a></p>
        <p>Or reply to this email with "APPROVE" in the subject line.</p>
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

def check_email_approval():
    """Check for a reply email with 'APPROVE' in the subject."""
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        return False
    
    try:
        # Connect to Gmail IMAP
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(EMAIL_SENDER, EMAIL_PASSWORD)
        mail.select('inbox')
        
        # Search for emails from the receiver with "APPROVE" in subject
        status, messages = mail.search(None, f'(FROM "{EMAIL_RECEIVER}" SUBJECT "APPROVE")')
        
        if status == 'OK' and messages[0]:
            print("✅ Approval found in email replies!")
            mail.close()
            mail.logout()
            return True
        
        mail.close()
        mail.logout()
        return False
    except Exception as e:
        print(f"⚠️ Email check failed: {e}")
        return False

def wait_for_approval():
    """Wait for email approval (with timeout)."""
    print("⏳ Waiting for email approval...")
    print(f"📧 Check your inbox at: {EMAIL_RECEIVER}")
    
    # Wait up to 30 minutes for approval
    for attempt in range(30):
        time.sleep(60)  # Check every minute
        if check_email_approval():
            return True
        print(f"   Waiting... {attempt+1}/30 minutes")
    
    print("⏰ Approval timeout. Skipping post.")
    return False

# === MAIN FUNCTION ===

def main():
    print("🚀 Starting Milton Keynes News Bot with Email Approval...")
    
    # Step 1: Fetch news
    article = fetch_latest_news()
    if not article:
        return
    
    # Step 2: Generate AI content
    ai_content = generate_with_ai(article)
    
    # Step 3: Send approval email
    if send_approval_email(ai_content["headline"], ai_content["caption"], article["link"]):
        print("📧 Approval email sent. Waiting for your response...")
        
        # Step 4: Wait for approval
        if wait_for_approval():
            print("✅ Approved! Publishing...")
            
            # Step 5: Create image and post
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
