const axios = require('axios');
const cheerio = require('cheerio');
const fs = require('fs');
const dayjs = require('dayjs');
const utc = require('dayjs/plugin/utc');
const timezone = require('dayjs/plugin/timezone');
const customParseFormat = require('dayjs/plugin/customParseFormat');

dayjs.extend(utc);
dayjs.extend(timezone);
dayjs.extend(customParseFormat);

// ========== CẤU HÌNH (CONFIGURATION) ==========
const DAY_ORDER = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const TIME_RANGE_HOURS = 48; // ৪৮ ঘণ্টার মধ্যে থাকা ম্যাচগুলো
const OUTPUT_FILE = './ausport_football_schedule_bd.json';

const MONTH_MAP = {
  January: 0, Jan: 0,
  February: 1, Feb: 1,
  March: 2, Mar: 2,
  April: 3, Apr: 3,
  May: 4,
  June: 5, Jun: 5,
  July: 6, Jul: 6,
  August: 7, Aug: 7,
  September: 8, Sep: 8, Sept: 8,
  October: 9, Oct: 9,
  November: 10, Nov: 10,
  December: 11, Dec: 11
};

// ========== ফুটবলের লিগ ও ফিল্টার কনফিগারেশন ==========
const FOOTBALL_CONFIG = {
  leagues: {
    'Premier League': ['arsenal', 'aston villa', 'bournemouth', 'brentford', 'brighton', 'chelsea',
                       'crystal palace', 'everton', 'fulham', 'leeds united', 'liverpool', 'manchester city',
                       'manchester united', 'newcastle', 'nottingham forest', 'sunderland', 'tottenham hotspur',
                       'hull city', 'ipswich town', 'coventry city'],
    'Serie A': ['inter milan', 'ac milan', 'napoli', 'juventus', 'roma', 'atalanta', 'lazio'],
    'La Liga': 'all',
    'Bundesliga': ['bayern', 'borussia dortmund', 'bayer leverkusen'],
    'Ligue 1': ['psg', 'olympique marseille'],
    'UEFA Champions League': 'all',
    'UEFA Europa League': 'all',
    'UEFA Europa Conference League': 'all',
    'World Cup': 'all',
    'EURO': 'all',
    'UEFA European Championship': 'all',
  },
  friendlyAllowedTeams: ['argentina', 'brazil', 'japan', 'south korea', 'nhật bản', 'hàn quốc'],
  excludeKeywords: ['u18', 'u19', 'u20', 'u21', 'u23', 'women', 'girls', 'boys', 'youth', 'junior', 'reserves', 'woman'],
};

function isFootballRelevant(competition, home, away, title) {
  const comp = (competition || '').toLowerCase();
  const h = (home || '').toLowerCase();
  const a = (away || '').toLowerCase();
  const t = (title || '').toLowerCase();

  for (const kw of FOOTBALL_CONFIG.excludeKeywords) {
    if (comp.includes(kw) || t.includes(kw)) return false;
  }

  const specialLeagues = ['uefa champions league', 'uefa europa league', 'uefa europa conference league',
                          'world cup', 'euro', 'uefa european championship'];
  if (specialLeagues.some(l => comp.includes(l))) return true;

  for (const [league, teams] of Object.entries(FOOTBALL_CONFIG.leagues)) {
    if (comp.includes(league.toLowerCase())) {
      if (teams === 'all') return true;
      const teamList = teams.map(item => item.toLowerCase());
      if (teamList.some(team => h.includes(team) || a.includes(team))) return true;
    }
  }

  if (comp.includes('friendly') || t.includes('friendly')) {
    const allowed = FOOTBALL_CONFIG.friendlyAllowedTeams;
    if (allowed.some(team => h.includes(team) || a.includes(team))) return true;
  }
  return false;
}

// শুধুমাত্র ফুটবলের জন্য ফিল্টার কার্যকর করা হলো (টেনিস বাদ দেওয়া হয়েছে)
function isEventRelevant(sport, competition, home, away, title) {
  const s = (sport || '').toLowerCase();
  if (s === 'soccer' || s === 'football') {
    return isFootballRelevant(competition, home, away, title);
  }
  return false;
}

// ========== বাংলাদেশের সময় রূপান্তর (Bangladesh Time Zone Conversion) ==========
function convertAedtToBangladeshTime(baseDate, timeStr) {
  if (!timeStr) return null;
  const match = timeStr.match(/^(\d{1,2}):(\d{2})(AM|PM)$/i);
  if (!match) return null;
  let [, hourStr, minuteStr, ampm] = match;
  let hour = parseInt(hourStr, 10);
  const minute = parseInt(minuteStr, 10);
  if (ampm.toUpperCase() === 'PM' && hour !== 12) hour += 12;
  if (ampm.toUpperCase() === 'AM' && hour === 12) hour = 0;
  
  // অস্ট্রেলিয়ার সিডনি সময় থেকে বাংলাদেশ সময় (Asia/Dhaka) কনভার্ট করা
  const aedtTime = dayjs(baseDate).tz('Australia/Sydney').hour(hour).minute(minute).second(0);
  return aedtTime.tz('Asia/Dhaka');
}

function getBangladeshInfo(baseDate, timeStr) {
  const dt = convertAedtToBangladeshTime(baseDate, timeStr);
  if (!dt) return null;
  return {
    datetime: dt.toISOString(),
    time: dt.format('HH:mm'),
    date: dt.format('DD/MM/YYYY'),
  };
}

// ========== স্ক্র্যাপিং ফাংশনসমূহ ==========
function fallbackDateForDay(pathSuffix) {
  const DAY_MAP = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 };
  const now = new Date();
  const currentDay = now.getDay();
  const targetDay = DAY_MAP[pathSuffix];
  const diff = targetDay - currentDay;
  const baseDate = new Date(now);
  baseDate.setDate(now.getDate() + diff);
  baseDate.setHours(0, 0, 0, 0);
  return { baseDate };
}

function resolveDateForPage($, pathSuffix) {
  const headerText = $('h2.dayInfo').first().text().trim();
  if (headerText) {
    const m = headerText.match(/(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+(\d{1,2})\.\s+([A-Za-z]+)/i);
    if (m) {
      const dayNum = parseInt(m[2], 10);
      const monthRaw = m[3];
      const monthName = monthRaw.charAt(0).toUpperCase() + monthRaw.slice(1).toLowerCase();
      const monthIdx = MONTH_MAP[monthName];
      if (!isNaN(dayNum) && monthIdx != null) {
        const now = new Date();
        const year = now.getFullYear();
        const baseDate = new Date(year, monthIdx, dayNum);
        baseDate.setHours(0, 0, 0, 0);
        return { baseDate };
      }
    }
  }
  return fallbackDateForDay(pathSuffix);
}

function findSportForEvent($, eventDiv) {
  const $event = $(eventDiv);
  const panelLeague = $event.closest('.panelLeague');
  if (panelLeague.length) {
    const panelType = panelLeague.prevAll('.panelType').first();
    if (panelType.length) {
      const h3 = panelType.find('h3').first();
      if (h3.length) {
        const img = h3.find('img').first();
        const span = h3.find('span.align-middle').first();
        const sport = (img.attr('title') || img.attr('alt') || '').trim() ||
                      span.text().trim() ||
                      h3.text().trim();
        if (sport) return sport;
      }
    }
  }
  let cur = $event.parent();
  for (let i = 0; i < 10 && cur.length; i++) {
    const h3 = cur.prevAll().find('h3').first();
    if (h3.length) {
      const img = h3.find('img').first();
      const span = h3.find('span.align-middle').first();
      const sport = (img.attr('title') || img.attr('alt') || '').trim() ||
                    span.text().trim() ||
                    h3.text().trim();
      if (sport) return sport;
    }
    cur = cur.parent();
  }
  return '';
}

function extractTimeFromHotText(text) {
  const m = text.match(/\bfrom\s+(\d{1,2}:\d{2}(?:AM|PM))\b/i);
  return m ? m[1].toUpperCase() : "";
}

function resolveBaseDateFromHotText(text) {
  const now = new Date();
  if (/^Tomorrow\b/i.test(text)) {
    const d = new Date(now);
    d.setDate(now.getDate() + 1);
    d.setHours(0, 0, 0, 0);
    return d;
  }
  const m = text.match(/^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\.?\s+(\d{1,2})\s+([A-Za-z]+)\b/i);
  if (m) {
    const dayNum = parseInt(m[2], 10);
    const monthRaw = m[3];
    const monthName = monthRaw.charAt(0).toUpperCase() + monthRaw.slice(1).toLowerCase();
    const monthIdx = MONTH_MAP[monthName];
    if (monthIdx != null && !isNaN(dayNum)) {
      const year = now.getFullYear();
      const d = new Date(year, monthIdx, dayNum);
      d.setHours(0, 0, 0, 0);
      return d;
    }
  }
  const d = new Date(now);
  d.setHours(0, 0, 0, 0);
  return d;
}

function parseHotEvents($) {
  const rows = [];
  $(".panel-body-desktop .hotEvents .list-group-item").each((idx, el) => {
    const item = $(el);
    const open = item.find(".openUrl").first();
    if (!open.length) return;
    const line1 = open.find(".eventText > div").first().text().replace(/\s+/g, " ").trim();
    const line2 = open.find(".eventText > div").eq(1).text().replace(/\s+/g, " ").trim();
    const [left, matchRaw] = line1.split("|").map(v => (v || "").trim());
    const datetimeText = left || "";
    const match = matchRaw || "";
    const sport = (line2.split("|")[0] || "").trim();
    const league = (line2.split("|")[1] || "").replace(/\s+/g, " ").trim();
    let channel = item.find(".ml-10 img").attr("title") || item.find(".ml-10 img").attr("alt") || "";
    channel = channel.replace(/Live on\s*/i, "").trim();
    const timeAedt = extractTimeFromHotText(datetimeText);
    const baseDate = resolveBaseDateFromHotText(datetimeText);
    const home = match.includes(" - ") ? match.split(" - ")[0].trim() : match.trim();
    const away = match.includes(" - ") ? match.split(" - ")[1].trim() : "";
    
    const bdInfo = timeAedt ? getBangladeshInfo(baseDate, timeAedt) : null;
    rows.push({
      sport, competition: league || "Hot Events", home, away,
      channels: channel,
      bangladesh_time: bdInfo?.time || '',
      bangladesh_date: bdInfo?.date || '',
      bangladesh_datetime: bdInfo?.datetime || null,
    });
  });
  return rows;
}

async function scrapeDay(pathSuffix) {
  const url = `https://ausportguide.com/live-sports-tv-guide/${pathSuffix}`;
  console.log('Scraping:', url);
  const res = await axios.get(url, {
    headers: {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36',
      'Accept-Language': 'en-US,en;q=0.9'
    },
    timeout: 30000,
    maxRedirects: 5,
    validateStatus: status => status >= 200 && status < 400
  });
  const $ = cheerio.load(res.data);
  const dateInfo = resolveDateForPage($, pathSuffix);
  const rows = [];
  let currentCompetition = '';

  $('h3, .leagueTitle, div.list-group-item.d-flex.gap-3.shadow-sm').each((idx, el) => {
    const $el = $(el);
    if ($el.hasClass('leagueTitle')) {
      currentCompetition = $el.find('span.align-middle').first().text().trim();
      return;
    }
    if ($el.hasClass('list-group-item')) {
      const eventDiv = $el;
      const timeAedt = eventDiv.find('.eventTime').first().text().trim();
      if (!timeAedt) return;
      const eventText = eventDiv.find('.eventText').first();
      const teamDivs = eventText.children('div').filter((i, e) => {
        const cls = $(e).attr('class') || '';
        return !cls.includes('gameSpacer') && !cls.includes('fs-10');
      });
      const home = (teamDivs.eq(0).text() || '').replace(/\s+/g, ' ').trim();
      const away = (teamDivs.eq(1).text() || '').replace(/\s+/g, ' ').trim();
      const title = eventText.find('div.fs-10 i').first().text().replace(/\s+/g, ' ').trim();
      const channels = [];
      eventDiv.find('div.text-end img.stationImg').each((i, img) => {
        let t = $(img).attr('title') || $(img).attr('alt') || '';
        t = t.replace(/Live on\s*/i, '').trim();
        if (t) channels.push(t);
      });
      const sport = findSportForEvent($, eventDiv);
      const bdInfo = getBangladeshInfo(dateInfo.baseDate, timeAedt);
      rows.push({
        day: pathSuffix,
        sport, competition: currentCompetition, home, away, title,
        channels: channels.join(' | '),
        bangladesh_time: bdInfo?.time || '',
        bangladesh_date: bdInfo?.date || '',
        bangladesh_datetime: bdInfo?.datetime || null,
      });
    }
  });
  const hotRows = parseHotEvents($);
  if (hotRows.length) console.log(`HotEvents for ${pathSuffix}: ${hotRows.length}`);
  rows.push(...hotRows);
  console.log(`Rows for ${pathSuffix}: ${rows.length}`);
  return rows;
}

// ========== প্রধান এক্সিকিউশন (MAIN) ==========
(async () => {
  let allRows = [];
  for (const d of DAY_ORDER) {
    try {
      const rows = await scrapeDay(d);
      allRows = allRows.concat(rows);
    } catch (e) {
      console.error(`Skipping day ${d} due to error:`, e.message);
    }
  }
  
  // ১. শুধুমাত্র ফুটবল ও লিগ ফিল্টার অনুযায়ী ফিল্টার করা
  let filtered = allRows.filter(row => isEventRelevant(row.sport, row.competition, row.home, row.away, row.title));
  console.log('After football league filter:', filtered.length);
  
  // ২. ৪৮ ঘণ্টার সময়ের উইন্ডো ফিল্টার করা
  const now = dayjs();
  filtered = filtered.filter(row => {
    if (!row.bangladesh_datetime) return false;
    const diff = dayjs(row.bangladesh_datetime).diff(now, 'hour', true);
    return diff >= 0 && diff <= TIME_RANGE_HOURS;
  });
  console.log(`After time filter (${TIME_RANGE_HOURS}h):`, filtered.length);
  
  // ৩. ডুপ্লিকেট রিমুভ করা
  const seen = new Set();
  filtered = filtered.filter(row => {
    const key = `${row.bangladesh_date}|${row.bangladesh_time}|${row.sport}|${row.competition}|${row.home}|${row.away}`.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  console.log('After deduplication:', filtered.length);
  
  // ৪. সময়ের ক্রমানুসারে সাজানো
  filtered.sort((a,b) => dayjs(a.bangladesh_datetime).diff(dayjs(b.bangladesh_datetime)));
  
  // ৫. JSON ফাইলে আউটপুট সেভ করা
  const output = filtered.map(r => ({
    competition: r.competition,
    home: r.home,
    away: r.away,
    match_time: r.bangladesh_time,
    match_date: r.bangladesh_date,
    channels: r.channels,
    sport: r.sport,
  }));
  
  fs.writeFileSync(OUTPUT_FILE, JSON.stringify(output, null, 2));
  console.log('JSON written successfully:', OUTPUT_FILE);
})();
    
