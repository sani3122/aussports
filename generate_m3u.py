#!/usr/bin/env python3
"""
Live Match M3U Playlist Generator based on Schedule JSON & Channels TXT
Output: live_matches.m3u
"""

import json
import requests
from datetime import datetime
import pytz

# ========== CẤU HÌNH / CONFIGURATION ==========
BANGLADESH_TZ = pytz.timezone("Asia/Dhaka")

# ১. আপনার গিটহাবের JSON ফাইলের Raw URL
JSON_URL = "https://raw.githubusercontent.com/sani3122/aussports/main/nowtv_ziggo_football_bd.json"

# ২. আপনার গিটহাবের Channels TXT ফাইলের Raw URL (যেটি আপনি বানাবেন)
CHANNELS_TXT_URL = "https://raw.githubusercontent.com/sani3122/aussports/main/channels.txt"

# ৩. আউটপুট প্লেলিস্টের নাম
M3U_OUTPUT_FILE = "live_matches.m3u"

# ================= ==============================

def fetch_channel_links(txt_url: str) -> dict:
    """GitHub TXT ফাইল থেকে চ্যানেলের নাম এবং লিঙ্কের ম্যাপ তৈরি করে"""
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
            print(f"✅ Loaded {len(channel_map)} channel links from TXT.")
        else:
            print(f"⚠️ Failed to load channels.txt (Status: {resp.status_code})")
    except Exception as e:
        print(f"❌ Error fetching channels TXT: {e}")
    return channel_map

def fetch_schedule_json(json_url: str) -> list:
    """GitHub থেকে ফুটবল শিডিউল JSON ফাইল লোড করে"""
    try:
        resp = requests.get(json_url, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        else:
            print(f"❌ Failed to load JSON schedule (Status: {resp.status_code})")
            return []
    except Exception as e:
        print(f"❌ Error fetching JSON schedule: {e}")
        return []

def is_match_currently_live(date_str: str, start_time_str: str, end_time_str: str, now_bd: datetime) -> bool:
    """ম্যাচটি বর্তমানে বাংলাদেশে লাইভ চলছে কিনা তা চেক করে"""
    try:
        # Date, Start_Time এবং End_Time পার্স করা
        start_dt_str = f"{date_str} {start_time_str}"
        end_dt_str = f"{date_str} {end_time_str}"
        
        start_dt = BANGLADESH_TZ.localize(datetime.strptime(start_dt_str, "%Y-%m-%d %H:%M"))
        end_dt = BANGLADESH_TZ.localize(datetime.strptime(end_dt_str, "%Y-%m-%d %H:%M"))
        
        # যদি এন্ড টাইম স্টার্ট টাইমের চেয়ে কম হয় (যেমন: রাত ২৩:০০ এ শুরু হয়ে রাত ০১:৩০ এ শেষ), তবে ১ দিন যোগ হবে
        if end_dt < start_dt:
            end_dt += timedelta(days=1)
            
        # বর্তমান সময় কি স্টার্ট টাইম এবং এন্ড টাইমের মাঝে আছে?
        return start_dt <= now_bd <= end_dt
    except Exception as e:
        print(f"Error parsing match time ({date_str} {start_time_str}): {e}")
        return False

def generate_m3u():
    print("🚀 Starting M3U Playlist Generator...")
    now_bd = datetime.now(BANGLADESH_TZ)
    print(f"🕒 Current Bangladesh Time: {now_bd.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # লিঙ্ক ও শিডিউল নিয়ে আসা
    channel_links = fetch_channel_links(CHANNELS_TXT_URL)
    schedule = fetch_schedule_json(JSON_URL)
    
    if not schedule:
        print("❌ No schedule data found. Exiting.")
        return

    m3u_entries = ["#EXTM3U"]
    live_match_count = 0

    for item in schedule:
        date_str = item.get("Date")
        start_time = item.get("Start_Time")
        end_time = item.get("End_Time")
        matchup = item.get("Matchup", "Live Match")
        league = item.get("League", "Football")
        services = item.get("Services", [])

        # ১. চেক করা ম্যাচটি এখন বাংলাদেশে লাইভ আছে কিনা
        if is_match_currently_live(date_str, start_time, end_time, now_bd):
            available_streams = []
            
            # ২. ম্যাচের চ্যানেলগুলোর লিঙ্ক খুঁজে বের করা
            for service in services:
                service_clean = service.strip().lower()
                if service_clean in channel_links:
                    available_streams.append((service, channel_links[service_clean]))

            # ৩. যদি এক বা একাধিক স্ট্রিম বা চ্যানেল খুঁজে পাওয়া যায়
            if available_streams:
                live_match_count += 1
                total_streams = len(available_streams)
                
                for idx, (stream_name, stream_url) in enumerate(available_streams, 1):
                    # একটি মাত্র স্ট্রিম থাকলে সরাসরি ম্যাচের নাম, আর একাধিক থাকলে Stream 1, Stream 2 যুক্ত হবে
                    if total_streams > 1:
                        display_name = f"{matchup} - Stream {idx}"
                    else:
                        display_name = matchup
                        
                    # M3U ফরম্যাট যোগ করা
                    m3u_entries.append(
                        f'#EXTINF:-1 tvg-name="{display_name}" group-title="{league}", {display_name}\n{stream_url}'
                    )

    # ৪. M3U ফাইল সেভ করা
    with open(M3U_OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_entries))

    print(f"✅ M3U Playlist generated successfully with {live_match_count} live match(es)!")
    print(f"💾 File saved to: {M3U_OUTPUT_FILE}")

if __name__ == "__main__":
    generate_m3u()
    
