#!/usr/bin/env python3
"""
WherestheMatch Twenty20 International Cricket Scraper
Source: https://www.wheresthematch.com/twenty20-international-cricket-on-tv/
Source Timezone: Europe/London (UK Time) -> Converted to Asia/Dhaka (BST, GMT+6)
Output: cricket_schedule_bd.json
"""

import asyncio
import json
import re
from datetime import datetime, timedelta
import pytz
from playwright.async_api import async_playwright

# ==================== CONFIGURATION ====================
URL = "https://www.wheresthematch.com/cricket-today/"
UK_TZ = pytz.timezone("Europe/London")
BANGLADESH_TZ = pytz.timezone("Asia/Dhaka")

# Set TIME_RANGE_HOURS_AFTER = None to include ALL upcoming fixtures on the page
TIME_RANGE_HOURS_BEFORE = 6
TIME_RANGE_HOURS_AFTER = 2160  # ~90 days ahead (covers Dec fixtures in schedule)
T20_DURATION_HOURS = 4
OUTPUT_FILE = "cricket_schedule_bd.json"

# ==================== DATE & TIME PARSERS ====================
def parse_uk_date(date_text: str, ref_uk_date):
    if not date_text:
        return None
    cleaned = re.sub(r'\bToday\b', '', date_text, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = re.sub(r'\b(\d{1,2})(st|nd|rd|th)\b', r'\1', cleaned, flags=re.IGNORECASE)

    formats = [
        "%a %d %B %Y",
        "%d %B %Y",
        "%a %d %b %Y",
        "%d %b %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    no_year = re.sub(r'\s+\d{4}$', '', cleaned).strip()
    for fmt in ("%a %d %B", "%d %B", "%a %d %b", "%d %b"):
        try:
            dt = datetime.strptime(no_year, fmt).replace(year=ref_uk_date.year)
            return dt.date()
        except ValueError:
            continue

    return None


def parse_time_24h_or_12h(time_text: str):
    if not time_text:
        return None
    t = time_text.strip().upper()
    m = re.search(r'\b(\d{1,2}):(\d{2})\s*(AM|PM)?\b', t)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2))
    meridiem = m.group(3)

    if meridiem == "PM" and hour != 12:
        hour += 12
    elif meridiem == "AM" and hour == 12:
        hour = 0

    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def normalize_matchup(fixture_text: str) -> str:
    text = re.sub(r'\s+', ' ', fixture_text or '').strip()
    text = re.sub(r'\s+v(?:s)?\s+', ' vs ', text, flags=re.IGNORECASE)
    return text


def is_within_range(bd_dt: datetime, ref_bd_dt: datetime) -> bool:
    start = ref_bd_dt - timedelta(hours=TIME_RANGE_HOURS_BEFORE)
    if TIME_RANGE_HOURS_AFTER is None:
        return bd_dt >= start
    end = ref_bd_dt + timedelta(hours=TIME_RANGE_HOURS_AFTER)
    return start <= bd_dt <= end


# ==================== CLEAN DOM EXTRACTOR ====================
EXTRACT_JS = r"""
() => {
    const results = [];
    const rows = Array.from(document.querySelectorAll('table tr, [class*="fixture"], [class*="Fixture"], tr'));

    // Normalize known channel labels cleanly
    const cleanChannelName = (raw) => {
        if (!raw) return null;
        let s = raw.replace(/\s+/g, ' ').trim();
        if (!s || s.length > 40) return null;

        // Reject headings, sentences, promos, and placeholders
        if (/tv channels|start time|broadcast on|twenty20 international|get sky sports|watch live|download|t\.?b\.?c\.?|^\s*sky\s*$/i.test(s)) {
            return null;
        }

        const low = s.toLowerCase();
        if (low.includes('tnt sports 1')) return 'TNT Sports 1';
        if (low.includes('tnt sports 2')) return 'TNT Sports 2';
        if (low.includes('tnt sports 3')) return 'TNT Sports 3';
        if (low.includes('tnt sports 4')) return 'TNT Sports 4';
        if (low.includes('tnt sports')) return 'TNT Sports';
        if (low.includes('sky sports cricket')) return 'Sky Sports Cricket';
        if (low.includes('sky sports main event')) return 'Sky Sports Main Event';
        if (low.includes('sky sports')) return 'Sky Sports';
        if (low.includes('hbo max') || low === 'hbomax') return 'HBO Max';
        if (low.includes('willow')) return 'Willow Cricket';
        if (low.includes('sony ten') || low.includes('sony sports')) return 'Sony Sports';
        if (low.includes('star sports')) return 'Star Sports';

        return s;
    };

    for (const row of rows) {
        const text = (row.innerText || '').trim();
        if (!text) continue;

        if (/get sky sports|watch live!|download the wheresthematch/i.test(text) && !/\d{1,2}:\d{2}/.test(text)) {
            continue;
        }

        const timeMatch = text.match(/\b(\d{1,2}:\d{2}(?:\s*(?:AM|PM))?)\b/i);
        if (!timeMatch) continue;

        let matchup = '';
        const vMatch = text.match(/([A-Za-z][A-Za-z\s\.\'-]{1,35}?)\s+(?:v|vs)\s+([A-Za-z][A-Za-z\s\.\'-]{1,35}?)(?=\s+(?:Twenty20|ODI|Test|Today|Mon|Tue|Wed|Thu|Fri|Sat|Sun|\d{1,2}(?:st|nd|rd|th)|\d{1,2}:\d{2})|\n|$)/i);
        if (vMatch) {
            matchup = `${vMatch[1].trim()} vs ${vMatch[2].trim()}`;
        }

        const dateMatch = text.match(/(?:Today\s+)?(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}(?:st|nd|rd|th)\s+[A-Za-z]+\s+\d{4}/i)
            || text.match(/\d{1,2}(?:st|nd|rd|th)\s+[A-Za-z]+\s+\d{4}/i);

        const channels = [];
        const seen = new Set();
        const addChannel = (rawName) => {
            const norm = cleanChannelName(rawName);
            if (!norm) return;
            const key = norm.toLowerCase();
            if (!seen.has(key)) {
                seen.add(key);
                channels.push(norm);
            }
        };

        // 1. Extract from channel images (alt / title / src)
        const imgs = row.querySelectorAll('img');
        for (const img of imgs) {
            const alt = (img.getAttribute('alt') || '').trim();
            const title = (img.getAttribute('title') || '').trim();
            const src = (img.getAttribute('src') || '').toLowerCase();

            if (alt || title) {
                addChannel(alt || title);
            }
            if (src) {
                if (src.includes('tnt')) addChannel(src.match(/tnt[^a-z0-9]?[1-4]?/i)?.[0] || 'TNT Sports');
                if (src.includes('sky') && src.includes('cricket')) addChannel('Sky Sports Cricket');
                if (src.includes('hbo')) addChannel('HBO Max');
            }
        }

        // 2. Extract short broadcaster text tokens only (avoid full sentences)
        const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
        for (const line of lines) {
            if (line.length <= 35 && /tnt sports|sky sports cricket|hbo\s?max|willow|sony|star sports/i.test(line)) {
                addChannel(line);
            }
        }

        if (matchup && dateMatch) {
            results.push({
                matchup,
                date_raw: dateMatch[0],
                time_raw: timeMatch[1],
                league: "Twenty20 International",
                services: channels
            });
        }
    }

    return results;
}
"""


async def scrape_t20i_wheresthematch():
    ref_bd_now = datetime.now(BANGLADESH_TZ)
    ref_uk_now = ref_bd_now.astimezone(UK_TZ)

    print("🏏 Starting WherestheMatch T20I Scraper...")
    print(f"🕒 BD Now: {ref_bd_now.strftime('%Y-%m-%d %H:%M:%S')} | UK Now: {ref_uk_now.strftime('%Y-%m-%d %H:%M:%S')}")

    raw_items = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        context = await browser.new_context(
            locale="en-GB",
            timezone_id="Europe/London",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        page.set_default_timeout(60000)

        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2500)
            raw_items = await page.evaluate(EXTRACT_JS)
        finally:
            await context.close()
            await browser.close()

    unique_matches = {}
    for item in raw_items:
        uk_date = parse_uk_date(item.get("date_raw", ""), ref_uk_now.date())
        parsed_hm = parse_time_24h_or_12h(item.get("time_raw", ""))
        if not uk_date or not parsed_hm:
            continue

        hour, minute = parsed_hm
        uk_naive = datetime(uk_date.year, uk_date.month, uk_date.day, hour, minute)
        uk_dt = UK_TZ.localize(uk_naive)

        bd_start_dt = uk_dt.astimezone(BANGLADESH_TZ)
        bd_end_dt = bd_start_dt + timedelta(hours=T20_DURATION_HOURS)

        if not is_within_range(bd_start_dt, ref_bd_now):
            continue

        matchup = normalize_matchup(item.get("matchup", ""))
        if not matchup:
            continue

        key = (
            bd_start_dt.strftime("%Y-%m-%d"),
            bd_start_dt.strftime("%H:%M"),
            matchup
        )

        services = list(dict.fromkeys(item.get("services", [])))
        if key not in unique_matches:
            unique_matches[key] = {
                "Date": bd_start_dt.strftime("%Y-%m-%d"),
                "Start_Time": bd_start_dt.strftime("%H:%M"),
                "End_Time": bd_end_dt.strftime("%H:%M"),
                "League": "Twenty20 International",
                "Matchup": matchup,
                "Services": services
            }
        else:
            existing = set(unique_matches[key]["Services"])
            for s in services:
                if s not in existing:
                    unique_matches[key]["Services"].append(s)

    final_list = sorted(unique_matches.values(), key=lambda x: (x["Date"], x["Start_Time"]))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final_list, f, indent=2, ensure_ascii=False)

    print(f"✅ Saved {len(final_list)} T20I matches (BD Time) to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(scrape_t20i_wheresthematch())
    
