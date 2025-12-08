from fastapi import FastAPI
from pydantic import BaseModel
from lxml import etree
from ftplib import FTP
import requests
import schedule
import threading
import time
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime

app = FastAPI()

# Store ALL config entries here
config_history = []   # list of {timestamp, config}

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
# CORE FUNCTIONS
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
# PROCESS FEED
# ------------------------------------------------------
def run_feed_job(config: FeedConfig):
    xml_bytes = fetch_xml(config.source_url)
    parser = etree.XMLParser(remove_blank_text=True)
    root = etree.fromstring(xml_bytes, parser)

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
    global config_history

    # Save config + timestamp
    config_history.append({
        "timestamp": datetime.utcnow().isoformat(),
        "config": config.dict()
    })

    removed = run_feed_job(config)

    return {
        "status": "success",
        "removed_images": removed,
        "ftp_path": config.ftp_target_path
    }


# ------------------------------------------------------
# GET LAST CONFIG
# ------------------------------------------------------
@app.get("/last-config")
def get_last_config():
    if not config_history:
        return {"message": "No config has been posted yet"}

    return config_history[-1]


# ------------------------------------------------------
# GET FULL HISTORY
# ------------------------------------------------------
@app.get("/config-history")
def get_config_history():
    return config_history


# ------------------------------------------------------
# SCHEDULER
# ------------------------------------------------------
# ------------------------------------------------------
# SCHEDULER
# ------------------------------------------------------
scheduler_running = False

def scheduler_loop():
    while scheduler_running:
        schedule.run_pending()
        time.sleep(1)


@app.post("/start-scheduler")
def start_scheduler(config: FeedConfig):
    global scheduler_running

    if scheduler_running:
        return {"message": "Scheduler already running"}

    scheduler_running = True

    # Run every 1 minute
    schedule.every(1).minutes.do(lambda: run_feed_job(config))

    thread = threading.Thread(target=scheduler_loop)
    thread.start()

    return {"message": "Scheduler started (runs every 1 minute)"}

@app.post("/stop-scheduler")
def stop_scheduler():
    global scheduler_running
    scheduler_running = False
    return {"message": "Scheduler stopped"}


# ------------------------------------------------------
# HEALTH CHECK
# ------------------------------------------------------
@app.get("/")
def home():
    return {"message": "API is running"}
