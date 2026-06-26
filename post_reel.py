"""
Daily news reel: build it, email you a link to watch + approve, and only
publish to Instagram as a Reel after you click approve.

Uses its OWN approval file (reel_approved.txt) and its OWN Pipedream workflow,
so it never clashes with the photo bot's approval.

Env (GitHub secrets, same ones you already use):
  INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_BUSINESS_ID, OPENAI_API_KEY,
  APPROVAL_TOKEN (repo write), GITHUB_REPOSITORY,
  EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER
"""

import os
import time
import base64
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests

import build_reel  # reuses the builder

# === CONFIG ===
IG_TOKEN = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
IG_ID = os.environ.get("INSTAGRAM_BUSINESS_ID")
GH_TOKEN = os.environ.get("APPROVAL_TOKEN")
GH_REPO = os.environ.get("GITHUB_REPOSITORY")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.environ.get("EMAIL_RECEIVER")

# Second Pipedream workflow that creates reel_approved.txt (NOT the photo one).
# Paste the URL of your NEW reel-approval Pipedream workflow here:
REEL_PIPEDREAM_URL = "https://eoydp1e9yssfbk3.m.pipedream.net"

VIDEO_FILE = "reel.mp4"
HOST_PATH = "reels/latest.mp4"
REEL_APPROVAL_FILE = "reel_approved.txt"
GRAPH = "https://graph.facebook.com/v20.0"


# === Approval helpers (single-use reel_approved.txt) ===
def _gh_headers():
    return {"Authorization": f"token {GH_TOKEN}", "Accept": "application/vnd.github+json"}


def _approval_url():
    owner, repo = GH_REPO.split("/")
    return f"https://api.github.com/repos/{owner}/{repo}/contents/{REEL_APPROVAL_FILE}"


def get_reel_approval_sha():
    if not GH_TOKEN or not GH_REPO:
        return None
    try:
        r = requests.get(_approval_url(), headers=_gh_headers())
        return r.json().get("sha") if r.status_code == 200 else None
    except Exception as e:
        print(f"⚠️ approval check failed: {e}")
        return None


def reel_is_approved():
    return get_reel_approval_sha() is not None


def clear_reel_approval():
    sha = get_reel_approval_sha()
    if not sha:
        return
    try:
        r = requests.delete(_approval_url(), headers=_gh_headers(),
                            json={"message": "Consume reel approval", "sha": sha})
        if r.status_code in (200, 201):
            print("🧹 Cleared reel_approved.txt — approval consumed.")
        else:
            print(f"⚠️ Could not clear reel approval ({r.status_code}): {r.text[:150]}")
    except Exception as e:
        print(f"⚠️ Could not clear reel approval: {e}")


def wait_for_reel_approval():
    print("⏳ Waiting for reel approval...")
    print(f"📧 Check your inbox at: {EMAIL_RECEIVER}")
    for attempt in range(20):
        time.sleep(30)
        print(f"   Waiting... {attempt+1}/20")
        if reel_is_approved():
            return True
    print("⏰ Approval timeout. Skipping reel.")
    return False


# === Hosting ===
def host_video(path):
    print("⬆️ Uploading reel to repo for hosting...")
    api = _approval_url().replace(REEL_APPROVAL_FILE, HOST_PATH)
    sha = None
    r = requests.get(api, headers=_gh_headers())
    if r.status_code == 200:
        sha = r.json().get("sha")
    with open(path, "rb") as f:
        content = base64.b64encode(f.read()).decode("utf-8")
    payload = {"message": "Update daily reel video", "content": content, "branch": "main"}
    if sha:
        payload["sha"] = sha
    r = requests.put(api, headers=_gh_headers(), json=payload)
    if r.status_code not in (200, 201):
        print(f"❌ Hosting upload failed ({r.status_code}): {r.text[:200]}")
        return None
    url = r.json()["content"]["download_url"]
    print(f"✅ Hosted at {url}")
    return url


# === Caption + approval email ===
def build_caption(stories):
    date = datetime.now().strftime("%A %d %B %Y")
    lines = [f"🗞️ Milton Keynes Evening News — {date}", ""]
    for s in stories:
        lines.append("• " + s["title"])
    lines += [
        "",
        "Follow @miltonkeynes_news for your daily local round-up.",
        "",
        "#MiltonKeynes #MKNews #MiltonKeynesNews #MK #Buckinghamshire "
        "#LocalNews #MKCommunity #ThamesValley #NewsUpdate #Reels",
    ]
    return "\n".join(lines)


def send_reel_approval_email(stories, caption, watch_url):
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("❌ Email credentials missing. Skipping approval.")
        return False

    story_list = "".join(f"<li>{s['title']}</li>" for s in stories)
    body = f"""
    <html><body>
        <h2>🎬 Daily Reel ready for approval</h2>
        <p><strong>Today's stories:</strong></p>
        <ul>{story_list}</ul>
        <p><a href="{watch_url}" style="display:inline-block;background:#222;color:#fff;
           padding:10px 20px;text-decoration:none;border-radius:5px;">▶ Watch the reel</a></p>
        <p style="white-space:pre-wrap;border-left:3px solid #ccc;padding-left:10px;color:#444;">{caption}</p>
        <hr>
        <p><strong>Approve to publish this reel:</strong></p>
        <p><a href="{REEL_PIPEDREAM_URL}" style="display:inline-block;background:#cc0000;color:#fff;
           padding:10px 20px;text-decoration:none;border-radius:5px;">✅ Approve &amp; Publish Reel</a></p>
        <p><small>You have about 10 minutes to approve.</small></p>
    </body></html>
    """
    msg = MIMEMultipart()
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    msg["Subject"] = "🎬 Reel Approval Needed — Milton Keynes Evening News"
    msg.attach(MIMEText(body, "html"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        print("✅ Approval email sent!")
        return True
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return False


# === Instagram Reel publish ===
def post_reel(video_url, caption):
    if not IG_TOKEN or not IG_ID:
        print("❌ Instagram credentials missing.")
        return False

    print("🎬 Creating Reel container...")
    r = requests.post(
        f"{GRAPH}/{IG_ID}/media",
        data={"media_type": "REELS", "video_url": video_url,
              "caption": caption, "access_token": IG_TOKEN},
    )
    if r.status_code != 200:
        print(f"❌ Container creation failed: {r.text[:300]}")
        return False
    container_id = r.json().get("id")
    if not container_id:
        print(f"❌ No container id: {r.json()}")
        return False
    print(f"✅ Container {container_id} created.")

    print("⏳ Waiting for Instagram to process the video...")
    for attempt in range(30):
        time.sleep(10)
        s = requests.get(
            f"{GRAPH}/{container_id}",
            params={"fields": "status_code,status", "access_token": IG_TOKEN},
        ).json()
        code = s.get("status_code")
        print(f"   status {attempt+1}/30: {code}")
        if code == "FINISHED":
            break
        if code == "ERROR":
            print(f"❌ Processing error: {s}")
            return False
    else:
        print("❌ Timed out waiting for processing.")
        return False

    print("📤 Publishing Reel...")
    r = requests.post(
        f"{GRAPH}/{IG_ID}/media_publish",
        data={"creation_id": container_id, "access_token": IG_TOKEN},
    )
    if r.status_code == 200:
        print("✅ Reel published successfully!")
        return True
    print(f"❌ Publish failed: {r.text[:300]}")
    return False


# === MAIN ===
def main():
    print("🚀 Building today's reel...")
    stories = build_reel.main()
    if not stories:
        print("❌ No stories — nothing to post.")
        return
    if not os.path.exists(VIDEO_FILE):
        print("❌ reel.mp4 was not produced.")
        return

    video_url = host_video(VIDEO_FILE)
    if not video_url:
        return

    caption = build_caption(stories)
    print("\n----- CAPTION -----\n" + caption + "\n-------------------\n")

    # Approval gate
    clear_reel_approval()  # clear any stale approval first
    if not send_reel_approval_email(stories, caption, video_url):
        print("❌ Could not send approval email. Skipping reel.")
        return
    if not wait_for_reel_approval():
        print("❌ Reel not approved. Skipping.")
        return
    clear_reel_approval()  # consume it (single-use)

    print("✅ Approved! Publishing reel...")
    post_reel(video_url, caption)


if __name__ == "__main__":
    main()
