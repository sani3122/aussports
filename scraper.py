#!/usr/bin/env python3
"""
Now TV & Ziggo Sport Clean Football Schedule Extractor (Strictly Bangladesh Time with End Time)
Output: nowtv_ziggo_football_bd.json
"""

import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple, Set

import pytz
import requests
from bs4 import BeautifulSoup

# ========== CẤU HÌNH / CONFIGURATION ==========
BANGLADESH_TZ = pytz.timezone("Asia/Dhaka")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"

OUTPUT_FILE = "ziggo_starhub_football_bd.json"

ALLOWED_FOOTBALL_LEAGUES = {
    "Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
    "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
    "UEFA Euro", "FA Cup", "League Cup", "EFL Cup", "FIFA World Cup", "International Friendly",
    "MLS", "Saudi Pro League", "Copa America", "AFC Champions League"
}

# নারীদের ম্যাচ এবং বয়সভিত্তিক ফুটবল ফিল্টার আউট করার কি-ওয়ার্ড
EXCLUDED_FOOTBALL_KEYWORDS = [
    r'\bwomen\b', r'\bwomens\b', r"women's",
    r'\bu[- ]?\d{1,2}\b',  # U-21, U21, U19, U23 ইত্যাদি
    r'\byouth\b', r'\bjunior\b', r'\bgirls\b', r'\bladies\b', r'\bfemale\b', r'\breserves\b'
]
EXCLUDED_FOOTBALL_PATTERN = re.compile('|'.join(EXCLUDED_FOOTBALL_KEYWORDS), re.IGNORECASE)
# ===============================================

# ---------- Helpers ----------
def normalize_matchup(matchup: str) -> str:
    text = matchup.lower()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def clean_brackets(text: str) -> str:
    return re.sub(r"\[.*?\]", "", text).strip()

def is_live(text: str) -> bool:
    return bool(re.search(r"\[Live\]", text, re.IGNORECASE))

def is_football_league_allowed(text: str) -> bool:
    text_lower = text.lower()
    return any(allowed.lower() in text_lower for allowed in ALLOWED_FOOTBALL_LEAGUES)

def is_excluded_football(text: str) -> bool:
    return bool(EXCLUDED_FOOTBALL_PATTERN.search(text))

def extract_league_matchup(title: str) -> Tuple[str, str]:
    cleaned = clean_brackets(title)
    cleaned = re.sub(r"\s*Live\s*$", "", cleaned, flags=re.IGNORECASE).strip()

    # 1) Colon
    if re.search(r"[:：]", cleaned):
        parts = re.split(r"\s*[:：]\s*", cleaned, maxsplit=1)
        league = parts[0].strip()
        matchup = parts[1].strip()
        league = re.sub(r"\s*Live\b", "", league, flags=re.IGNORECASE).strip()
        matchup = re.sub(r"\s*Live\b", "", matchup, flags=re.IGNORECASE).strip()
        matchup = re.sub(r"\s+-\s+", " vs ", matchup)
        return league, matchup

    # 2) Dash/hyphen
    if re.search(r"[-–]", cleaned):
        parts = re.split(r"\s*[-–]\s*", cleaned, maxsplit=1)
        left = parts[0].strip()
        right = parts[1].strip() if len(parts) > 1 else ""
        if is_football_league_allowed(left):
            league = re.sub(r"\s*Live\b", "", left, flags=re.IGNORECASE).strip()
            matchup = re.sub(r"\s*Live\b", "", right, flags=re.IGNORECASE).strip()
            matchup = re.sub(r"\s+-\s+", " vs ", matchup)
            return league, matchup
        else:
            matchup = re.sub(r"\s+[-–]\s+", " vs ", cleaned)
            return "", matchup

    return "", cleaned


# ---------- Now TV Fetcher ----------
class NowTVFetcher:
    def __init__(self):
        self.base_url = "https://nowplayer.now.com"
        self.channel_filter = "now Sports"

    def fetch_channels(self) -> Dict[str, str]:
        print("📡 [NowTV] Fetching channels...")
        url = f"{self.base_url}/channels"
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "en,zh;q=0.9"}
        try:
            resp = requests.get(url, headers=headers, cookies={"LANG": "en"}, timeout=15)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            channel_map = {}
            for item in soup.find_all("div", class_="product-item"):
                name_tag = item.find("p", class_="img-name")
                ch_tag = item.find("p", class_="channel")
                if name_tag and ch_tag:
                    name = name_tag.text.strip()
                    ch_no = ch_tag.text.replace("CH", "").strip()
                    if name.lower().startswith(self.channel_filter.lower()):
                        channel_map[ch_no] = name
            print(f"✅ [NowTV] {len(channel_map)} 'now Sports' channels found.")
            return channel_map
        except Exception as e:
            print(f"❌ [NowTV] Failed to fetch channels: {e}")
            return {}

    def fetch_7day_epg(self, channel_numbers: List[str]) -> Dict[int, List[List[Dict]]]:
        print("📡 [NowTV] Fetching 7-day EPG...")
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/plain, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": f"{self.base_url}/tvguide",
            "X-Requested-With": "XMLHttpRequest",
        }
        cookies = {"LANG": "en"}
        epg_data = {}
        for day in range(1, 8):
            params = [("channelIdList[]", ch) for ch in channel_numbers] + [("day", str(day))]
            try:
                resp = requests.get(f"{self.base_url}/tvguide/epglist", headers=headers,
                                    cookies=cookies, params=params, timeout=10)
                resp.raise_for_status()
                epg_data[day] = resp.json()
                print(f"  Day {day}: OK")
            except Exception as e:
                print(f"  Day {day}: Failed - {e}")
                epg_data[day] = []
        return epg_data

    def parse_events(self, epg_data, channel_numbers, channel_map) -> List[Dict]:
        events = []
        for day in range(1, 8):
            day_progs = epg_data.get(day, [])
            for idx, channel_progs in enumerate(day_progs):
                if idx >= len(channel_numbers):
                    continue
                ch_no = channel_numbers[idx]
                ch_name = channel_map.get(ch_no, f"Channel {ch_no}")
                for epg_item in channel_progs:
                    title = (epg_item.get("name") or "").strip()
                    if not title or not is_live(title):
                        continue
                    
                    if not is_football_league_allowed(title):
                        continue

                    if is_excluded_football(title):
                        continue

                    league, matchup = extract_league_matchup(title)
                    if not league:
                        league = "Football"
                    if not matchup:
                        matchup = title

                    if " vs " not in matchup and " v " not in matchup:
                        continue

                    start_ts = epg_item.get("start", 0) / 1000
                    dt_start = datetime.fromtimestamp(start_ts, tz=BANGLADESH_TZ)
                    # ২ ঘণ্টা ৩০ মিনিট যোগ করে End Time হিসাব করা
                    dt_end = dt_start + timedelta(hours=2, minutes=30)
                    
                    events.append({
                        "Date": dt_start.strftime("%Y-%m-%d"),
                        "Start_Time": dt_start.strftime("%H:%M"),
                        "End_Time": dt_end.strftime("%H:%M"),
                        "League": league,
                        "Matchup": matchup,
                        "Services": [ch_name],
                    })
        return events


# ---------- Ziggo Sport Fetcher ----------
class ZiggoFetcher:
    def __init__(self):
        self.base_url = "https://www.ziggosport.nl"

    def get_available_dates(self) -> List[str]:
        index_url = f"{self.base_url}/cache/site/ZiggosportNL/json/epg/index.json"
        try:
            resp = requests.get(index_url, timeout=10)
            resp.raise_for_status()
            files = resp.json()
            dates = [f.split("-", 1)[1].split(".")[0] for f in files]
            return sorted(dates)
        except Exception as e:
            print(f"❌ [Ziggo] Failed to load index: {e}")
            return []

    def fetch_epg_for_date(self, date_str: str) -> List[Dict]:
        url = f"{self.base_url}/cache/site/ZiggosportNL/json/epg/epg-{date_str}.json"
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"❌ [Ziggo] Failed to fetch {date_str}: {e}")
            return []

    def parse_events(self, days: int = 7) -> List[Dict]:
        all_dates = self.get_available_dates()
        today = datetime.now(BANGLADESH_TZ).strftime("%Y-%m-%d")
        future_dates = sorted([d for d in all_dates if d >= today])[:days]
        events = []
        for date_str in future_dates:
            data = self.fetch_epg_for_date(date_str)
            if not data:
                continue
            for channel_data in data:
                channel_name = channel_data.get("channel", "Unknown Channel")
                for prog in channel_data.get("programming", []):
                    if not prog.get("live"):
                        continue
                    
                    sport_name = (prog.get("sportName") or "").lower()
                    if sport_name != "voetbal":
                        continue
                        
                    title = (prog.get("title") or "").strip()
                    if not title or is_excluded_football(title):
                        continue

                    league, matchup = extract_league_matchup(title)
                    if not league:
                        league = "Football"
                    if not matchup:
                        matchup = title

                    if " vs " not in matchup and " v " not in matchup:
                        continue

                    start_ts = prog.get("timeStart")
                    if start_ts:
                        dt_start = datetime.fromtimestamp(start_ts, tz=BANGLADESH_TZ)
                        dt_end = dt_start + timedelta(hours=2, minutes=30)
                        date_formatted = dt_start.strftime("%Y-%m-%d")
                        start_formatted = dt_start.strftime("%H:%M")
                        end_formatted = dt_end.strftime("%H:%M")
                    else:
                        date_formatted = date_str
                        start_formatted = "00:00"
                        end_formatted = "02:30"

                    events.append({
                        "Date": date_formatted,
                        "Start_Time": start_formatted,
                        "End_Time": end_formatted,
                        "League": league,
                        "Matchup": matchup,
                        "Services": [channel_name],
                    })
        return events


# ---------- Strict Deduplication & Channel Merging ----------
def deduplicate_events(events: List[Dict]) -> List[Dict]:
    groups = {}
    for ev in events:
        date = ev["Date"]
        norm = normalize_matchup(ev["Matchup"])
        key = (date, norm)
        
        if key not in groups:
            groups[key] = {
                "Date": ev["Date"],
                "Start_Time": ev["Start_Time"],
                "End_Time": ev["End_Time"],
                "League": ev["League"],
                "Matchup": ev["Matchup"],
                "Services": set(ev["Services"])
            }
        else:
            groups[key]["Services"].update(ev["Services"])
            if groups[key]["League"] in ("Football", "Sports", "Unknown", "") and ev["League"] not in ("Football", "Sports", "Unknown", ""):
                groups[key]["League"] = ev["League"]
            if ev["Start_Time"] < groups[key]["Start_Time"]:
                groups[key]["Start_Time"] = ev["Start_Time"]
                groups[key]["End_Time"] = ev["End_Time"]

    merged = []
    for key, val in groups.items():
        val["Services"] = sorted(list(val["Services"]))
        merged.append(val)
        
    return merged

def enrich_leagues(events: List[Dict]) -> List[Dict]:
    league_map = {}
    for ev in events:
        if ev["League"] not in ("Football", "Sports", "Unknown", ""):
            key = (ev["Date"], normalize_matchup(ev["Matchup"]))
            league_map[key] = ev["League"]

    for ev in events:
        if ev["League"] in ("Football", "Sports", "Unknown", ""):
            key = (ev["Date"], normalize_matchup(ev["Matchup"]))
            if key in league_map:
                ev["League"] = league_map[key]
    return events


# ---------- Main Execution ----------
async def main():
    print("🚀 Now TV & Ziggo Sport Football Schedule Extractor (With Start & End Time - BD Time)")

    # 1. Now TV
    nowtv = NowTVFetcher()
    nowtv_channels = nowtv.fetch_channels()
    nowtv_events = []
    if nowtv_channels:
        ch_numbers = list(nowtv_channels.keys())
        epg = nowtv.fetch_7day_epg(ch_numbers)
        nowtv_events = nowtv.parse_events(epg, ch_numbers, nowtv_channels)
        print(f"🎯 [NowTV] {len(nowtv_events)} football events")

    # 2. Ziggo Sport
    ziggo = ZiggoFetcher()
    ziggo_events = ziggo.parse_events(days=7)
    print(f"🎯 [Ziggo] {len(ziggo_events)} football events")

    # Combine & Process
    all_events = nowtv_events + ziggo_events
    print(f"📊 Total raw football events: {len(all_events)}")

    all_events = deduplicate_events(all_events)
    all_events = enrich_leagues(all_events)
    print(f"✅ After strict deduplication & enrichment: {len(all_events)} events")

    all_events.sort(key=lambda x: (x["Date"], x["Start_Time"]))

    output = []
    for ev in all_events:
        output.append({
            "Date": ev["Date"],
            "Start_Time": ev["Start_Time"],
            "End_Time": ev["End_Time"],
            "League": ev["League"],
            "Matchup": ev["Matchup"],
            "Services": ev["Services"]
        })

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"💾 Saved to: {OUTPUT_FILE}")

    print("\n📋 Sample output (First 5 matches in BD Time):")
    for ev in output[:5]:
        print(f"{ev['Date']} | {ev['Start_Time']} - {ev['End_Time']} BST | {ev['League']} | {ev['Matchup']} | {', '.join(ev['Services'])}")

if __name__ == "__main__":
    asyncio.run(main())
    
