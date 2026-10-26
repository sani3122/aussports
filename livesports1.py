#!/usr/bin/env python3
"""
Live Sports Schedule Scraper (Livesportsontv + Footonsat)
Converted to Strictly Bangladesh Standard Time (BST - Asia/Dhaka)
Filtered for Football / Soccer Only (No Tennis, No Women's, No Youth)
Output: liveonsat_schedule_bd.json
"""

import asyncio
import json
import re
import aiohttp
from datetime import datetime, timedelta, timezone
import pytz
from playwright.async_api import async_playwright

# ==================== CONFIGURATION ====================
BANGLADESH_TZ = pytz.timezone("Asia/Dhaka") # GMT+6
WITA_TZ = pytz.timezone("Asia/Makassar")    # GMT+8 (Page default render timezone)

TIME_RANGE_HOURS_BEFORE = 4
TIME_RANGE_HOURS_AFTER = 72
OUTPUT_FILE = "liveonsat_schedule_bd.json"

FOOTONSAT_URLS = [
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/premierleague.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/seriea.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/laliga.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/bundesliga.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/ligue1.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/championsleague.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/europaleague.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/ConferenceLeague.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/worldcup.json",
    "https://raw.githubusercontent.com/fairbird/footonsat-api/refs/heads/main/today.json"
]

# ==================== ALLOWED LEAGUES (FOOTBALL ONLY) ====================
ALLOWED_LEAGUES = {
    "Premier League", "Serie A", "La Liga", "Bundesliga", "Ligue 1",
    "UEFA Champions League", "UEFA Europa League", "UEFA Europa Conference League",
    "UEFA European Championship", "FIFA World Cup", "UEFA Nations League",
    "International Friendlies", "FA Cup", "Carabao Cup"
}

PREMIER_LEAGUE_TEAMS = {
    "arsenal", "aston villa", "bournemouth", "brentford", "brighton", "chelsea",
    "crystal palace", "everton", "fulham", "leeds united", "liverpool", "manchester city",
    "manchester united", "newcastle", "nottingham forest", "sunderland", "tottenham",
    "hull city", "ipswich town", "coventry city"
}

ALLOWED_TEAMS_PER_LEAGUE = {
    "Premier League": PREMIER_LEAGUE_TEAMS,
    "Serie A": {"inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"},
    "La Liga": None,
    "Bundesliga": {"bayern munich", "borussia dortmund", "bayer leverkusen"},
    "Ligue 1": {"psg", "paris saint-germain", "marseille", "olympique marseille"},
    "FA Cup": PREMIER_LEAGUE_TEAMS,
    "Carabao Cup": PREMIER_LEAGUE_TEAMS,
    "UEFA Champions League": None,
    "UEFA Europa League": None,
    "UEFA Europa Conference League": None,
    "UEFA European Championship": None,
    "FIFA World Cup": None,
    "UEFA Nations League": None,
    "International Friendlies": None,
}

# ==================== HELPER FUNCTIONS ====================
def parse_short_date(date_str: str, ref_date):
    if not date_str:
        return None
    s = date_str.strip().replace(',', '')
    s = re.sub(r'\s+\d{4}$', '', s).strip()

    for fmt in ("%b %d", "%d %b", "%B %d", "%d %B"):
        try:
            dt = datetime.strptime(s, fmt)
            dt = dt.replace(year=ref_date.year)
            delta = (dt.date() - ref_date).days
            if delta < -180:
                dt = dt.replace(year=ref_date.year + 1)
            elif delta > 180:
                dt = dt.replace(year=ref_date.year - 1)
            return dt.date()
        except ValueError:
            continue
    return None

def is_within_time_range(dt: datetime, ref: datetime) -> bool:
    start = ref - timedelta(hours=TIME_RANGE_HOURS_BEFORE)
    end = ref + timedelta(hours=TIME_RANGE_HOURS_AFTER)
    return start <= dt <= end

def is_youth_or_women(matchup: str, league: str) -> bool:
    combined = f"{matchup} {league}".lower()
    women_keywords = [
        "women", "womens", "women's", "woman", "female", "frauen", "damen", "weiblich",
        "donne", "femminile", "mujeres", "femenino", "femenina", "femmes", "féminin",
        "féminine", "mulheres", "feminino", "vrouwen", "női", "kadın", "w/serie"
    ]
    youth_keywords = [
        "youth", "junior", "academy", "reserves", "reserve", "ii", "zweite", "second team",
        "sub", "u-", "under", "jugend", "juniorer", "giovanili", "primavera", "cantera",
        "filial", "jeunes", "espoirs", "jong", "beloften", "greek super"
    ]
    for kw in women_keywords + youth_keywords:
        if kw in combined:
            return True
    return False

def normalize_league(league: str) -> str:
    league_lower = league.lower()
    if "fa cup" in league_lower:
        return "FA Cup"
    if "carabao cup" in league_lower or "league cup" in league_lower:
        return "Carabao Cup"
    if "premier league" in league_lower:
        return "Premier League"
    if "serie a" in league_lower:
        return "Serie A"
    if "la liga" in league_lower or "primera" in league_lower:
        return "La Liga"
    if "bundesliga" in league_lower:
        return "Bundesliga"
    if "ligue 1" in league_lower:
        return "Ligue 1"
    if "champions league" in league_lower:
        return "UEFA Champions League"
    if "europa league" in league_lower:
        return "UEFA Europa League"
    if "conference league" in league_lower:
        return "UEFA Europa Conference League"
    if "nations league" in league_lower:
        return "UEFA Nations League"
    if "european championship" in league_lower or "euro" in league_lower:
        return "UEFA European Championship"
    if "world cup" in league_lower:
        return "FIFA World Cup"
    if "friendly" in league_lower:
        return "International Friendlies"
    return league.strip()

# ==================== TEAM NAME MAPPING ====================
TEAM_NAME_MAPPING = {
    # Premier League
    "manchester united": "Manchester United", "man utd": "Manchester United", "man united": "Manchester United",
    "manchester city": "Manchester City", "man city": "Manchester City",
    "arsenal": "Arsenal", "chelsea": "Chelsea", "liverpool": "Liverpool", "tottenham hotspur": "Tottenham Hotspur",
    "tottenham": "Tottenham Hotspur", "spurs": "Tottenham Hotspur", "aston villa": "Aston Villa",
    "newcastle united": "Newcastle United", "newcastle": "Newcastle United", "west ham united": "West Ham United",
    "west ham": "West Ham United", "everton": "Everton", "fulham": "Fulham", "crystal palace": "Crystal Palace",
    "brighton & hove albion": "Brighton", "brighton": "Brighton", "brentford": "Brentford", "leeds united": "Leeds United",
    "wolverhampton wanderers": "Wolverhampton Wanderers", "wolves": "Wolverhampton Wanderers",
    "nottingham forest": "Nottingham Forest", "sunderland": "Sunderland", "leicester city": "Leicester City",
    "southampton": "Southampton", "burnley": "Burnley", "ipswich town": "Ipswich Town",

    # La Liga
    "real madrid": "Real Madrid", "madrid": "Real Madrid", "fc barcelona": "Barcelona", "barcelona": "Barcelona",
    "atletico madrid": "Atletico Madrid", "atlético madrid": "Atletico Madrid", "atletico": "Atletico Madrid",
    "real sociedad": "Real Sociedad", "real betis": "Real Betis", "athletic bilbao": "Athletic Bilbao",
    "valencia": "Valencia", "villarreal": "Villarreal", "sevilla": "Sevilla", "getafe": "Getafe",
    "espanyol": "Espanyol", "osasuna": "Osasuna", "rayo vallecano": "Rayo Vallecano", "girona": "Girona",

    # Serie A
    "ac milan": "AC Milan", "milan": "AC Milan", "inter milan": "Inter Milan", "inter": "Inter Milan",
    "juventus": "Juventus", "juve": "Juventus", "napoli": "Napoli", "roma": "Roma", "as roma": "Roma",
    "lazio": "Lazio", "atalanta": "Atalanta", "fiorentina": "Fiorentina", "torino": "Torino", "bologna": "Bologna",

    # Bundesliga
    "bayern munich": "Bayern Munich", "bayern münchen": "Bayern Munich", "bayern": "Bayern Munich",
    "borussia dortmund": "Borussia Dortmund", "dortmund": "Borussia Dortmund", "bayer leverkusen": "Bayer Leverkusen",
    "rb leipzig": "RB Leipzig", "eintracht frankfurt": "Eintracht Frankfurt", "vfb stuttgart": "VfB Stuttgart",

    # Ligue 1
    "psg": "Paris Saint-Germain", "paris saint-germain": "Paris Saint-Germain", "marseille": "Marseille",
    "lyon": "Lyon", "monaco": "Monaco", "lille": "Lille", "nice": "Nice", "rennes": "Rennes"
}

def normalize_team_name(name: str) -> str:
    if not name:
        return name
    name_lower = name.lower().strip()
    name_lower = re.sub(r'\b(fc|sc|as|us|ac|ssc|sv|tsv|vfl|cf|cd)\b', '', name_lower)
    name_lower = re.sub(r'[^\w\s]', '', name_lower).strip()
    best_match = name
    best_len = 0
    for key, canonical in TEAM_NAME_MAPPING.items():
        if key in name_lower and len(key) > best_len:
            best_len = len(key)
            best_match = canonical
    return best_match

def normalize_matchup(matchup: str):
    matchup = matchup.strip()
    home = away = None
    if '@' in matchup:
        parts = [p.strip() for p in matchup.split('@')]
        if len(parts) == 2:
            away, home = parts
    elif 'vs' in matchup.lower():
        parts = [p.strip() for p in re.split(r'\s+vs\s+', matchup, flags=re.IGNORECASE)]
        if len(parts) == 2:
            home, away = parts
    if not away or not home:
        return matchup
    away_norm = normalize_team_name(away)
    home_norm = normalize_team_name(home)
    return f"{home_norm} vs {away_norm}"

def is_match_allowed(league: str, matchup: str) -> bool:
    if league not in ALLOWED_LEAGUES:
        return False
    if league == "International Friendlies":
        return True
    allowed_teams = ALLOWED_TEAMS_PER_LEAGUE.get(league)
    if allowed_teams is None:
        return True
    matchup_lower = matchup.lower()
    return any(team in matchup_lower for team in allowed_teams)

# ==================== LIVESPORTSONTV CONFIG (FOOTBALL ONLY) ====================
LEAGUES_CONFIG = {
    "Premier League": {"url": "https://www.livesportsontv.com/league/premier-league", "teams": PREMIER_LEAGUE_TEAMS},
    "Serie A": {"url": "https://www.livesportsontv.com/league/serie-a", "teams": {"inter milan", "ac milan", "napoli", "juventus", "roma", "atalanta", "lazio"}},
    "La Liga": {"url": "https://www.livesportsontv.com/league/la-liga", "teams": {"barcelona", "real madrid", "atletico madrid"}},
    "Bundesliga": {"url": "https://www.livesportsontv.com/league/bundesliga-5", "teams": {"bayern", "borussia dortmund", "bayer leverkusen"}},
    "Ligue 1": {"url": "https://www.livesportsontv.com/league/ligue-1-3", "teams": {"psg", "marseille"}},
    "UEFA Champions League": {"url": "https://www.livesportsontv.com/league/uefa-champions-league", "teams": None},
    "UEFA Europa League": {"url": "https://www.livesportsontv.com/league/uefa-europa-league", "teams": None},
    "UEFA Europa Conference League": {"url": "https://www.livesportsontv.com/league/uefa-conference-league", "teams": None},
    "UEFA European Championship": {"url": "https://www.livesportsontv.com/league/uefa-european-championship", "teams": None},
    "FIFA World Cup": {"url": "https://www.livesportsontv.com/league/world-cup-5", "teams": None},
    "UEFA Nations League": {"url": "https://www.livesportsontv.com/league/uefa-nations-league", "teams": None},
    "International Friendlies": {"url": "https://www.livesportsontv.com/league/international-friendly-2", "teams": None},
    "FA Cup": {"url": "https://www.livesportsontv.com/league/fa-cup", "teams": None, "custom_filter": "premier_league_only"},
    "Carabao Cup": {"url": "https://www.livesportsontv.com/league/league-cup", "teams": None, "custom_filter": "premier_league_only"},
}

EXTRACT_JS = r"""
() => {
    const output = [];
    const extractDate = (eventElement) => {
        const dateEl = eventElement.querySelector('[class*="FixtureItem_date" i], [class*="FixtureListByTime_date" i]');
        if (dateEl) {
            const t = (dateEl.textContent || '').trim();
            if (t) return t;
        }
        const MONTHS_ABBR = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'];
        const MONTHS_FULL = ['january','february','march','april','may','june','july','august','september','october','november','december'];
        const allMonths = MONTHS_ABBR.concat(MONTHS_FULL);
        const candidates = eventElement.querySelectorAll('div, span');
        for (const el of candidates) {
            let t = (el.textContent || '').trim();
            if (!t || t.length > 25) continue;
            t = t.replace(/,?\s*\d{4}$/, '').trim();
            let month = null, day = null;
            const m1 = t.match(/^([A-Za-z]+)\s+(\d{1,2})$/);
            const m2 = t.match(/^(\d{1,2})\s+([A-Za-z]+)$/);
            if (m1) { month = m1[1].toLowerCase(); day = parseInt(m1[2]); }
            else if (m2) { day = parseInt(m2[1]); month = m2[2].toLowerCase(); }
            if (month && day && allMonths.includes(month)) return t;
        }
        return '';
    };

    const extractChannels = (eventElement) => {
        const channels = [];
        const seen = new Set();
        const add = (name, type, url) => {
            name = (name || '').replace(/\s+/g, ' ').trim();
            if (!name) return;
            const low = name.toLowerCase();
            if (['logo', 'image', 'icon', 'team logo', 'channel'].includes(low)) return;
            if (low.length < 2 || low.length > 80) return;
            if (seen.has(low)) return;
            seen.add(low);
            channels.push(name);
        };

        let chips = Array.from(eventElement.querySelectorAll('[class*="channelChip" i], [class*="ChannelChip"], [class*="channel-chip"]'));
        for (const el of chips) {
            let name = el.querySelector('[class*="channelChipText" i], [class*="ChannelChipText"]')?.textContent || '';
            if (!name) name = el.querySelector('img')?.getAttribute('alt') || el.textContent || '';
            add(name);
        }
        if (channels.length === 0) {
            const links = eventElement.querySelectorAll('a[href*="/channel/"]');
            for (const link of links) {
                add(link.textContent?.trim() || link.querySelector('img')?.getAttribute('alt')?.trim() || '');
            }
        }
        return channels;
    };

    const eventElements = document.querySelectorAll('[class*="FixtureItem_container__"]');
    for (const eventElement of eventElements) {
        const link = eventElement.querySelector('a[href*="/match/"]');
        const title = link?.getAttribute("aria-label")?.trim();
        const href = link?.getAttribute("href");
        const time = eventElement.querySelector('[class*="FixtureItem_time__"]')?.textContent?.trim() || "";
        const dateText = extractDate(eventElement);
        if (title && href && time) {
            output.push({ title, href, time, date: dateText, channels: extractChannels(eventElement) });
        }
    }
    return output;
}
"""

async def scrape_livesportsontv(ref_bd_time: datetime):
    all_games = []
    semaphore = asyncio.Semaphore(4)

    async def scrape_one(league_name, cfg):
        async with semaphore:
            return await scrape_league(league_name, cfg, ref_bd_time)

    tasks = [scrape_one(name, cfg) for name, cfg in LEAGUES_CONFIG.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, list):
            all_games.extend(result)

    return all_games

async def scrape_league(league_name: str, cfg: dict, ref_bd_time: datetime):
    url = cfg["url"]
    team_filter = cfg.get("teams")
    custom_filter = cfg.get("custom_filter")
    games = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu"])
        context = await browser.new_context(
            locale="en-US", timezone_id="Asia/Makassar",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(2000)
            raw_events = await page.evaluate(EXTRACT_JS)

            for raw in raw_events:
                match = re.match(r'(\d{1,2}):(\d{2})\s*(AM|PM)', raw['time'], re.IGNORECASE)
                if not match:
                    continue
                hour, minute = int(match.group(1)), int(match.group(2))
                meridiem = match.group(3).upper()
                if meridiem == 'PM' and hour != 12: hour += 12
                elif meridiem == 'AM' and hour == 12: hour = 0

                event_date = parse_short_date(raw.get('date', ''), ref_bd_time.date())
                if not event_date: continue

                # convert from page rendering timezone to BD timezone
                page_dt = WITA_TZ.localize(datetime(event_date.year, event_date.month, event_date.day, hour, minute))
                bd_start_dt = page_dt.astimezone(BANGLADESH_TZ)
                bd_end_dt = bd_start_dt + timedelta(hours=2, minutes=30)

                if not is_within_time_range(bd_start_dt, ref_bd_time):
                    continue

                matchup = raw['title']
                if is_youth_or_women(matchup, league_name):
                    continue

                league_display = normalize_league(league_name)
                norm_matchup = normalize_matchup(matchup)

                if team_filter and not any(t.lower() in matchup.lower() for t in team_filter):
                    continue

                games.append({
                    "Date": bd_start_dt.strftime("%Y-%m-%d"),
                    "Start_Time": bd_start_dt.strftime("%H:%M"),
                    "End_Time": bd_end_dt.strftime("%H:%M"),
                    "League": league_display,
                    "Matchup": norm_matchup,
                    "Services": raw.get('channels', [])
                })
        except Exception as e:
            print(f"Error scraping {league_name}: {e}")
        finally:
            await context.close()
            await browser.close()

    return games

# ==================== FOOTONSAT ====================
async def fetch_footonsat_data(ref_bd_time: datetime):
    all_matches = []
    async with aiohttp.ClientSession() as session:
        for url in FOOTONSAT_URLS:
            try:
                async with session.get(url, timeout=30) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        data = json.loads(text)
                        items = data.get("footonsat", [])
                        matches = parse_footonsat_items(items, ref_bd_time)
                        all_matches.extend(matches)
            except Exception as e:
                print(f"Error fetching {url}: {e}")
    return all_matches

def parse_footonsat_items(items, ref_bd_time):
    matches = []
    current_match = None
    current_channels = []
    for item in items:
        if "match" in item and "compet" in item:
            if current_match:
                try:
                    dt_utc = pytz.utc.localize(datetime.strptime(f"{current_match['date']} {current_match['time']}", "%Y-%m-%d %H:%M"))
                    dt_bd = dt_utc.astimezone(BANGLADESH_TZ)
                    dt_end = dt_bd + timedelta(hours=2, minutes=30)
                    if is_within_time_range(dt_bd, ref_bd_time):
                        league_raw = current_match['compet'].strip()
                        if not is_youth_or_women(current_match['match'], league_raw):
                            league = normalize_league(league_raw)
                            if is_match_allowed(league, current_match['match']):
                                matches.append({
                                    "Date": dt_bd.strftime("%Y-%m-%d"),
                                    "Start_Time": dt_bd.strftime("%H:%M"),
                                    "End_Time": dt_end.strftime("%H:%M"),
                                    "League": league,
                                    "Matchup": normalize_matchup(current_match['match'].strip()),
                                    "Services": current_channels.copy()
                                })
                except Exception:
                    pass
            current_match = item
            current_channels = []
        elif "channel" in item and current_match and item.get("related_to", "").strip() == current_match['match'].strip():
            ch_name = item['channel'].strip()
            ch_name = re.sub(r'[📺]', '', ch_name).strip()
            if ch_name:
                current_channels.append(ch_name)
    return matches

# ==================== MAIN EXECUTION ====================
async def main():
    ref_bd_time = datetime.now(BANGLADESH_TZ)
    print(f"🚀 LiveSports & Footonsat Scraper Started (BD Time: {ref_bd_time.strftime('%Y-%m-%d %H:%M:%S')})")

    games_live = await scrape_livesportsontv(ref_bd_time)
    print(f"🏟️ Fetched from LiveSportsOnTV: {len(games_live)} matches")

    games_foot = await fetch_footonsat_data(ref_bd_time)
    print(f"🛰️ Fetched from Footonsat: {len(games_foot)} matches")

    # Merge & Deduplicate
    unique = {}
    for g in games_live + games_foot:
        key = (g["Date"], g["Start_Time"], g["League"], g["Matchup"])
        if key not in unique:
            unique[key] = {
                "Date": g["Date"],
                "Start_Time": g["Start_Time"],
                "End_Time": g["End_Time"],
                "League": g["League"],
                "Matchup": g["Matchup"],
                "Services": list(g["Services"])
            }
        else:
            existing = set(unique[key]["Services"])
            new_services = [s for s in g["Services"] if s not in existing]
            if new_services:
                unique[key]["Services"].extend(new_services)

    final = list(unique.values())
    final.sort(key=lambda x: (x["Date"], x["Start_Time"]))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(final, f, indent=2, ensure_ascii=False)

    print(f"🎉 Saved {len(final)} football matches to: {OUTPUT_FILE}")

if __name__ == "__main__":
    asyncio.run(main())
