from fastapi import FastAPI
import threading
from bot import main as bot_main

app = FastAPI(title="SkyMoviesHD RSS Bot")


@app.get("/")
def home():
    return {
        "status": "running",
        "message": "SkyMoviesHD Telegram Bot Active"
    }


# Start bot in background thread
@app.on_event("startup")
def startup_event():
    thread = threading.Thread(target=bot_main, daemon=True)
    thread.start()
