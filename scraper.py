#!/usr/bin/env python3
import json
import re
from datetime import datetime, date
from typing import List, Dict
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

IMFS_URL = "https://www.imfs-frankfurt.de/veranstaltungen/alle-kommenden-veranstaltungen"

SEMINARS = [
    {
        "id": "finance_seminar",
        "name": "Finance Seminar Series",
        "page": "https://www.old.wiwi.uni-frankfurt.de/abteilungen/finance/seminar/finance-seminar-series/seminar-calendar.html",
        "location": "HoF E.01 / Deutsche Bank room",
        "time_info": "Tuesdays 12:00–13:15",
    },
    {
        "id": "finance_brownbag",
        "name": "Finance Brown Bag",
        "page": "https://www.old.wiwi.uni-frankfurt.de/abteilungen/finance/seminar/brown-bag/finance-brown-bag.html",
        "location": "HoF E.20 / DZ Bank room",
        "time_info": "Wednesdays 14:00–15:00",
    },
    {
        "id": "mm_amos",
        "name": "AMOS Seminar (Management & Microeconomics)",
        "page": "https://www.old.wiwi.uni-frankfurt.de/abteilungen/mm/forschung/forschungskolloquien/amos.html",
        "location": "RuW 4.201",
        "time_info": "Usually Wednesdays 14:15",
    },
    {
        "id": "mm_brownbag",
        "name": "Management & Microeconomics Brown Bag",
        "page": "https://www.old.wiwi.uni-frankfurt.de/abteilungen/mm/forschung/forschungskolloquien/brown-bag-seminar.html",
        "location": "RuW 4.201",
        "time_info": "Thursdays 12:30–13:30",
    },
    {
        "id": "qep",
        "name": "Quantitative Economic Policy Seminar",
        "page": "https://www.old.wiwi.uni-frankfurt.de/abteilungen/eq/seminars/quantitative-economic-policy-seminar.html",
        "location": "RuW 4.202",
        "time_info": "",
    },
    {
        "id": "macro_seminar",
        "name": "Macro Seminar",
        "page": "https://www.old.wiwi.uni-frankfurt.de/abteilungen/money-and-macroeconomics/macro-seminar.html",
        "location": "HoF E.01 / Deutsche Bank room",
        "time_info": "Tuesdays 14:15–15:30",
    },
    {
        "id": "macro_brownbag",
        "name": "Money & Macro Brown Bag",
        "page": "https://www.old.wiwi.uni-frankfurt.de/abteilungen/money-and-macroeconomics/brown-bag-seminar.html",
        "location": "",
        "time_info": "",
    },
]

MONTH_MAP = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "mär": 3,
    "maer": 3,
    "maerz": 3,
    "märz": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "mai": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "okt": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "dez": 12,
    "december": 12,
}


def parse_date(date_str: str) -> date:
    """Handle all the weird date formats across the seminar pages."""
    s = date_str.strip()

    # 04 Nov 2025
    m = re.match(r"^(\d{1,2})\s+([A-Za-zÄÖÜäöü\.]+)\s+(\d{4})$", s)
    if m:
        day = int(m.group(1))
        month_name = m.group(2).strip(".").lower()
        year = int(m.group(3))
        month = MONTH_MAP.get(month_name)
        if not month:
            raise ValueError(f"Unknown month: {month_name} in {date_str}")
        return datetime(year, month, day).date()

    # Nov 18, 2025
    m = re.match(r"^([A-Za-zÄÖÜäöü\.]+)\s+(\d{1,2}),\s*(\d{4})$", s)
    if m:
        month_name = m.group(1).strip(".").lower()
        day = int(m.group(2))
        year = int(m.group(3))
        month = MONTH_MAP.get(month_name)
        if not month:
            raise ValueError(f"Unknown month: {month_name} in {date_str}")
        return datetime(year, month, day).date()

    # 27. November 2025
    m = re.match(r"^(\d{1,2})\.\s*([A-Za-zÄÖÜäöü\.]+)\s+(\d{4})$", s)
    if m:
        day = int(m.group(1))
        month_name = m.group(2).strip(".").lower()
        year = int(m.group(3))
        month = MONTH_MAP.get(month_name)
        if not month:
            raise ValueError(f"Unknown month: {month_name} in {date_str}")
        return datetime(year, month, day).date()

    # 27.11.2025
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", s)
    if m:
        day = int(m.group(1))
        month = int(m.group(2))
        year = int(m.group(3))
        return datetime(year, month, day).date()

    # Fallback to ISO-ish
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass

    raise ValueError(f"Unrecognized date format: {date_str}")


def fetch(url: str) -> BeautifulSoup:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def scrape_wiwi_table(cfg: Dict) -> List[Dict]:
    """Generic scraper for all old.wiwi.uni-frankfurt.de seminar tables."""
    url = cfg["page"]
    soup = fetch(url)
    table = soup.select_one("table.data-table-event")
    events: List[Dict] = []

    if not table:
        return events

    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if not tds:
            continue

        # Date
        date_td = tr.find("td", class_="dtstart-container") or tds[0]
        date_text = date_td.get_text(strip=True)
        if not date_text:
            continue

        try:
            d = parse_date(date_text)
        except Exception:
            # Skip rows with strange dates (usually non-event rows)
            continue

        # Speaker
        speaker_td = tr.find("td", class_="speaker") or (tds[1] if len(tds) > 1 else None)
        speaker = speaker_td.get_text(" ", strip=True) if speaker_td else ""

        # Title + details link
        summary_td = tr.find("td", class_="summary") or (tds[2] if len(tds) > 2 else None)
        title = ""
        details_url = url
        if summary_td:
            link = summary_td.find("a")
            if link:
                title = link.get_text(" ", strip=True)
                href = link.get("href")
                if href:
                    details_url = urljoin(url, href)
            else:
                title = summary_td.get_text(" ", strip=True)

        if not title:
            # Typically "Keine Ereignisse gefunden."
            continue

        events.append(
            {
                "seminar_id": cfg["id"],
                "seminar_name": cfg["name"],
                "seminar_page": cfg["page"],   # <- used by "Open seminar page" button
                "title": title,
                "speaker": speaker,
                "date": d.isoformat(),
                "raw_date": date_text,
                "time_info": cfg.get("time_info", ""),
                "location": cfg.get("location", ""),
                "details_url": details_url,
                "source": "Goethe University Frankfurt",
            }
        )

    return events


def scrape_imfs() -> List[Dict]:
    """Very lightweight scraper for IMFS upcoming events page."""
    soup = fetch(IMFS_URL)
    text = soup.get_text("\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    events: List[Dict] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        # Pick up "IMFS Working Lunch" / "Policy Lecture" blocks
        if "IMFS Working Lunch" in line or "Policy Lecture" in line:
            block: List[str] = []
            j = i + 1
            while j < len(lines) and lines[j]:
                block.append(lines[j])
                j += 1

            if len(block) >= 4:
                speaker = block[0]
                talk_title = block[1].strip('“”"')
                date_str = block[2]
                time_line = block[3]
                location_lines = block[4:7] if len(block) > 4 else []
                location = ", ".join(location_lines)

                try:
                    d = parse_date(date_str)
                except Exception:
                    i = j
                    continue

                events.append(
                    {
                        "seminar_id": "imfs",
                        "seminar_name": "IMFS Working Lunch / Policy Lecture",
                        "seminar_page": IMFS_URL,  # <- used by "Open seminar page" button
                        "title": talk_title,
                        "speaker": speaker,
                        "date": d.isoformat(),
                        "raw_date": date_str,
                        "time_info": time_line,
                        "location": location,
                        "details_url": IMFS_URL,
                        "source": "IMFS Frankfurt",
                    }
                )
            i = j
        else:
            i += 1

    return events


def main() -> None:
    all_events: List[Dict] = []

    # Wiwi seminar tables
    for cfg in SEMINARS:
        all_events.extend(scrape_wiwi_table(cfg))

    # IMFS
    all_events.extend(scrape_imfs())

    # De-duplicate (same seminar + title + date)
    seen = set()
    unique_events: List[Dict] = []
    for ev in all_events:
        key = (ev["seminar_id"], ev["title"], ev["date"])
        if key in seen:
            continue
        seen.add(key)
        unique_events.append(ev)

    # Sort by date (string ISO "YYYY-MM-DD" works lexicographically)
    unique_events.sort(key=lambda e: e["date"])

    with open("events.json", "w", encoding="utf-8") as f:
        json.dump(unique_events, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
