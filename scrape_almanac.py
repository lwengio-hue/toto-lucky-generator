"""
Chinese Almanac (黄历 / Tung Shing) Scraper v3
================================================
Scrapes daily almanac data and saves to SQLite DB.

PRIMARY SOURCE  : chinese-calendar.net      (rich per-hour data, works everywhere)
SECONDARY SOURCE: chinesecalendaronline.com (correct lunar date + auspicious directions)
                  → Singapore version, verified correct against physical 通书

LUNAR DATE NOTE:
  All Almanac books for SG/HK/MY/TW use GMT+8 (120°E) as reference.
  chinesecalendaronline.com matches Singapore physical calendar — use this.
  chinese-calendar.net may be off by ±1 day at lunar month boundaries.

Usage:
  pip install pytz requests beautifulsoup4

  python scrape_almanac.py --print --timezone sg
  python scrape_almanac.py --print --timezone germany
  python scrape_almanac.py --from 2026-01-01 --to 2026-12-31
  python scrape_almanac.py --from 2026-01-01 --to 2027-12-31
  python scrape_almanac.py --date 2026-04-16 --print --timezone sg --force
"""

from __future__ import annotations
import requests
import sqlite3
import json
import re
import os
import time
import argparse
from datetime import datetime, date, timedelta
from bs4 import BeautifulSoup

try:
    import pytz
    HAS_PYTZ = True
except ImportError:
    HAS_PYTZ = False

os.makedirs("data", exist_ok=True)

# ── Config ─────────────────────────────────────────────────────────────────────
DB_PATH       = "data/almanac.db"
PRIMARY_URL   = "https://chinese-calendar.net/{date}"
SECONDARY_URL = "https://www.chinesecalendaronline.com/{y}/{m}/{d}.htm"
DELAY_SEC     = 1.5
TIMEOUT_SEC   = 20
MAX_RETRIES   = 3

SHI_CHEN_TIMES = {
    "Zi"  : ("23:00", "00:59"),
    "Chou": ("01:00", "02:59"),
    "Yin" : ("03:00", "04:59"),
    "Mao" : ("05:00", "06:59"),
    "Chen": ("07:00", "08:59"),
    "Si"  : ("09:00", "10:59"),
    "Wu"  : ("11:00", "12:59"),
    "Wei" : ("13:00", "14:59"),
    "Shen": ("15:00", "16:59"),
    "You" : ("17:00", "18:59"),
    "Xu"  : ("19:00", "20:59"),
    "Hai" : ("21:00", "22:59"),
}
SHI_CHEN_ORDER = ["Zi","Chou","Yin","Mao","Chen","Si","Wu","Wei","Shen","You","Xu","Hai"]

TIMEZONE_ALIASES = {
    "sg"        : "Asia/Singapore",
    "singapore" : "Asia/Singapore",
    "hk"        : "Asia/Hong_Kong",
    "hongkong"  : "Asia/Hong_Kong",
    "my"        : "Asia/Kuala_Lumpur",
    "malaysia"  : "Asia/Kuala_Lumpur",
    "tw"        : "Asia/Taipei",
    "taiwan"    : "Asia/Taipei",
    "cn"        : "Asia/Shanghai",
    "china"     : "Asia/Shanghai",
    "germany"   : "Europe/Berlin",
    "austria"   : "Europe/Vienna",
    "uk"        : "Europe/London",
    "us_east"   : "America/New_York",
    "us_west"   : "America/Los_Angeles",
    "australia" : "Australia/Sydney",
    "japan"     : "Asia/Tokyo",
    "india"     : "Asia/Kolkata",
    "uae"       : "Asia/Dubai",
    "canada"    : "America/Toronto",
}
# ──────────────────────────────────────────────────────────────────────────────


def init_db(conn: sqlite3.Connection):
    """Create almanac table. Migrates older DBs automatically."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS almanac (
            gregorian_date      TEXT PRIMARY KEY,
            day_of_week         TEXT,
            lunar_date          TEXT,
            solar_term          TEXT,
            year_pillar         TEXT,
            year_pillar_zh      TEXT,
            month_pillar        TEXT,
            month_pillar_zh     TEXT,
            day_pillar          TEXT,
            day_pillar_zh       TEXT,
            clash_zodiac        TEXT,
            evil_direction      TEXT,
            auspicious_acts     TEXT,
            inauspicious_acts   TEXT,
            good_shi_chen       TEXT,
            auspicious_times    TEXT,
            inauspicious_times  TEXT,
            god_of_joy          TEXT,
            god_of_happiness    TEXT,
            god_of_wealth       TEXT,
            hourly_json         TEXT,
            scraped_at          TEXT
        )
    """)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(almanac)").fetchall()}
    new_cols = {
        "solar_term"        : "TEXT",
        "year_pillar_zh"    : "TEXT",
        "month_pillar_zh"   : "TEXT",
        "day_pillar_zh"     : "TEXT",
        "good_shi_chen"     : "TEXT",
        "auspicious_times"  : "TEXT",
        "inauspicious_times": "TEXT",
        "god_of_joy"        : "TEXT",
        "god_of_happiness"  : "TEXT",
        "god_of_wealth"     : "TEXT",
    }
    for col, dtype in new_cols.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE almanac ADD COLUMN {col} {dtype}")
    conn.commit()


# ── PRIMARY SCRAPER: chinese-calendar.net ─────────────────────────────────────

def parse_primary(soup: BeautifulSoup, target_date: date) -> dict | None:
    """
    Parse chinese-calendar.net for daily + hourly almanac data.

    FIX v3: Parse each MuiGrid-item individually (not box2 as combined string)
    to prevent auspicious/inauspicious content from bleeding into each other.
    """

    # ── Day header / info box ──────────────────────────────────────────────────
    info_box = soup.find("div", class_=re.compile("infoOutBox|box1"))
    if not info_box:
        return None

    full_txt = info_box.get_text(separator=" | ", strip=True)

    day_of_week = None
    m = re.search(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)", full_txt)
    if m:
        day_of_week = m.group(1)

    # Lunar date from primary (may be ±1 day off at month boundaries)
    # — overridden by secondary source if available
    lunar_date = None
    m = re.search(r"Lunar Date\s*\|\s*([^|]+)", full_txt)
    if m:
        lunar_date = m.group(1).strip()

    solar_term = None
    m = re.search(r"Solar Term\s*\|\s*([^|]+)", full_txt)
    if m:
        st = m.group(1).strip()
        if st and st.lower() != "none":
            solar_term = st

    # Pillars  e.g. "Bing Wu (丙 午) Fire Horse"
    def parse_pillar(label):
        pat = rf"{label} Pill?er\s*\|\s*([^|]+)"
        pm = re.search(pat, full_txt, re.IGNORECASE)
        if not pm:
            return None, None
        raw = pm.group(1).strip()
        zh_m = re.search(r"\(([^)]+)\)", raw)
        zh = zh_m.group(1).replace(" ", "") if zh_m else None
        return raw, zh

    year_pillar,  year_pillar_zh  = parse_pillar("Year")
    month_pillar, month_pillar_zh = parse_pillar("Month")
    day_pillar,   day_pillar_zh   = parse_pillar("Day")

    # ── Daily auspicious / inauspicious — parse each MuiGrid item separately ──
    # FIX: target individual items instead of combined box2 string
    box2 = soup.find("div", class_=re.compile("box2"))
    auspicious_acts = inauspicious_acts = clash_zodiac = evil_direction = None
    good_shi_chen = None

    if box2:
        for item in box2.find_all("div", class_=re.compile("MuiGrid-item")):
            raw = item.get_text(separator=" | ", strip=True)

            if raw.startswith("Auspicious |"):
                val = raw[len("Auspicious |"):].strip()
                # Remove filler phrase that means "nothing else to add"
                val = val.replace("Do nothing else", "").strip().strip(",|").strip()
                # Remove any Shi Chen names that may have crept in
                parts = [p.strip() for p in val.split(",")
                         if p.strip() and p.strip() not in SHI_CHEN_ORDER]
                auspicious_acts = ", ".join(parts)

            elif raw.startswith("Inauspicious |"):
                inauspicious_acts = raw[len("Inauspicious |"):].strip()

            elif raw.startswith("Clash |"):
                clash_zodiac = raw[len("Clash |"):].strip()

            elif raw.startswith("Evil |"):
                evil_direction = raw[len("Evil |"):].strip()

            elif raw.startswith("Good Time |"):
                good_shi_chen = raw[len("Good Time |"):].strip()

    # ── Hourly table: 12 Shi Chen slots ───────────────────────────────────────
    hourly = []
    seen   = set()

    time_grids = soup.find_all("div", class_=re.compile(r"timeGrid1"))

    for grid in time_grids:
        grid_txt = grid.get_text(separator=" | ", strip=True)

        sc_m = re.match(
            r"(Good)?\s*\|?\s*(Zi|Chou|Yin|Mao|Chen|Si|Wu|Wei|Shen|You|Xu|Hai)",
            grid_txt
        )
        if not sc_m:
            continue

        # Luck: slots starting with "Good |" are auspicious; all others are inauspicious
        luck    = "Good" if sc_m.group(1) == "Good" else "Bad"
        sc_name = sc_m.group(2)
        if sc_name in seen:
            continue
        seen.add(sc_name)

        times     = SHI_CHEN_TIMES.get(sc_name, ("??:??", "??:??"))
        time_gmt8 = f"{times[0]}-{times[1]}"

        # Per-hour fields — parse MuiGrid-container divs within this timeGrid1
        # These are cleanly separated: Auspicious|..., Inauspicious|..., Clash|..., Evil|...
        hour_ausp = hour_inausp = hour_clash = hour_evil = None

        for container in grid.find_all("div", class_=re.compile("MuiGrid-container")):
            ctxt = container.get_text(separator=" | ", strip=True)
            if ctxt.startswith("Auspicious |"):
                v = ctxt[len("Auspicious |"):].strip()
                if v.lower() not in ("none", "nothing", ""):
                    hour_ausp = v
            elif ctxt.startswith("Inauspicious |"):
                v = ctxt[len("Inauspicious |"):].strip()
                hour_inausp = "All activities inauspicious" if v == "Everything Sucks" else v
            elif ctxt.startswith("Clash |"):
                hour_clash = ctxt[len("Clash |"):].strip()
            elif ctxt.startswith("Evil |"):
                hour_evil = ctxt[len("Evil |"):].strip()

        hourly.append({
            "shi_chen"   : sc_name,
            "time_gmt8"  : time_gmt8,
            "luck"       : luck,
            "ausp_acts"  : hour_ausp,
            "inausp_acts": hour_inausp,
            "clash"      : hour_clash,
            "evil_dir"   : hour_evil,
        })

    order_map = {sc: i for i, sc in enumerate(SHI_CHEN_ORDER)}
    hourly.sort(key=lambda x: order_map.get(x["shi_chen"], 99))

    # Derive time slots from hourly luck — stored in DB so they survive round-trip
    ausp_times   = [h["time_gmt8"] for h in hourly if h["luck"] == "Good"]
    inausp_times = [h["time_gmt8"] for h in hourly if h["luck"] == "Bad"]

    return {
        "gregorian_date"    : target_date.strftime("%Y-%m-%d"),
        "day_of_week"       : day_of_week,
        "lunar_date"        : lunar_date,   # may be overridden by secondary
        "solar_term"        : solar_term,
        "year_pillar"       : year_pillar,
        "year_pillar_zh"    : year_pillar_zh,
        "month_pillar"      : month_pillar,
        "month_pillar_zh"   : month_pillar_zh,
        "day_pillar"        : day_pillar,
        "day_pillar_zh"     : day_pillar_zh,
        "clash_zodiac"      : clash_zodiac,
        "evil_direction"    : evil_direction,
        "auspicious_acts"   : auspicious_acts,
        "inauspicious_acts" : inauspicious_acts,
        "good_shi_chen"     : good_shi_chen,
        "auspicious_times"  : " | ".join(ausp_times),
        "inauspicious_times": " | ".join(inausp_times),
        "god_of_joy"        : None,   # filled by secondary
        "god_of_happiness"  : None,
        "god_of_wealth"     : None,
        "hourly_json"       : json.dumps(hourly, ensure_ascii=False),
        "scraped_at"        : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ── SECONDARY SCRAPER: chinesecalendaronline.com (Singapore version) ──────────

def fetch_secondary(target_date: date, session: requests.Session) -> dict | None:
    """
    Fetch from chinesecalendaronline.com (Singapore version).
    Returns dict with:
      - lunar_date   : authoritative Singapore lunar date
      - god_of_joy / god_of_happiness / god_of_wealth : auspicious directions
    Returns None if unavailable (rate-limited, network issue, etc.)
    """
    url = SECONDARY_URL.format(
        y=target_date.year,
        m=target_date.month,
        d=target_date.day
    )
    try:
        r = session.get(url, timeout=TIMEOUT_SEC)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")

        result = {}

        # Lunar date — Singapore standard, verified correct against physical 通书
        lunar_div = soup.find("div", class_="mt1")
        if lunar_div:
            txt = re.sub(r"\s+", " ", lunar_div.text).strip()
            txt = txt.replace("(Lunar Date)", "").strip()
            if txt:
                result["lunar_date"] = txt

        # Auspicious directions
        dirbox = soup.find("div", class_="px2 my1")
        if dirbox:
            txt = re.sub(r"\s+", " ", dirbox.text).strip()
            joy    = re.search(r"God of Joy:\s*([\w\s]+?)(?:The|$)", txt)
            happy  = re.search(r"God of Happiness:\s*([\w\s]+?)(?:The|$)", txt)
            wealth = re.search(r"God of Wealth:\s*([\w\s]+?)(?:The|$|\.)", txt)
            if joy:
                result["god_of_joy"]       = joy.group(1).strip()
            if happy:
                result["god_of_happiness"] = happy.group(1).strip()
            if wealth:
                result["god_of_wealth"]    = wealth.group(1).strip()

        return result if result else None

    except Exception:
        return None


# ── FETCH + COMBINE ────────────────────────────────────────────────────────────

def fetch_date(target_date: date, session: requests.Session,
               fetch_dirs: bool = True) -> dict | None:
    """
    Fetch full almanac for one date.
    Primary source: rich hourly data from chinese-calendar.net
    Secondary source: correct lunar date + directions from chinesecalendaronline.com
    """
    url = PRIMARY_URL.format(date=target_date.strftime("%Y-%m-%d"))

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, timeout=TIMEOUT_SEC)
            r.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                print(f"  [ERROR] {target_date}: {e}")
                return None
            time.sleep(3)

    soup = BeautifulSoup(r.text, "html.parser")
    data = parse_primary(soup, target_date)
    if not data:
        return None

    if fetch_dirs:
        secondary = fetch_secondary(target_date, session)
        if secondary:
            # Override lunar date with Singapore-standard version
            if secondary.get("lunar_date"):
                data["lunar_date"] = secondary["lunar_date"]
            # Add directions
            for key in ("god_of_joy", "god_of_happiness", "god_of_wealth"):
                if secondary.get(key):
                    data[key] = secondary[key]
        time.sleep(0.5)

    return data


# ── DATABASE ───────────────────────────────────────────────────────────────────

def insert_record(conn: sqlite3.Connection, data: dict):
    conn.execute("""
        INSERT OR REPLACE INTO almanac (
            gregorian_date, day_of_week, lunar_date, solar_term,
            year_pillar, year_pillar_zh, month_pillar, month_pillar_zh,
            day_pillar, day_pillar_zh,
            clash_zodiac, evil_direction,
            auspicious_acts, inauspicious_acts, good_shi_chen,
            auspicious_times, inauspicious_times,
            god_of_joy, god_of_happiness, god_of_wealth,
            hourly_json, scraped_at
        ) VALUES (
            :gregorian_date, :day_of_week, :lunar_date, :solar_term,
            :year_pillar, :year_pillar_zh, :month_pillar, :month_pillar_zh,
            :day_pillar, :day_pillar_zh,
            :clash_zodiac, :evil_direction,
            :auspicious_acts, :inauspicious_acts, :good_shi_chen,
            :auspicious_times, :inauspicious_times,
            :god_of_joy, :god_of_happiness, :god_of_wealth,
            :hourly_json, :scraped_at
        )
    """, data)
    conn.commit()


def get_from_db(conn: sqlite3.Connection, target_date: date) -> dict | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM almanac WHERE gregorian_date = ?",
        (target_date.strftime("%Y-%m-%d"),)
    ).fetchone()
    conn.row_factory = None
    return dict(row) if row else None


# ── TIMEZONE CONVERSION ────────────────────────────────────────────────────────

def resolve_tz(tz_input: str) -> str:
    key = tz_input.lower().replace(" ", "_")
    return TIMEZONE_ALIASES.get(key, tz_input)


def convert_time_slot(time_gmt8: str, tz_name: str, ref_date: date) -> str:
    """Convert 'HH:MM-HH:MM' from GMT+8 to target timezone."""
    if not HAS_PYTZ:
        return f"{time_gmt8} (GMT+8)"
    try:
        gmt8_tz   = pytz.timezone("Asia/Singapore")
        target_tz = pytz.timezone(tz_name)
        m = re.match(r"(\d{2}):(\d{2})-(\d{2}):(\d{2})", time_gmt8)
        if not m:
            return time_gmt8
        sh, sm, eh, em = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        end_date   = ref_date if eh > sh else ref_date + timedelta(days=1)
        s_gmt8 = gmt8_tz.localize(datetime(ref_date.year, ref_date.month, ref_date.day, sh, sm))
        e_gmt8 = gmt8_tz.localize(datetime(end_date.year, end_date.month, end_date.day, eh, em))
        s_loc  = s_gmt8.astimezone(target_tz)
        e_loc  = e_gmt8.astimezone(target_tz)
        s_str  = s_loc.strftime("%H:%M")
        e_str  = e_loc.strftime("%H:%M")
        if s_loc.date() != ref_date:
            s_str += f"({s_loc.strftime('%d%b')})"
        if e_loc.date() != ref_date:
            e_str += f"({e_loc.strftime('%d%b')})"
        return f"{s_str}-{e_str}"
    except Exception:
        return f"{time_gmt8}(err)"


def enrich_with_tz(data: dict, tz_name: str) -> dict:
    result = dict(data)
    ref    = date.fromisoformat(data["gregorian_date"])

    # FIX: derive times from hourly_json if auspicious_times field is empty
    ausp_raw   = [t for t in (data.get("auspicious_times")   or "").split(" | ") if t]
    inausp_raw = [t for t in (data.get("inauspicious_times") or "").split(" | ") if t]

    if not ausp_raw and data.get("hourly_json"):
        hourly     = json.loads(data["hourly_json"])
        ausp_raw   = [h["time_gmt8"] for h in hourly if h.get("luck") == "Good"]
        inausp_raw = [h["time_gmt8"] for h in hourly if h.get("luck") == "Bad"]

    result["auspicious_times_local"]   = [convert_time_slot(t, tz_name, ref) for t in ausp_raw]
    result["inauspicious_times_local"] = [convert_time_slot(t, tz_name, ref) for t in inausp_raw]
    result["auspicious_times_gmt8"]    = ausp_raw
    result["inauspicious_times_gmt8"]  = inausp_raw
    result["timezone_used"]            = tz_name

    if data.get("hourly_json"):
        hourly = json.loads(data["hourly_json"])
        for slot in hourly:
            slot["time_local"] = convert_time_slot(slot["time_gmt8"], tz_name, ref)
        result["hourly_local"] = hourly

    return result


# ── PRETTY PRINT ───────────────────────────────────────────────────────────────

def print_almanac(data: dict, timezone: str | None = None):
    tz_name = None
    if timezone:
        tz_name = resolve_tz(timezone)
        data    = enrich_with_tz(data, tz_name)

    # Derive times if not yet enriched
    ausp_gmt8   = data.get("auspicious_times_gmt8")
    inausp_gmt8 = data.get("inauspicious_times_gmt8")

    if ausp_gmt8 is None:
        ausp_gmt8   = [t for t in (data.get("auspicious_times")   or "").split(" | ") if t]
        inausp_gmt8 = [t for t in (data.get("inauspicious_times") or "").split(" | ") if t]
        if not ausp_gmt8 and data.get("hourly_json"):
            hourly      = json.loads(data["hourly_json"])
            ausp_gmt8   = [h["time_gmt8"] for h in hourly if h.get("luck") == "Good"]
            inausp_gmt8 = [h["time_gmt8"] for h in hourly if h.get("luck") == "Bad"]

    ausp_local   = data.get("auspicious_times_local",   ausp_gmt8)
    inausp_local = data.get("inauspicious_times_local", inausp_gmt8)

    print()
    print("═" * 68)
    print(f"  🗓️  {data['gregorian_date']}  ({data.get('day_of_week','')})")
    print("═" * 68)
    print(f"  农历  Lunar   : {data.get('lunar_date','')}  ← Singapore standard (通书)")
    if data.get("solar_term"):
        print(f"  节气  Solar   : {data['solar_term']}")
    print()

    yp = data.get("year_pillar",  "")
    mp = data.get("month_pillar", "")
    dp = data.get("day_pillar",   "")
    yz = f"  ({data['year_pillar_zh']})"  if data.get("year_pillar_zh")  else ""
    mz = f"  ({data['month_pillar_zh']})" if data.get("month_pillar_zh") else ""
    dz = f"  ({data['day_pillar_zh']})"   if data.get("day_pillar_zh")   else ""
    print(f"  年  Year  pillar : {yp}{yz}")
    print(f"  月  Month pillar : {mp}{mz}")
    print(f"  日  Day   pillar : {dp}{dz}")
    print()

    print(f"  ⚡ 冲  Clash  : {data.get('clash_zodiac','')}  "
          f"(year of {data.get('clash_zodiac','')} = less favourable today)")
    print(f"  🚫 煞  Evil   : {data.get('evil_direction','')}  "
          f"(avoid activities facing this direction)")
    print()

    if any(data.get(k) for k in ["god_of_joy", "god_of_happiness", "god_of_wealth"]):
        print("  🧭 AUSPICIOUS DIRECTIONS")
        print(f"     喜神  God of Joy       : {data.get('god_of_joy','—')}")
        print(f"     贵神  God of Happiness : {data.get('god_of_happiness','—')}")
        print(f"     财神  God of Wealth    : {data.get('god_of_wealth','—')}")
    else:
        print("  🧭 Directions: not available (run from MacBook with secondary source)")
    print()

    print("  ✅ 宜  AUSPICIOUS today:")
    for act in (data.get("auspicious_acts") or "").split(","):
        act = act.strip()
        if act:
            print(f"     • {act}")
    print()

    print("  ❌ 忌  INAUSPICIOUS today:")
    for act in (data.get("inauspicious_acts") or "").split(","):
        act = act.strip()
        if act:
            print(f"     • {act}")
    print()

    if data.get("good_shi_chen"):
        print(f"  ⏰ Good Shi Chen: {data['good_shi_chen']}")
        print()

    if tz_name:
        print(f"  ⏰ AUSPICIOUS HOURS  (GMT+8  →  {tz_name})")
        for g, l in zip(ausp_gmt8, ausp_local):
            print(f"     ✅  {g:<14}  →  {l}")
        print()
        print(f"  ⏰ INAUSPICIOUS HOURS  (GMT+8  →  {tz_name})")
        for g, l in zip(inausp_gmt8, inausp_local):
            print(f"     ❌  {g:<14}  →  {l}")
    else:
        print("  ⏰ AUSPICIOUS HOURS (GMT+8 / Singapore time)")
        for t in ausp_gmt8:
            print(f"     ✅  {t}")
        print()
        print("  ⏰ INAUSPICIOUS HOURS (GMT+8 / Singapore time)")
        for t in inausp_gmt8:
            print(f"     ❌  {t}")

    print()
    print("  📋 12 SHI CHEN HOURLY BREAKDOWN")
    hourly = data.get("hourly_local") or (
        json.loads(data["hourly_json"]) if data.get("hourly_json") else []
    )
    for slot in hourly:
        icon     = "✅" if slot.get("luck") == "Good" else "❌"
        time_str = slot.get("time_local", slot.get("time_gmt8", ""))
        sc       = slot.get("shi_chen", "")
        print(f"\n  {icon} {sc:<5} {time_str}")
        if slot.get("ausp_acts"):
            print(f"     宜: {slot['ausp_acts']}")
        if slot.get("inausp_acts"):
            print(f"     忌: {slot['inausp_acts']}")
        if slot.get("clash"):
            print(f"     冲: {slot['clash']}  |  煞: {slot.get('evil_dir','')}")

    print()
    print("  Source: chinese-calendar.net (hourly) + chinesecalendaronline.com (lunar/directions)")
    print("═" * 68)
    print()


# ── SCRAPE RANGE ───────────────────────────────────────────────────────────────

def scrape_range(start: date, end: date, conn: sqlite3.Connection,
                 session: requests.Session, force: bool = False,
                 fetch_dirs: bool = True):
    total   = (end - start).days + 1
    saved   = skipped = 0
    d       = start

    print(f"\n  Scraping {total} days  ({start} → {end})")
    print(f"  DB      : {DB_PATH}")
    print(f"  Dirs    : {'yes — includes lunar date + God of Joy/Wealth/Happiness' if fetch_dirs else 'skipped (--no-dirs)'}")
    print()

    while d <= end:
        if not force and get_from_db(conn, d):
            skipped += 1
            d += timedelta(days=1)
            continue

        data = fetch_date(d, session, fetch_dirs=fetch_dirs)
        if data:
            insert_record(conn, data)
            saved += 1
            dp = data.get("day_pillar_zh") or data.get("day_pillar", "?")
            print(f"  ✅ {d}  {data.get('day_of_week',''):>9}  {dp:<8}  "
                  f"clash={data.get('clash_zodiac','?'):8}  "
                  f"lunar={data.get('lunar_date','?')}")
        else:
            print(f"  ⚠️  {d}  — not available")

        d += timedelta(days=1)
        time.sleep(DELAY_SEC)

    total_in_db = conn.execute("SELECT COUNT(*) FROM almanac").fetchone()[0]
    print(f"\n  Done. Saved: {saved}  Skipped (cached): {skipped}")
    print(f"  Total in DB: {total_in_db:,} days")


# ── PUBLIC API ─────────────────────────────────────────────────────────────────

def get_almanac(target_date_str: str | None = None,
                timezone: str | None = None) -> dict | None:
    """
    Get almanac for a date (default: today). Scrapes if not cached.
    Args:
        target_date_str: 'YYYY-MM-DD', or None for today
        timezone: 'sg', 'germany', 'Europe/Berlin', etc.
    Returns:
        dict with all fields. If timezone given, includes *_local converted times.
    """
    d = (datetime.strptime(target_date_str, "%Y-%m-%d").date()
         if target_date_str else date.today())

    conn    = sqlite3.connect(DB_PATH)
    init_db(conn)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    data = get_from_db(conn, d)
    if not data:
        data = fetch_date(d, session, fetch_dirs=True)
        if data:
            insert_record(conn, data)
    conn.close()

    if data and timezone:
        data = enrich_with_tz(data, resolve_tz(timezone))
    return data


def get_toto_draw_day_almanac(timezone: str = "sg") -> dict | None:
    """
    Get almanac for today if it's a TOTO draw day (Monday/Thursday),
    otherwise for the next draw day.
    """
    today   = date.today()
    weekday = today.weekday()           # 0=Mon, 3=Thu
    days_to_mon = (0 - weekday) % 7
    days_to_thu = (3 - weekday) % 7
    next_draw   = today + timedelta(days=min(days_to_mon, days_to_thu))
    return get_almanac(next_draw.strftime("%Y-%m-%d"), timezone=timezone)


# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Scrape Chinese Almanac (黄历) to SQLite DB"
    )
    parser.add_argument("--date",    help="Single date YYYY-MM-DD (default: today)")
    parser.add_argument("--from",    dest="date_from", help="Start date YYYY-MM-DD")
    parser.add_argument("--to",      dest="date_to",   help="End date YYYY-MM-DD")
    parser.add_argument("--print",   action="store_true", help="Print almanac after scraping")
    parser.add_argument("--timezone",help="Timezone (e.g. sg, germany, Europe/Berlin)")
    parser.add_argument("--force",   action="store_true", help="Re-scrape existing dates")
    parser.add_argument("--no-dirs", action="store_true",
                        help="Skip secondary source — faster, no directions or corrected lunar date")
    args = parser.parse_args()

    today = date.today()

    if args.date_from and args.date_to:
        start  = datetime.strptime(args.date_from, "%Y-%m-%d").date()
        end    = datetime.strptime(args.date_to,   "%Y-%m-%d").date()
        single = False
    elif args.date:
        start = end = datetime.strptime(args.date, "%Y-%m-%d").date()
        single = True
    else:
        start = end = today
        single = True

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    session = requests.Session()
    session.headers.update({
        "User-Agent"     : "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept"         : "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })

    if not HAS_PYTZ and args.timezone:
        print("⚠️  pytz not installed — run: pip install pytz")

    if args.print and single:
        data = get_from_db(conn, start)
        if not data or args.force:
            print(f"  Fetching {start}...")
            data = fetch_date(start, session, fetch_dirs=not args.no_dirs)
            if data:
                insert_record(conn, data)
        if data:
            print_almanac(data, timezone=args.timezone)
        else:
            print(f"  Could not retrieve almanac for {start}")
    else:
        scrape_range(start, end, conn, session,
                     force=args.force, fetch_dirs=not args.no_dirs)
        if single and args.print:
            data = get_from_db(conn, start)
            if data:
                print_almanac(data, timezone=args.timezone)

    total = conn.execute("SELECT COUNT(*) FROM almanac").fetchone()[0]
    conn.close()
    print(f"  DB: {DB_PATH}  ({total:,} days stored)")
    if not HAS_PYTZ:
        print("  💡 pip install pytz  for timezone conversion")


if __name__ == "__main__":
    main()
