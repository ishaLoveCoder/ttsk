import json
import os

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "sky_domain": "https://skymovieshd.fast/",
    "hdm_rss": "https://hdmovie2.com.se/movies/feed/",
    "interval": 900,
    "tag_username": "@username",
    "tag_id": 123456789,
    "channels": [],
    "sky_enabled": True,
    "hdm_enabled": True,
    "admin_id": 0,
    "stats": {
        "today_sky": 0,
        "today_hdm": 0,
        "last_reset": ""
    }
}

def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
            # Ensure all default keys exist
            updated = False
            for key, value in DEFAULT_CONFIG.items():
                if key not in config:
                    config[key] = value
                    updated = True
            if updated:
                save_config(config)
            return config
    except Exception as e:
        print(f"Error loading config: {e}")
        return DEFAULT_CONFIG

def save_config(config):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"Error saving config: {e}")

def update_config(key, value):
    config = load_config()
    config[key] = value
    save_config(config)
    return config
