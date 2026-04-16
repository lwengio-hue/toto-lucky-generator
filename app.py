"""
🎱 TOTO Lucky Generator
Singapore Pools TOTO — AI + Mathematics + Numerology + Feng Shui
"""

import streamlit as st
import sqlite3
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from collections import Counter
from itertools import combinations as combo_iter, permutations
from datetime import datetime, date, timedelta
import tempfile, os, re, json, urllib.request, warnings
warnings.filterwarnings('ignore')

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="🎱 TOTO Lucky Generator",
    page_icon="🎱",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── GitHub DB URLs ─────────────────────────────────────────────────────────────
GITHUB_TOTO_DB_URL    = (
    "https://github.com/lwengio-hue/toto-lucky-generator"
    "/raw/main/data/toto_results.db"
)
GITHUB_ALMANAC_DB_URL = (
    "https://github.com/lwengio-hue/toto-lucky-generator"
    "/raw/main/data/almanac.db"
)

NUM_COLS  = ['num1','num2','num3','num4','num5','num6']
COMBO_SIZE = 7

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700&family=Crimson+Pro:ital,wght@0,400;0,600;1,400&display=swap');

html, body, [class*="css"] { font-family: 'Crimson Pro', Georgia, serif; }

.main-title {
    font-family: 'Cinzel', serif;
    font-size: 2.4rem;
    font-weight: 700;
    text-align: center;
    background: linear-gradient(135deg, #b8860b, #ffd700, #b8860b);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: 3px;
    margin-bottom: 0.2rem;
}
.sub-title {
    text-align: center;
    color: #aaa;
    font-size: 0.95rem;
    letter-spacing: 1px;
    margin-bottom: 2rem;
}
.ball {
    display: inline-flex; align-items: center; justify-content: center;
    width: 52px; height: 52px; border-radius: 50%;
    font-family: 'Cinzel', serif; font-size: 1rem; font-weight: 700;
    color: white; margin: 3px;
    box-shadow: 0 4px 14px rgba(0,0,0,0.35);
    border: 2px solid rgba(255,255,255,0.2);
}
.ball-red    { background: radial-gradient(circle at 35% 35%, #e74c3c, #7b241c); }
.ball-blue   { background: radial-gradient(circle at 35% 35%, #2980b9, #154360); }
.ball-gold   { background: radial-gradient(circle at 35% 35%, #f39c12, #7d6608); color: #1a1a1a; }
.ball-green  { background: radial-gradient(circle at 35% 35%, #27ae60, #1a5e36); }
.ball-purple { background: radial-gradient(circle at 35% 35%, #8e44ad, #4a235a); }
.ball-teal   { background: radial-gradient(circle at 35% 35%, #16a085, #0b5345); }

.pick-card {
    background: linear-gradient(145deg, #1a1a2e, #16213e);
    border: 1px solid rgba(255,215,0,0.15);
    border-radius: 14px; padding: 18px 22px; margin-bottom: 14px;
    box-shadow: 0 6px 24px rgba(0,0,0,0.3);
}
.stat-box {
    background: rgba(255,255,255,0.04); border-radius: 10px;
    padding: 12px 16px; border: 1px solid rgba(255,255,255,0.07);
    text-align: center;
}
.almanac-box {
    background: linear-gradient(135deg, #1a1a0e, #0e1a0e);
    border: 1px solid rgba(255,215,0,0.25);
    border-radius: 14px; padding: 20px 24px; margin: 12px 0;
}
.action-row {
    display: flex; align-items: center; gap: 12px;
    padding: 8px 0; border-bottom: 1px solid rgba(255,255,255,0.06);
    font-size: 1rem;
}
.tag { display: inline-block; padding: 2px 10px; border-radius: 20px;
       font-size: 0.75rem; font-weight: 600; margin-left: 8px; }
.tag-hot    { background: rgba(231,76,60,0.2);  color: #e74c3c; border: 1px solid rgba(231,76,60,0.4); }
.tag-cold   { background: rgba(41,128,185,0.2); color: #3498db; border: 1px solid rgba(41,128,185,0.4); }
.tag-lucky  { background: rgba(255,215,0,0.15); color: #ffd700; border: 1px solid rgba(255,215,0,0.3); }
.disclaimer {
    background: rgba(231,76,60,0.07); border-left: 3px solid #922b21;
    padding: 12px 16px; border-radius: 0 8px 8px 0;
    font-size: 0.85rem; color: #bbb; margin-top: 1rem;
}
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# DATA LOADING
# ══════════════════════════════════════════════════════════════════════════════

@st.cache_data(show_spinner=False)
def load_toto_db(db_bytes: bytes) -> pd.DataFrame:
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        f.write(db_bytes); tmp = f.name
    conn = sqlite3.connect(tmp)
    df   = pd.read_sql('SELECT * FROM draws ORDER BY draw_number ASC', conn)
    conn.close(); os.unlink(tmp)
    df['draw_date'] = pd.to_datetime(df['draw_date'], errors='coerce')
    for c in NUM_COLS:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df = df[df['date_reliable'] == 1].dropna(subset=NUM_COLS).reset_index(drop=True)
    for c in NUM_COLS:
        df[c] = df[c].astype(int)
    return df


@st.cache_data(show_spinner=False)
def load_almanac_db(db_bytes: bytes, target_date: str) -> dict | None:
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        f.write(db_bytes); tmp = f.name
    conn = sqlite3.connect(tmp)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM almanac WHERE gregorian_date = ?", (target_date,)
    ).fetchone()
    conn.close(); os.unlink(tmp)
    return dict(row) if row else None


def fetch_github_db(url: str) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return r.read()
    except Exception:
        return None


@st.cache_data(show_spinner="📥 Loading TOTO data from GitHub...")
def get_toto_bytes():
    return fetch_github_db(GITHUB_TOTO_DB_URL)


@st.cache_data(show_spinner="📥 Loading almanac from GitHub...")
def get_almanac_bytes():
    return fetch_github_db(GITHUB_ALMANAC_DB_URL)


# ══════════════════════════════════════════════════════════════════════════════
# CORE LOGIC
# ══════════════════════════════════════════════════════════════════════════════

def compute_freq(df):
    all_nums = pd.Series(df[NUM_COLS].values.flatten().astype(int))
    freq = all_nums.value_counts().sort_index().reindex(range(1, 50), fill_value=0)
    return freq


def parse_money(s):
    if not s or s == '-': return None
    cleaned = re.sub(r'[^\d.]', '', str(s))
    return float(cleaned) if cleaned else None


def gen_pure_random(size=7):
    return sorted(np.random.choice(range(1, 50), size=size, replace=False).tolist())


def derive_lucky_combo(lucky_nums, freq, size=7, n_combos=5):
    anchors = []
    for n, _ in lucky_nums:
        try:
            v = int(n)
            if 1 <= v <= 49:
                anchors.append(v)
        except: pass
    anchors    = list(set(anchors))[:size]
    n_fill     = size - len(anchors)
    used       = set(anchors)
    cold_pool  = [n for n in freq.sort_values().index.tolist() if n not in used]
    results, seen, attempts = [], set(), 0
    while len(results) < n_combos and attempts < 500:
        attempts += 1
        pool    = cold_pool[:min(30, len(cold_pool))]
        fillers = [int(x) for x in np.random.choice(pool, size=min(n_fill, len(pool)), replace=False)]
        combo   = sorted(anchors + fillers)
        key     = tuple(combo)
        if key not in seen and len(combo) == size:
            seen.add(key)
            results.append((combo, sum(freq.get(n, 0) for n in combo)))
    return sorted(results, key=lambda x: x[1])


MIRROR_TABLE = {"0":"5","1":"6","2":"7","3":"8","4":"9",
                "5":"0","6":"1","7":"7","8":"3","9":"4"}

def mirror_number(n):
    m = int("".join(MIRROR_TABLE.get(d, d) for d in str(n)))
    if m < 1:  m = 49 - m
    if m > 49: m = m - 49
    return max(1, min(49, m))

def mirror_formula(nums):
    result = []
    for n in nums:
        s1 = n + 6
        if s1 > 49: s1 -= 49
        result.append(mirror_number(s1))
    return result


def get_almanac_times(almanac_data):
    """Extract auspicious times from almanac dict, falling back to hourly_json."""
    ausp = [t for t in (almanac_data.get('auspicious_times') or '').split(' | ') if t]
    if not ausp and almanac_data.get('hourly_json'):
        hourly = json.loads(almanac_data['hourly_json'])
        ausp   = [h['time_gmt8'] for h in hourly if h.get('luck') == 'Good']
    return ausp


# ══════════════════════════════════════════════════════════════════════════════
# UI HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def render_balls(combo, style='red'):
    return ''.join(f'<span class="ball ball-{style}">{n}</span>' for n in combo)


def render_pick_card(title, emoji, combos, freq, top7_high, top7_low,
                     style='red', show_analysis=True):
    html = f'<div class="pick-card"><div style="font-size:1rem;font-weight:600;margin-bottom:12px">{emoji} {title}</div>'
    for combo in combos:
        html += render_balls(combo, style)
        if show_analysis:
            combo_sum  = sum(combo)
            above31    = sum(1 for n in combo if n > 31)
            hot_in     = [n for n in combo if n in top7_high]
            cold_in    = [n for n in combo if n in top7_low]
            html += f'<div style="font-size:0.8rem;color:#aaa;margin:6px 0 12px 4px">sum={combo_sum} · >31:{above31}/{COMBO_SIZE}'
            if hot_in:  html += f' · <span style="color:#e74c3c">hot:{hot_in}</span>'
            if cold_in: html += f' · <span style="color:#3498db">cold:{cold_in}</span>'
            html += '</div>'
        else:
            html += '<br><br>'
    html += '</div>'
    return html


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("### 📂 Databases")
    toto_upload   = st.file_uploader("Upload toto_results.db (optional)", type=['db','sqlite','sqlite3'])
    almanac_upload= st.file_uploader("Upload almanac.db (optional)",       type=['db','sqlite','sqlite3'])
    st.caption("Leave empty to auto-load from GitHub")

    st.markdown("---")
    st.markdown("### ⚙️ Settings")
    combo_size = st.selectbox("Entry type", [7, 6], index=0,
                              help="System 7 = $7, covers all 7-choose-6 combos | Ordinary = $1")
    top_n      = st.slider("Lucky combos to show", 1, 8, 5)
    your_zodiac= st.selectbox("Your Chinese zodiac",
        ["Rat","Ox","Tiger","Rabbit","Dragon","Snake",
         "Horse","Goat","Monkey","Rooster","Dog","Pig"],
        index=6, help="Used for clash warning in almanac")

    st.markdown("---")
    st.markdown("### 🔮 Lucky Numbers")
    st.caption("Enter 1–49, one per line: `NUMBER, reason`")
    lucky_text = st.text_area("", height=130,
        placeholder="27, My birthday\n16, Father's number\n8, Lucky 8\n48, My age")

    st.markdown("---")
    st.markdown("### ⚙️ Wheeling Pool")
    st.caption("8–12 numbers for full coverage (leave blank = auto)")
    wheel_text = st.text_area("", height=60, key="wheel",
        placeholder="11, 15, 22, 31, 38, 45, 49")

    st.markdown("---")
    generate = st.button("🎱 Generate My Picks", type="primary", use_container_width=True)
    st.caption("⚠️ For fun only. Odds: 1 in 13,983,816")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PAGE
# ══════════════════════════════════════════════════════════════════════════════

st.markdown('<div class="main-title">🎱 TOTO Lucky Generator</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Singapore Pools TOTO · AI + Mathematics + Numerology + Feng Shui · Mon · Thu</div>',
            unsafe_allow_html=True)

# ── Load TOTO DB ──────────────────────────────────────────────────────────────
if toto_upload:
    toto_bytes = toto_upload.read()
    st.cache_data.clear()
elif (toto_bytes := get_toto_bytes()):
    st.info("📂 TOTO data loaded from GitHub · Updates after every draw")
else:
    st.error("❌ Could not load TOTO database. Please upload toto_results.db.")
    st.stop()

df = load_toto_db(toto_bytes)

# ── Load Almanac DB ───────────────────────────────────────────────────────────
today_str = date.today().strftime("%Y-%m-%d")
almanac_data = None

if almanac_upload:
    almanac_bytes = almanac_upload.read()
elif (almanac_bytes := get_almanac_bytes()):
    almanac_bytes = almanac_bytes
else:
    almanac_bytes = None

if almanac_bytes:
    almanac_data = load_almanac_db(almanac_bytes, today_str)

# ── Stats strip ───────────────────────────────────────────────────────────────
freq      = compute_freq(df)
total_draws = len(df)
latest    = df.iloc[-1]
jackpot   = latest.get('jackpot_prize') or 'Unknown'

# Snowball streak
df['no_g1'] = ((df['g1_winners'].isna()) | (df['g1_winners'] == 0)).astype(int)
streak, streaks = 0, []
for v in df['no_g1']:
    streak = streak + 1 if v == 1 else 0
    streaks.append(streak)
df['streak'] = streaks
current_streak = int(df['streak'].iloc[-1])

c1, c2, c3, c4, c5 = st.columns(5)
for col, label, val in [
    (c1, "Valid Draws",    f"{total_draws:,}"),
    (c2, "Latest Draw",    f"#{int(latest['draw_number'])}"),
    (c3, "Draw Date",      str(latest['draw_date'].date()) if pd.notna(latest['draw_date']) else "—"),
    (c4, "Jackpot",        jackpot),
    (c5, "Snowball Streak",f"{current_streak} draws"),
]:
    col.markdown(f'<div class="stat-box"><div style="font-size:1.2rem;font-weight:700;color:#ffd700">{val}</div><div style="color:#888;font-size:0.75rem">{label}</div></div>',
                 unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

if not generate:
    st.markdown("""
    <div class="disclaimer">
    👈 Configure your settings in the sidebar, enter your lucky numbers, then click <b>Generate My Picks</b>.
    All methods combined — statistical, numerology, and feng shui — into one weekly output.
    </div>""", unsafe_allow_html=True)
    st.stop()

# ── Parse inputs ──────────────────────────────────────────────────────────────
lucky_numbers = []
for line in lucky_text.strip().split('\n'):
    line = line.strip()
    if not line: continue
    parts   = line.split(',', 1)
    num_str = parts[0].strip()
    reason  = parts[1].strip() if len(parts) > 1 else 'Lucky number'
    if num_str.isdigit() and 1 <= int(num_str) <= 49:
        lucky_numbers.append((num_str, reason))

wheel_numbers = []
for tok in re.split(r'[,\s]+', wheel_text.strip()):
    tok = tok.strip()
    if tok.isdigit() and 1 <= int(tok) <= 49:
        wheel_numbers.append(int(tok))

# ── Generate all pools ────────────────────────────────────────────────────────
top7_high = freq.nlargest(7).index.tolist()
top7_low  = freq.nsmallest(7).index.tolist()

hot_combo    = sorted(top7_high)[:combo_size]
cold_combo   = sorted(top7_low)[:combo_size]
random_combo = gen_pure_random(combo_size)
lucky_combos = derive_lucky_combo(lucky_numbers, freq, combo_size, top_n) if lucky_numbers else []

# Mirror
last_nums   = [int(latest[c]) for c in NUM_COLS]
last_add    = int(latest['additional']) if pd.notna(latest.get('additional')) else None
mirror_res  = mirror_formula(last_nums)
mirror_combo= sorted(list(set(mirror_res)))
if last_add and len(mirror_combo) < combo_size:
    s1 = last_add + 6
    if s1 > 49: s1 -= 49
    extra = mirror_number(s1)
    if extra not in mirror_combo:
        mirror_combo.append(extra)
mirror_combo = sorted(mirror_combo[:combo_size])

# Wheeling
if not wheel_numbers:
    anchor_nums  = [int(n) for n, _ in lucky_numbers if n.isdigit() and 1<=int(n)<=49]
    wheel_numbers = sorted(list(set(top7_high[:4] + anchor_nums)))[:10]
wheel_pool   = sorted(list(set(w for w in wheel_numbers if 1<=w<=49)))
wheel_combos = list(combo_iter(wheel_pool, combo_size)) if len(wheel_pool) >= combo_size else []

# ── RESULTS ───────────────────────────────────────────────────────────────────
st.markdown(f"### 🏆 Weekly Picks — {datetime.now().strftime('%A, %d %B %Y')}")
st.caption(f"Data: {total_draws:,} draws · System {combo_size} entry · Jackpot: {jackpot} · Snowball: {current_streak} draws")

tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
    "🗓️ Feng Shui", "🔴 Hot/Cold", "🎲 Random", "🔮 Lucky", "🪞 Mirror", "⚙️ Wheel", "📊 Analysis"
])

# ── TAB 1: ALMANAC ────────────────────────────────────────────────────────────
with tab1:
    if almanac_data:
        clash = almanac_data.get('clash_zodiac', '')
        is_clash = clash and your_zodiac.lower() == clash.lower()
        ausp_times = get_almanac_times(almanac_data)

        html  = '<div class="almanac-box">'
        html += f'<div style="font-size:1.1rem;font-weight:700;color:#ffd700;margin-bottom:12px">🗓️ TODAY\'s Buying Guidance — {almanac_data.get("gregorian_date")} ({almanac_data.get("day_of_week")})</div>'
        html += f'<div style="color:#ccc;margin-bottom:4px">农历 Lunar: <b>{almanac_data.get("lunar_date","")}</b> &nbsp;|&nbsp; {almanac_data.get("solar_term","")}</div>'
        html += f'<div style="color:#ccc;margin-bottom:12px">Day Pillar: <b>{almanac_data.get("day_pillar","")}</b> ({almanac_data.get("day_pillar_zh","")})</div>'

        if is_clash:
            html += f'<div style="background:rgba(231,76,60,0.15);border:1px solid #e74c3c;border-radius:8px;padding:10px;margin-bottom:12px">⚠️ <b>YOUR ZODIAC ({your_zodiac}) CLASHES TODAY</b> — consider buying less or skipping</div>'
        else:
            html += f'<div style="background:rgba(39,174,96,0.1);border:1px solid #27ae60;border-radius:8px;padding:10px;margin-bottom:12px">✅ Your zodiac ({your_zodiac}) is clear today (today\'s clash: {clash})</div>'

        html += '<div class="action-row">🚫 <b>Evil direction</b> — avoid facing: <b style="color:#e74c3c">' + almanac_data.get("evil_direction","—") + '</b></div>'
        html += '<div style="margin:12px 0 6px;font-weight:600;color:#ffd700">🧭 AUSPICIOUS DIRECTIONS</div>'
        html += f'<div class="action-row">财神 God of Wealth &nbsp;→&nbsp; <b style="color:#ffd700">{almanac_data.get("god_of_wealth","—")}</b></div>'
        html += f'<div class="action-row">喜神 God of Joy &nbsp;→&nbsp; <b style="color:#ffd700">{almanac_data.get("god_of_joy","—")}</b></div>'
        html += f'<div class="action-row">贵神 God of Happiness &nbsp;→&nbsp; <b style="color:#ffd700">{almanac_data.get("god_of_happiness","—")}</b></div>'

        html += '<div style="margin:14px 0 6px;font-weight:600;color:#ffd700">⏰ BEST TIMES TO BUY (SGT)</div>'
        for t in ausp_times:
            html += f'<div class="action-row">✅ <b style="color:#27ae60">{t}</b></div>'

        html += '<div style="margin:16px 0 8px;font-weight:700;color:#ffd700;font-size:1rem">📋 YOUR ACTION PLAN</div>'
        html += f'<div class="action-row">1️⃣ Go buy during: <b style="color:#ffd700">{ausp_times[0] if ausp_times else "any auspicious slot above"}</b></div>'
        html += f'<div class="action-row">2️⃣ Face this direction at counter: <b style="color:#ffd700">{almanac_data.get("god_of_wealth","—")}</b></div>'
        html += f'<div class="action-row">3️⃣ Choose outlet <b style="color:#ffd700">{almanac_data.get("god_of_wealth","—")}</b> of your home</div>'
        html += f'<div class="action-row">4️⃣ Do NOT face: <b style="color:#e74c3c">{almanac_data.get("evil_direction","—")}</b></div>'

        ausp_acts = almanac_data.get("auspicious_acts","")
        inausp_acts = almanac_data.get("inauspicious_acts","")
        if ausp_acts:
            html += f'<div style="margin-top:12px;color:#aaa;font-size:0.85rem">✅ 宜 Today suits: {ausp_acts}</div>'
        if inausp_acts:
            html += f'<div style="color:#aaa;font-size:0.85rem">❌ 忌 Avoid today: {inausp_acts}</div>'

        html += '<div style="margin-top:10px;color:#666;font-size:0.75rem">Source: chinese-calendar.net + chinesecalendaronline.com</div>'
        html += '</div>'
        st.markdown(html, unsafe_allow_html=True)
    else:
        st.warning(f"No almanac data for today ({today_str}). Upload almanac.db or push it to GitHub.")
        st.info("Run on MacBook: `python scrape_almanac.py --from 2026-01-01 --to 2026-12-31` then push to GitHub.")

# ── TAB 2: HOT / COLD ────────────────────────────────────────────────────────
with tab2:
    st.markdown(render_pick_card(
        f"Hot Balls — Top 7 most drawn all-time", "🔴",
        [hot_combo], freq, top7_high, top7_low, style='red'
    ), unsafe_allow_html=True)
    st.markdown(render_pick_card(
        f"Cold Balls — Top 7 least drawn all-time", "🔵",
        [cold_combo], freq, top7_high, top7_low, style='blue'
    ), unsafe_allow_html=True)

    # Frequency bar chart
    fig, ax = plt.subplots(figsize=(16, 3))
    fig.patch.set_facecolor('#0e1117')
    ax.set_facecolor('#1a1a2e')
    expected = total_draws * 6 / 49
    colors = ['#e74c3c' if n in top7_high else '#3498db' if n in top7_low else '#555' for n in range(1,50)]
    ax.bar(range(1, 50), [freq[n] for n in range(1,50)], color=colors, edgecolor='#0e1117', linewidth=0.4)
    ax.axhline(expected, color='#ffd700', linestyle='--', linewidth=1.2, alpha=0.7)
    ax.set_xticks(range(1,50)); ax.set_xticklabels(range(1,50), fontsize=6, color='#aaa')
    ax.tick_params(colors='#888'); ax.set_ylabel('Times Drawn', color='#aaa')
    for spine in ax.spines.values(): spine.set_edgecolor('#333')
    ax.set_title('Ball Frequency — All Valid Draws', color='white', fontsize=10)
    plt.tight_layout()
    st.pyplot(fig)

# ── TAB 3: RANDOM ────────────────────────────────────────────────────────────
with tab3:
    st.markdown(render_pick_card(
        f"Pure Random — No bias, completely uniform", "🎲",
        [random_combo], freq, top7_high, top7_low, style='green'
    ), unsafe_allow_html=True)
    st.caption("Every number 1–49 has equal probability. New combo every time you generate.")

# ── TAB 4: LUCKY ─────────────────────────────────────────────────────────────
with tab4:
    if lucky_combos:
        combos_only = [c for c, _ in lucky_combos]
        st.markdown(render_pick_card(
            f"Lucky Feel — Your anchors + cold fillers", "🔮",
            combos_only, freq, top7_high, top7_low, style='gold'
        ), unsafe_allow_html=True)
        st.caption(f"Anchors: {[int(n) for n,_ in lucky_numbers]} · Filled with coldest available balls")
    else:
        st.info("Enter your lucky numbers in the sidebar to activate this tab.")

# ── TAB 5: MIRROR ────────────────────────────────────────────────────────────
with tab5:
    st.markdown(render_pick_card(
        f"Mirror Numbers — Based on Draw #{int(latest['draw_number'])}", "🪞",
        [mirror_combo], freq, top7_high, top7_low, style='purple'
    ), unsafe_allow_html=True)

    # Show working
    st.markdown("**Step-by-step transformation:**")
    rows = []
    for n in last_nums:
        s1 = n + 6
        if s1 > 49: s1 -= 49
        s2 = mirror_number(s1)
        rows.append({"Original": n, "+6 mod 49": s1, "Mirror": s2})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=False)
    st.caption("Mirror table: 0↔5  1↔6  2↔7  3↔8  4↔9  7=pivot | Folk numerology — no statistical basis")

# ── TAB 6: WHEEL ─────────────────────────────────────────────────────────────
with tab6:
    if wheel_combos:
        cost = len(wheel_combos) * 7
        st.markdown(f"**Pool ({len(wheel_pool)} numbers):** {wheel_pool}")
        st.markdown(f"**Total System {combo_size} entries:** {len(wheel_combos):,} &nbsp;·&nbsp; **Cost:** ${cost:,} SGD")
        st.caption(f"Guarantee: if pool contains the 6 winning balls, at least 1 entry wins G1. Pool covers {len(wheel_pool)/49*100:.1f}% of all 49 balls.")
        show = min(30, len(wheel_combos))
        wdf  = pd.DataFrame([{"Combo": str(list(c)), "Sum": sum(c),
                               "Hot balls": str([n for n in c if n in top7_high])}
                              for c in wheel_combos[:show]])
        st.dataframe(wdf, hide_index=True, use_container_width=True)
        if len(wheel_combos) > show:
            st.caption(f"Showing first {show} of {len(wheel_combos):,} combinations.")
    else:
        st.info(f"Need at least {combo_size} numbers in pool. Auto-pool: {wheel_numbers}")

# ── TAB 7: ANALYSIS ──────────────────────────────────────────────────────────
with tab7:
    st.markdown("#### Ball Heatmap")
    fig2, ax2 = plt.subplots(figsize=(14, 5))
    fig2.patch.set_facecolor('#0e1117')
    ax2.set_facecolor('#0e1117')
    norm = plt.Normalize(freq.min(), freq.max())
    cmap = plt.cm.RdYlBu_r
    lucky_set = set(int(n) for n,_ in lucky_numbers if n.isdigit() and 1<=int(n)<=49)
    for i, num in enumerate(range(1, 50)):
        row_idx, col_idx = i // 7, i % 7
        circle = plt.Circle((col_idx, -row_idx), 0.42, color=cmap(norm(freq[num])), ec='#0e1117', lw=1.2)
        ax2.add_patch(circle)
        ax2.text(col_idx, -row_idx, str(num), ha='center', va='center',
                 fontsize=8, color='white',
                 fontweight='bold' if (num in top7_high or num in top7_low or num in lucky_set) else 'normal')
        marker = '🔮' if num in lucky_set else ('🔴' if num in top7_high else ('🔵' if num in top7_low else ''))
        if marker:
            ax2.text(col_idx+0.35, -row_idx+0.35, marker, fontsize=5)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    plt.colorbar(sm, ax=ax2, label='Times drawn')
    ax2.set_xlim(-0.6, 7.2); ax2.set_ylim(-7.2, 0.8)
    ax2.set_aspect('equal'); ax2.axis('off')
    ax2.set_title('Ball Heatmap · 🔴Hot · 🔵Cold · 🔮Lucky', color='white', fontsize=11)
    plt.tight_layout()
    st.pyplot(fig2)

    st.markdown("#### Jackpot History")
    df['jackpot_num'] = df['jackpot_prize'].apply(parse_money)
    df_j = df[df['jackpot_num'].notna()]
    if len(df_j) > 10:
        fig3, ax3 = plt.subplots(figsize=(14, 3))
        fig3.patch.set_facecolor('#0e1117')
        ax3.set_facecolor('#1a1a2e')
        ax3.fill_between(df_j['draw_number'], df_j['jackpot_num']/1e6, alpha=0.3, color='#f39c12')
        ax3.plot(df_j['draw_number'], df_j['jackpot_num']/1e6, color='#f39c12', lw=0.8)
        wins = df_j[df_j['g1_winners'] > 0]
        ax3.scatter(wins['draw_number'], wins['jackpot_num']/1e6, color='#e74c3c', s=15, zorder=5, label='G1 won')
        ax3.set_ylabel('Jackpot (SGD M)', color='#aaa')
        ax3.tick_params(colors='#888')
        for sp in ax3.spines.values(): sp.set_edgecolor('#333')
        ax3.legend(facecolor='#1a1a2e', labelcolor='white')
        ax3.set_title('Group 1 Jackpot History', color='white', fontsize=10)
        plt.tight_layout()
        st.pyplot(fig3)

# ── Prize table + disclaimer ──────────────────────────────────────────────────
st.markdown("---")
st.markdown("**💰 Prize Structure (System 7 = $7/entry)**")
prizes = {"G1 (6 nums)":"Share jackpot","G2 (5+add)":"Share G2 pool",
          "G3 (5 nums)":"Share G3 pool","G4 (4+add)":"$167+","G5 (4 nums)":"$50+"}
cols = st.columns(len(prizes))
for col, (k,v) in zip(cols, prizes.items()):
    col.markdown(f"**{k}**  \n{v}")

st.markdown("""
<div class="disclaimer">
⚠️ <b>Responsible gambling:</b> All numbers have equal 1-in-13,983,816 odds.
No system improves your probability of winning. Set a budget and stick to it.
<b>National Problem Gambling Helpline: 1800-6-668-668</b>
</div>
""", unsafe_allow_html=True)
