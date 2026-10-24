#!/usr/bin/env python3
"""
Live Match M3U Playlist Generator with Auto-Cleanup for Expired Match Posters
Output: live_matches.m3u & cleaned generated_logos/ folder
"""

import json
import os
import re
import requests
from io import BytesIO
from datetime import datetime, timedelta
import pytz
from PIL import Image

# ========== CẤU HÌNH / CONFIGURATION ==========
BANGLADESH_TZ = pytz.timezone("Asia/Dhaka")

# ১. ফাইল ও ইউআরএল কনফিগারেশন
JSON_URL = "https://raw.githubusercontent.com/sani3122/aussports/main/ziggo_starhub_football_bd.json"
CHANNELS_TXT_URL = "https://raw.githubusercontent.com/sani3122/aussports/main/channels.txt"
BG_IMAGE_URL = "https://raw.githubusercontent.com/sani3122/aussports/refs/heads/main/icons/file_0000000073d88211a98938feb9e984e6.png"

# গিটহাব রপোজিটরির বেস ইউআরএল
GITHUB_RAW_BASE = "https://raw.githubusercontent.com/sani3122/aussports/main"

# আইকন ফোল্ডারসমূহ
ICON_FOLDERS = ["LaLiga", "Serie-A", "UEFA-Champions-League", "PremierLeague"]

M3U_OUTPUT_FILE = "live_matches.m3u"
GENERATED_LOGOS_DIR = "generated_logos"

# ===============================================

def clean_team_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r'\b(fc|cf|cd|rcd|us|ud|sc|as|vfb|tsv)\b', '', name)
    name = re.sub(r'[^a-z0-9]', '', name)
    return name.strip()

def fetch_channel_links(txt_url: str) -> dict:
    channel_map = {}
    try:
        resp = requests.get(txt_url, timeout=15)
        if resp.status_code == 200:
            lines = resp.text.strip().split('\n')
            for line in lines:
                if ',' in line:
                    parts = line.split(',', 1)
                    ch_name = parts[0].strip().lower()
                    ch_link = parts[1].strip()
                    channel_map[ch_name] = ch_link
    except Exception as e:
        print(f"❌ Error fetching channels TXT: {e}")
    return channel_map

def fetch_schedule_json(json_url: str) -> list:
    try:
        resp = requests.get(json_url, timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"❌ Error fetching JSON schedule: {e}")
    return []

def get_team_logo(team_name: str) -> Image.Image:
    norm_search = clean_team_name(team_name)
    
    for folder in ICON_FOLDERS:
        possible_filenames = [
            f"{norm_search}.png",
            f"{team_name.lower().replace(' ', '-')}.png",
            f"{team_name.lower().replace(' ', '_')}.png"
        ]
        
        for fname in possible_filenames:
            url = f"{GITHUB_RAW_BASE}/icons/{folder}/{fname}"
            try:
                res = requests.get(url, timeout=5)
                if res.status_code == 200:
                    img = Image.open(BytesIO(res.content)).convert("RGBA")
                    return img
            except Exception:
                continue
    return None

def create_match_poster(home_team: str, away_team: str, match_slug: str, bg_image: Image.Image) -> str:
    poster = bg_image.copy()
    w, h = poster.size

    home_logo = get_team_logo(home_team)
    away_logo = get_team_logo(away_team)

    logo_size = (int(h * 0.65), int(h * 0.65))

    if home_logo:
        home_logo.thumbnail(logo_size, Image.Resampling.LANCZOS)
        pos_x = int(w * 0.14)
        pos_y = int((h - home_logo.height) / 2)
        poster.paste(home_logo, (pos_x, pos_y), home_logo)

    if away_logo:
        away_logo.thumbnail(logo_size, Image.Resampling.LANCZOS)
        pos_x = int(w * 0.86 - away_logo.width)
        pos_y = int((h - away_logo.height) / 2)
        poster.paste(away_logo, (pos_x, pos_y), away_logo)

    os.makedirs(GENERATED_LOGOS_DIR, exist_ok=True)
    out_filename = f"{match_slug}.png"
    out_path = os.path.join(GENERATED_LOGOS_DIR, out_filename)
    poster.save(out_path, format="PNG")
    
    return f"{GITHUB_RAW_BASE}/{GENERATED_LOGOS_DIR}/{out_filename}"

def is_match_currently_live(date_str: str, start_time_str: str, end_time_str: str, now_bd: datetime) -> bool:
    try:
        start_dt_str = f"{date_str} {start_time_str}"
        end_dt_str = f"{date_str} {end_time_str}"
        
        start_dt = BANGLADESH_TZ.localize(datetime.strptime(start_dt_str, "%Y-%m-%d %H:%M"))
        end_dt = BANGLADESH_TZ.localize(datetime.strptime(end_dt_str, "%Y-%m-%d %H:%M"))
        
        if end_dt < start_dt:
            end_dt += timedelta(days=1)
            
        return start_dt <= now_bd <= end_dt
    except Exception:
        return False

def generate_m3u():
    print("🚀 Starting M3U Playlist & Auto-Cleanup Poster Generator...")
    now_bd = datetime.now(BANGLADESH_TZ)
    
    bg_res = requests.get(BG_IMAGE_URL, timeout=15)
    if bg_res.status_code != 200:
        print("❌ Background image loading failed!")
        return
    bg_image = Image.open(BytesIO(bg_res.content)).convert("RGBA")

    channel_links = fetch_channel_links(CHANNELS_TXT_URL)
    schedule = fetch_schedule_json(JSON_URL)
    
    if not schedule:
        print("❌ No schedule data found. Exiting.")
        return

    m3u_entries = ["#EXTM3U"]
    live_match_count = 0
    active_poster_files = set()

    for item in schedule:
        date_str = item.get("Date")
        start_time = item.get("Start_Time")
        end_time = item.get("End_Time")
        matchup = item.get("Matchup", "Live Match")
        league = item.get("League", "Football")
        services = item.get("Services", [])

        if is_match_currently_live(date_str, start_time, end_time, now_bd):
            available_streams = []
            
            for service in services:
                service_clean = service.strip().lower()
                if service_clean in channel_links:
                    available_streams.append((service, channel_links[service_clean]))

            if available_streams:
                live_match_count += 1
                total_streams = len(available_streams)

                if " vs " in matchup.lower():
                    teams = re.split(r'\s+vs\s+', matchup, flags=re.IGNORECASE)
                    home_team, away_team = teams[0].strip(), teams[1].strip()
                else:
                    home_team, away_team = matchup, ""

                match_slug = re.sub(r'[^a-z0-9]', '_', matchup.lower())
                poster_filename = f"{match_slug}.png"
                active_poster_files.add(poster_filename)

                # পোস্টার তৈরি বা নিশ্চিত করা
                logo_url = create_match_poster(home_team, away_team, match_slug, bg_image)

                for idx, (stream_name, stream_url) in enumerate(available_streams, 1):
                    display_name = f"{matchup} - Stream {idx}" if total_streams > 1 else matchup
                    
                    m3u_entries.append(
                        f'#EXTINF:-1 tvg-name="{display_name}" tvg-logo="{logo_url}" group-title="{league}", {display_name}\n{stream_url}'
                    )

    # 🧹 অটো-ক্লিনআপ: যে পোস্টারগুলো এখন আর লাইভ ম্যাচের তালিকায় নেই, সেগুলো ফোল্ডার থেকে মুছে ফেলা
    if os.path.exists(GENERATED_LOGOS_DIR):
        for file in os.listdir(GENERATED_LOGOS_DIR):
            if file.endswith(".png") and file not in active_poster_files:
                file_path = os.path.join(GENERATED_LOGOS_DIR, file)
                try:
                    os.remove(file_path)
                    print(f"🗑️ Deleted expired poster: {file}")
                except Exception as e:
                    print(f"⚠️ Failed to delete {file}: {e}")

    with open(M3U_OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_entries))

    print(f"✅ M3U Playlist & {live_match_count} Active Posters generated successfully (Expired posters cleaned)!")

if __name__ == "__main__":
    generate_m3u()
                    
