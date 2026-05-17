from fastapi import FastAPI
import threading
import time
import requests
import os
from bot import main as bot_main

app = FastAPI(title="SkyMoviesHD RSS Bot")


@app.get("/")
def home():
    return {
        "status": "running",
        "message": "SkyMoviesHD Telegram Bot Active"
    }


@app.get("/ping")
def ping():
    return {"ping": "pong"}


def self_ping():
    """Render pe sleep se bachane ke liye har 10 min mein khud ko ping karta hai"""
    time.sleep(30)  # startup ke baad thoda wait
    
    # Apna Render URL env se lo
    render_url = os.getenv("RENDER_EXTERNAL_URL", "")
    
    if not render_url:
        print("RENDER_EXTERNAL_URL set nahi hai, self-ping band")
        return
    
    while True:
        try:
            requests.get(f"{render_url}/ping", timeout=10)
            print("Self-ping done")
        except Exception as e:
            print(f"Self-ping error: {e}")
        
        time.sleep(600)  # 10 minute


@app.on_event("startup")
def startup_event():
    # Bot thread
    bot_thread = threading.Thread(target=bot_main, daemon=True)
    bot_thread.start()
    
    # Self-ping thread
    ping_thread = threading.Thread(target=self_ping, daemon=True)
    ping_thread.start()
