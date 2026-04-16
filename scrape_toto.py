"""
SG Pools TOTO Results Scraper — v2
=====================================
Fetches ALL available TOTO draw results from Singapore Pools and saves to SQLite.

New in v2 (vs original):
  - g1_locations  : pipe-separated list of Group 1 winning outlet names + addresses
  - g2_locations  : pipe-separated list of Group 2 winning outlet names + addresses
  - g1_snowball   : snowball amount (TEXT) when Group 1 has no winner
  - prize_expiry  : prize claim deadline date (TEXT)
  - Corrupt-aware re-scraping (get_existing_draws returns complete + corrupt sets)

Data availability (confirmed by live testing, Apr 2026):
  - Draws 1001–1193 : Numbers present but date field corrupted ("01 Jan 0001")
  - Draws 1194–4173 : Full valid data (Jul 1997 → Apr 2026)
  - Draws 1–1000    : Server returns latest draw (skipped automatically)

Schema: toto_results.db → table `draws`
  draw_number   INTEGER PRIMARY KEY
  draw_date     TEXT
  date_reliable INTEGER  (1 = real date, 0 = corrupted "01 Jan 0001")
  num1..num6    INTEGER  (winning numbers, sorted ascending)
  additional    INTEGER  (additional number)
  jackpot_prize TEXT     (Group 1 prize pool)
  g1_amount     TEXT     (prize per G1 winner)
  g1_winners    INTEGER  (number of G1 winning shares)
  g1_locations  TEXT     (pipe-separated outlet names/addresses for G1 winners)
  g1_snowball   TEXT     (snowball amount if no G1 winner, else NULL)
  g2_amount     TEXT
  g2_winners    INTEGER
  g2_locations  TEXT     (pipe-separated outlet names/addresses for G2 winners)
  g3_amount..g7_amount   TEXT
  g3_winners..g7_winners INTEGER
  prize_expiry  TEXT     (prize claim deadline, e.g. "Sat, 10 Oct 2026")
  scraped_at    TEXT
"""

from __future__ import annotations
import requests
import base64
import sqlite3
import time
import re
import os
from datetime import datetime
from bs4 import BeautifulSoup

os.makedirs("data", exist_ok=True)

# ── Configuration ─────────────────────────────────────────────────────────────
DB_PATH       = "data/toto_results.db"
DRAW_START    = 1001
DRAW_END      = None          # None = auto-detect latest
DELAY_SEC     = 1.5
TIMEOUT_SEC   = 20
MAX_RETRIES   = 3
BASE_URL      = "https://www.singaporepools.com.sg/en/product/sr/Pages/toto_results.aspx"
DRAW_LIST_URL = "https://www.singaporepools.com.sg/DataFileArchive/Lottery/Output/toto_result_draw_list_en.html"
CORRUPT_DATE  = "Mon, 01 Jan 0001"
# ─────────────────────────────────────────────────────────────────────────────

# ── TEMPORARY: re-scrape only G1-winner draws to populate locations ──────────
# After running once, revert FORCE_RESCRAPE_G1 back to False
FORCE_RESCRAPE_G1 = False

def encode_draw(n: int) -> str:
    raw = f"DrawNumber={n}".encode()
    return base64.b64encode(raw).decode().rstrip("=")


def get_latest_draw_number() -> int:
    print("  Fetching latest draw number from SG Pools …")
    r = requests.get(DRAW_LIST_URL, timeout=TIMEOUT_SEC)
    r.raise_for_status()
    matches = re.findall(r"value='(\d+)'", r.text)
    if not matches:
        raise RuntimeError("Could not find any draw numbers in draw list page.")
    latest = max(int(m) for m in matches)
    print(f"  Latest draw found: {latest}")
    return latest


def init_db(conn: sqlite3.Connection):
    """Create draws table with v2 schema (locations, snowball, expiry)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS draws (
            draw_number   INTEGER PRIMARY KEY,
            draw_date     TEXT,
            date_reliable INTEGER DEFAULT 1,
            num1          INTEGER,
            num2          INTEGER,
            num3          INTEGER,
            num4          INTEGER,
            num5          INTEGER,
            num6          INTEGER,
            additional    INTEGER,
            jackpot_prize TEXT,
            g1_amount     TEXT,
            g1_winners    INTEGER,
            g1_locations  TEXT,
            g1_snowball   TEXT,
            g2_amount     TEXT,
            g2_winners    INTEGER,
            g2_locations  TEXT,
            g3_amount     TEXT,
            g3_winners    INTEGER,
            g4_amount     TEXT,
            g4_winners    INTEGER,
            g5_amount     TEXT,
            g5_winners    INTEGER,
            g6_amount     TEXT,
            g6_winners    INTEGER,
            g7_amount     TEXT,
            g7_winners    INTEGER,
            prize_expiry  TEXT,
            scraped_at    TEXT
        )
    """)

    # ── Migrate existing DB: add new columns if they don't exist ─────────────
    existing_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(draws)").fetchall()
    }
    new_cols = {
        "g1_locations" : "TEXT",
        "g1_snowball"  : "TEXT",
        "g2_locations" : "TEXT",
        "prize_expiry" : "TEXT",
    }
    for col, dtype in new_cols.items():
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE draws ADD COLUMN {col} {dtype}")
            print(f"  ✚ Added new column: {col}")

    conn.commit()


def get_existing_draws(conn: sqlite3.Connection) -> tuple[set, set]:
    """
    Returns:
      complete : draw numbers fully valid — skip
      corrupt  : draw numbers with bad/missing data — re-scrape
    Corrupt = date_reliable=0 OR any num1-num6 is NULL
    """
    cur = conn.execute("""
        SELECT draw_number, date_reliable,
               num1, num2, num3, num4, num5, num6
        FROM draws
    """)
    complete, corrupt = set(), set()
    for row in cur.fetchall():
        draw_num      = row[0]
        date_reliable = row[1]
        numbers       = row[2:8]
        if date_reliable == 0 or any(n is None for n in numbers):
            corrupt.add(draw_num)
        else:
            complete.add(draw_num)
            
    # ── Re-scrape G1 winner draws missing location data ──────────────────────
    if FORCE_RESCRAPE_G1:
        g1_draws = conn.execute("""
            SELECT draw_number FROM draws
            WHERE g1_winners > 0
            AND (g1_locations IS NULL 
             OR g1_locations = ''
             OR g1_locations = '$10')   -- ← add this line
            AND date_reliable = 1
        """).fetchall()
        for row in g1_draws:
            complete.discard(row[0])   # remove from complete if it was there
            corrupt.add(row[0])        # force re-scrape
    
    return complete, corrupt

def parse_prize_row(row) -> tuple:
    cols = row.find_all("td")
    if len(cols) < 3:
        return None, None
    amount  = cols[1].text.strip().replace("$", "").replace(",", "")
    winners = cols[2].text.strip().replace(",", "")
    try:
        return "$" + "{:,}".format(int(amount)), int(winners)
    except ValueError:
        return cols[1].text.strip(), None


def extract_locations(soup: BeautifulSoup, group: int) -> str | None:
    """
    Find 'Group N winning tickets sold at:' paragraph and extract
    all outlet entries from the following <ul> tag.
    Returns pipe-separated string of outlets, or None.
    """
    target_text = f"Group {group} winning tickets sold at"
    for p in soup.find_all("p"):
        if target_text.lower() in p.text.lower():
            ul = p.find_next_sibling("ul")
            if not ul:
                return None
            outlets = []
            for li in ul.find_all("li"):
                txt = li.text.strip()
                # Clean up excessive whitespace
                txt = re.sub(r'\s+', ' ', txt).strip()
                if txt:
                    outlets.append(txt)
            # Also check direct text in ul if no li tags
            if not outlets:
                txt = re.sub(r'\s+', ' ', ul.text).strip()
                if txt:
                    outlets.append(txt)
            return " | ".join(outlets) if outlets else None
    return None


def extract_snowball(soup: BeautifulSoup) -> str | None:
    """
    If Group 1 has no winner, extract the snowball amount from:
    'Group 1 has no winner, and the prize amount of $X will be snowballed...'
    Returns the dollar amount string, or None if G1 had a winner.
    """
    for p in soup.find_all("p"):
        txt = p.text.strip()
        if "snowballed" in txt.lower() and "group 1" in txt.lower():
            # Extract dollar amount
            match = re.search(r'\$([\d,]+)', txt)
            if match:
                return "$" + match.group(1)
            return txt  # fallback: return full text
    return None


def extract_prize_expiry(soup: BeautifulSoup) -> str | None:
    """
    Extract prize claim deadline from:
    'Prizes not claimed by [DATE] will be channelled...'
    """
    for p in soup.find_all("p"):
        txt = p.text.strip()
        if "not claimed by" in txt.lower():
            match = re.search(
                r'not claimed by\s+([A-Za-z]+,\s+\d+\s+[A-Za-z]+\s+\d{4})',
                txt, re.IGNORECASE
            )
            if match:
                return match.group(1).strip()
    return None


def fetch_draw(draw_num: int, session: requests.Session) -> dict | None:
    qs  = encode_draw(draw_num)
    url = f"{BASE_URL}?sppl={qs}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, timeout=TIMEOUT_SEC)
            r.raise_for_status()
            break
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                print(f"\n    [ERROR] Draw {draw_num} failed after {MAX_RETRIES} retries: {e}")
                return None
            time.sleep(3)

    soup = BeautifulSoup(r.text, "html.parser")

    # ── Detect redirect to different draw ────────────────────────────────────
    draw_num_el = soup.find(class_="drawNumber")
    if not draw_num_el:
        return None
    m = re.search(r"\d+", draw_num_el.text)
    if not m or int(m.group()) != draw_num:
        return None

    # ── Date ─────────────────────────────────────────────────────────────────
    draw_date_el  = soup.find(class_="drawDate")
    draw_date     = draw_date_el.text.strip() if draw_date_el else "Unknown"
    date_reliable = 0 if (not draw_date_el or "0001" in draw_date) else 1

    # ── Winning numbers ───────────────────────────────────────────────────────
    nums = []
    for i in range(1, 7):
        el = soup.find(class_=f"win{i}")
        nums.append(int(el.text.strip()) if el else None)

    additional_el = soup.find(class_="additional")
    additional    = int(additional_el.text.strip()) if additional_el else None

    # ── Jackpot prize ─────────────────────────────────────────────────────────
    jackpot_el    = soup.find(class_="jackpotPrize")
    jackpot_prize = jackpot_el.text.strip() if jackpot_el else None

    # ── Prize shares ─────────────────────────────────────────────────────────
    group_data = {i: (None, None) for i in range(1, 8)}
    shares_tbl = soup.find(class_="tableWinningShares")
    if shares_tbl:
        data_rows = [
            row for row in shares_tbl.find_all("tr")
            if len(row.find_all("td")) == 3
        ]
        for idx, row in enumerate(data_rows, start=1):
            if idx > 7:
                break
            group_data[idx] = parse_prize_row(row)

    # ── NEW: Locations ────────────────────────────────────────────────────────
    g1_locations = extract_locations(soup, 1)
    g2_locations = extract_locations(soup, 2)

    # ── NEW: Snowball ─────────────────────────────────────────────────────────
    g1_snowball  = extract_snowball(soup)

    # ── NEW: Prize expiry ─────────────────────────────────────────────────────
    prize_expiry = extract_prize_expiry(soup)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "draw_number"  : draw_num,
        "draw_date"    : draw_date,
        "date_reliable": date_reliable,
        "num1"         : nums[0],
        "num2"         : nums[1],
        "num3"         : nums[2],
        "num4"         : nums[3],
        "num5"         : nums[4],
        "num6"         : nums[5],
        "additional"   : additional,
        "jackpot_prize": jackpot_prize,
        "g1_amount"    : group_data[1][0],
        "g1_winners"   : group_data[1][1],
        "g1_locations" : g1_locations,
        "g1_snowball"  : g1_snowball,
        "g2_amount"    : group_data[2][0],
        "g2_winners"   : group_data[2][1],
        "g2_locations" : g2_locations,
        "g3_amount"    : group_data[3][0],
        "g3_winners"   : group_data[3][1],
        "g4_amount"    : group_data[4][0],
        "g4_winners"   : group_data[4][1],
        "g5_amount"    : group_data[5][0],
        "g5_winners"   : group_data[5][1],
        "g6_amount"    : group_data[6][0],
        "g6_winners"   : group_data[6][1],
        "g7_amount"    : group_data[7][0],
        "g7_winners"   : group_data[7][1],
        "prize_expiry" : prize_expiry,
        "scraped_at"   : now,
    }


def insert_draw(conn: sqlite3.Connection, data: dict):
    conn.execute("""
        INSERT OR REPLACE INTO draws
        (draw_number, draw_date, date_reliable,
         num1, num2, num3, num4, num5, num6,
         additional, jackpot_prize,
         g1_amount, g1_winners, g1_locations, g1_snowball,
         g2_amount, g2_winners, g2_locations,
         g3_amount, g3_winners,
         g4_amount, g4_winners,
         g5_amount, g5_winners,
         g6_amount, g6_winners,
         g7_amount, g7_winners,
         prize_expiry, scraped_at)
        VALUES
        (:draw_number, :draw_date, :date_reliable,
         :num1, :num2, :num3, :num4, :num5, :num6,
         :additional, :jackpot_prize,
         :g1_amount, :g1_winners, :g1_locations, :g1_snowball,
         :g2_amount, :g2_winners, :g2_locations,
         :g3_amount, :g3_winners,
         :g4_amount, :g4_winners,
         :g5_amount, :g5_winners,
         :g6_amount, :g6_winners,
         :g7_amount, :g7_winners,
         :prize_expiry, :scraped_at)
    """, data)
    conn.commit()


def progress_bar(current: int, total: int, width: int = 50) -> str:
    filled = int(width * current / total) if total > 0 else 0
    bar    = "█" * filled + "░" * (width - filled)
    pct    = 100 * current / total if total > 0 else 0
    return f"[{bar}] {pct:5.1f}% ({current}/{total})"


def main():
    print("=" * 65)
    print("  SG POOLS — TOTO RESULTS SCRAPER v2")
    print("  New: G1/G2 outlet locations, snowball, prize expiry")
    print("=" * 65)

    draw_end       = DRAW_END or get_latest_draw_number()
    draws_to_fetch = list(range(DRAW_START, draw_end + 1))
    total          = len(draws_to_fetch)

    print(f"\n  Draw range : {DRAW_START} → {draw_end}  ({total:,} draws)")
    print(f"  Output DB  : {DB_PATH}")
    print(f"  Delay      : {DELAY_SEC}s between requests\n")

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    complete, corrupt = get_existing_draws(conn)
    print(f"  Complete draws in DB : {len(complete):,} (will skip)")
    print(f"  Corrupt rows         : {len(corrupt):,} (will re-scrape)")
    print(f"  New draws to fetch   : {total - len(complete) - len(corrupt):,}\n")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    })

    saved         = 0
    skipped       = 0
    missing       = 0
    corrupt_saved = 0
    processed     = 0
    start_time    = time.time()

    for draw_num in draws_to_fetch:
        processed += 1

        if draw_num in complete:
            skipped += 1
            continue
        if draw_num in corrupt:
            print(f"\n  ♻️  Re-scraping corrupt draw #{draw_num}...")

        if processed % 10 == 0 or processed == 1:
            elapsed  = time.time() - start_time
            rate     = max((processed - skipped) / elapsed, 0.001)
            eta_secs = (total - processed) / rate
            eta_str  = f"{int(eta_secs//60)}m {int(eta_secs%60)}s"
            bar      = progress_bar(processed, total)
            print(f"\r  {bar}  saved:{saved:,}  missing:{missing:,}  ETA:{eta_str}  ",
                  end="", flush=True)

        data = fetch_draw(draw_num, session)

        if data is None:
            missing += 1
        else:
            if draw_num in corrupt:
                corrupt_saved += 1
            insert_draw(conn, data)
            saved += 1

        time.sleep(DELAY_SEC)

    conn.close()
    elapsed = time.time() - start_time
    print(f"\n\n{'=' * 65}")
    print(f"  TOTO SCRAPE v2 COMPLETE")
    print(f"{'=' * 65}")
    print(f"  Draws saved        : {saved:,}")
    print(f"  Corrupt re-scraped : {corrupt_saved:,}")
    print(f"  Draws skipped      : {skipped:,}  (already complete)")
    print(f"  Draws not found    : {missing:,}  (not on server)")
    print(f"  Time taken         : {int(elapsed//60)}m {int(elapsed%60)}s")
    print(f"  Output file        : {DB_PATH}")
    print(f"{'=' * 65}\n")


if __name__ == "__main__":
    main()
