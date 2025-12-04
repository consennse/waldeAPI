from fastapi import FastAPI
from pydantic import BaseModel
from lxml import etree
from ftplib import FTP
import requests
import schedule
import threading
import time
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
last_config = None

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------
# INPUT MODEL
# ------------------------------------------------------
class FeedConfig(BaseModel):
    source_url: str
    ftp_host: str
    ftp_username: str
    ftp_password: str
    ftp_target_path: str


# ------------------------------------------------------
# CORE FUNCTIONS (not API specific)
# ------------------------------------------------------

def fetch_xml(url: str):
    resp = requests.get(url)
    resp.raise_for_status()
    return resp.content


def remove_teaser_images(root):
    images = root.findall(".//image")
    removed = 0

    for image in images:
        tags = [t.text.strip() for t in image.findall("tag") if t.text]

        if "Teaser (Portale)" in tags:
            parent = image.getparent()
            if parent is not None:
                parent.remove(image)
                removed += 1

    return removed


def upload_via_ftp(local_file, ftp_host, ftp_username, ftp_password, ftp_target_path):
    ftp = FTP(ftp_host)
    ftp.login(ftp_username, ftp_password)

    with open(local_file, "rb") as f:
        ftp.storbinary(f"STOR " + ftp_target_path, f)

    ftp.quit()


# ------------------------------------------------------
# MAIN PROCESS FUNCTION (used by API & Scheduler)
# ------------------------------------------------------
def run_feed_job(config: FeedConfig):
    # Fetch feed
    xml_bytes = fetch_xml(config.source_url)
    parser = etree.XMLParser(remove_blank_text=True)
    root = etree.fromstring(xml_bytes, parser)

    # Clean feed
    removed = remove_teaser_images(root)

    cleaned_xml = etree.tostring(
        root, pretty_print=True, xml_declaration=True, encoding="utf-8"
    )

    LOCAL_FILENAME = "fgp.xml"
    with open(LOCAL_FILENAME, "wb") as f:
        f.write(cleaned_xml)

    upload_via_ftp(
        LOCAL_FILENAME,
        config.ftp_host,
        config.ftp_username,
        config.ftp_password,
        config.ftp_target_path
    )

    return removed


# ------------------------------------------------------
# API ENDPOINT — MANUAL TRIGGER
# ------------------------------------------------------
@app.post("/process-feed")
def process_feed(config: FeedConfig):
    global last_config
    last_config = config.dict()   # store it

    removed = run_feed_job(config)
    return {
        "status": "success",
        "removed_images": removed,
        "ftp_path": config.ftp_target_path
    }
@app.get("/last-config")
def get_last_config():
    global last_config
    if last_config is None:
        return {"message": "No config has been posted yet"}
    return last_config

# ------------------------------------------------------
# SCHEDULER LOGIC
# ------------------------------------------------------
scheduler_running = False

def scheduler_loop():
    """Runs in background thread."""
    while scheduler_running:
        schedule.run_pending()
        time.sleep(1)

@app.post("/start-scheduler")
def start_scheduler(config: FeedConfig):
    global scheduler_running

    if scheduler_running:
        return {"message": "Scheduler already running"}

    scheduler_running = True

    # Schedule the job every hour
    schedule.every().hour.do(lambda: run_feed_job(config))

    thread = threading.Thread(target=scheduler_loop)
    thread.start()

    return {"message": "Scheduler started (runs every 1 hour)"}

@app.post("/stop-scheduler")
def stop_scheduler():
    global scheduler_running
    scheduler_running = False
    return {"message": "Scheduler stopped"}


# ------------------------------------------------------
# HEALTH CHECK / HOME
# ------------------------------------------------------
@app.get("/")
def home():
    return {"message": "API is running"}
