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
URL = "https://www.wheresthematch.com/twenty20-international-cricket-on-tv/"
UK_TZ = pytz.timezone("Europe/London")
BANGLADESH_TZ = pytz.timezone("Asia/Dhaka")

TIME_RANGE_HOURS_BEFORE = 4
TIME_RANGE_HOURS_AFTER = 168  # 7 days ahead so upcoming T20I series are included
T20_DURATION_HOURS = 4
OUTPUT_FILE = "cricket_schedule_bd.json"

# ==================== DATE & TIME PARSERS ====================
def parse_uk_date(date_text: str, ref_uk_date):
    """
    Parses strings like:
    'Today Tue 24th November 2026' or 'Fri 27th November 2026' or 'Wed 2nd December 2026'
    """
    if not date_text:
        return None
    cleaned = re.sub(r'\bToday\b', '', date_text, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'\s+', ' ', cleaned)
    # Remove ordinal suffixes: 1st, 2nd, 3rd, 4th, 24th -> 1, 2, 3, 4, 24
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

    # Fallback without year
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
    # Normalize "Australia v England" -> "Australia vs England"
    text = re.sub(r'\s+v(?:s)?\s+', ' vs ', text, flags=re.IGNORECASE)
    return text


def is_within_range(bd_dt: datetime, ref_bd_dt: datetime) -> bool:
    start = ref_bd_dt - timedelta(hours=TIME_RANGE_HOURS_BEFORE)
    end = ref_bd_dt + timedelta(hours=TIME_RANGE_HOURS_AFTER)
    return start <= bd_dt <= end


# ==================== DOM EXTRACTOR ====================
EXTRACT_JS = r"""
() => {
    const results = [];
    const rows = Array.from(document.querySelectorAll('table tr, [class*="fixture"], [class*="Fixture"], tr'));

    for (const row of rows) {
        const text = (row.innerText || '').trim();
        if (!text) continue;

        // Skip promo/ad rows
        if (/get sky sports|watch live!|cookie|privacy/i.test(text) && !/\d{1,2}:\d{2}/.test(text)) {
            continue;
        }

        const timeMatch = text.match(/\b(\d{1,2}:\d{2}(?:\s*(?:AM|PM))?)\b/i);
        if (!timeMatch) continue;

        // Find fixture teams like "Australia v England" or "Australia vs England"
        let matchup = '';
        const vMatch = text.match(/([A-Za-z][A-Za-z\s\.\'-]{1,35}?)\s+(?:v|vs)\s+([A-Za-z][A-Za-z\s\.\'-]{1,35}?)(?=\s+(?:Twenty20|ODI|Test|Today|Mon|Tue|Wed|Thu|Fri|Sat|Sun|\d{1,2}(?:st|nd|rd|th)|\d{1,2}:\d{2})|\n|$)/i);
        if (vMatch) {
            matchup = `${vMatch[1].trim()} vs ${vMatch[2].trim()}`;
        }

        // Find date string like "Tue 24th November 2026"
        const dateMatch = text.match(/(?:Today\s+)?(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{1,2}(?:st|nd|rd|th)\s+[A-Za-z]+\s+\d{4}/i)
            || text.match(/\d{1,2}(?:st|nd|rd|th)\s+[A-Za-z]+\s+\d{4}/i);

        // Extract broadcasters from text or image alts
        const channels = [];
        const seen = new Set();
        const addChannel = (ch) => {
            const clean = (ch || '').replace(/\s+/g, ' ').trim();
            if (!clean) return;
            const low = clean.toLowerCase();
            if (['t.b.c.', 'tbc', 'sky', 'get sky sports & watch live!'].includes(low)) return;
            if (clean.length < 2 || clean.length > 50) return;
            if (!seen.has(low)) {
                seen.add(low);
                channels.push(clean);
            }
        };

        // Check images inside row (e.g., TNT Sports, Sky Sports Cricket, HBO Max)
        const imgs = row.querySelectorAll('img');
        for (const img of imgs) {
            const alt = (img.getAttribute('alt') || '').trim();
            const title = (img.getAttribute('title') || '').trim();
            const src = (img.getAttribute('src') || '').toLowerCase();
            const label = alt || title;
            if (label && !/flag|ball|play|icon|arrow/i.test(label)) {
                addChannel(label);
            } else if (src) {
                if (src.includes('tnt')) addChannel('TNT Sports');
                else if (src.includes('sky') && src.includes('cricket')) addChannel('Sky Sports Cricket');
                else if (src.includes('hbo')) addChannel('HBO Max');
            }
        }

        // Also check lines for known channel names
        const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
        for (const line of lines) {
            if (/tnt sports|sky sports|hbo\s?max|tbc|t\.b\.c\.|willow|sony|star sports/i.test(line)) {
                if (!/get sky sports/i.test(line)) {
                    addChannel(line);
                }
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

    print(f"🏏 Starting WherestheMatch T20I Scraper...")
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
  
