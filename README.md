# 🎱 TOTO Lucky Generator

Singapore Pools TOTO — AI + Mathematics + Numerology + Feng Shui in one app.

---

## ✨ What It Does

| Method | Description |
|---|---|
| 🔴 **Hot/Cold Balls** | Top 7 most/least drawn across all historical draws |
| 🎲 **Pure Random** | Completely unbiased, equal probability for all 49 balls |
| 🔮 **Lucky Feel** | Your personal numbers as anchors + cold fillers |
| 🪞 **Mirror Numbers** | Folk formula: last draw → +6 mod 49 → mirror digits |
| ⚙️ **Wheeling System** | Full coverage calculator — guarantees G1 if pool contains winners |
| 🗓️ **Almanac Feng Shui** | TODAY's buying guidance — best time, direction, outlet location |

---

## 🚀 Run the App

### Option 1 — Streamlit Cloud (share a link)
1. Fork this repo
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect repo → select `app.py` → Deploy
4. Share the link!

### Option 2 — Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

---

## 📂 File Structure

```
toto-lucky-generator/
├── app.py                       # Streamlit web app
├── requirements.txt             # Dependencies
├── README.md                    # This file
├── scrape_toto.py               # Singapore Pools TOTO scraper
├── scrape_almanac.py            # Chinese Almanac (黄历) scraper
├── Toto_Optimizer_v3.ipynb      # Full analysis notebook
├── data/
│   ├── toto_results.db          # Scraped TOTO results
│   └── almanac.db               # Chinese Almanac data
└── output/
    └── toto_picks_YYYYMMDD.csv  # Weekly picks history
```

---

## 🔄 Weekly Update

```bash
# 1. Scrape latest draws
python scrape_toto.py
python scrape_almanac.py

# 2. Push to GitHub
git add data/toto_results.db data/almanac.db
git commit -m "Weekly update $(date +%Y-%m-%d)"
git push
```

Streamlit Cloud auto-redeploys within ~60 seconds.

---

## 🗓️ Almanac Feng Shui Feature

Pulls today's Chinese Almanac (黄历 / Tung Shing) to tell you:
- **Best hours** to go buy your ticket (auspicious Shi Chen slots)
- **Direction to face** at the counter (God of Wealth direction 财神)
- **Which outlet** to choose (directionally aligned with your home)
- **Clash warning** — if your Chinese zodiac clashes today

> ⚠️ Auspicious times are in SGT (GMT+8). For overseas family, times differ by timezone.

---

## ⚠️ Disclaimer

TOTO is a game of chance. Odds of winning Group 1: **1 in 13,983,816**.
No system improves your probability. Play responsibly.

**National Problem Gambling Helpline: 1800-6-668-668** (Singapore, 24/7)
