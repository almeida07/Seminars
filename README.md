# Goethe Econ Seminar Dashboard

Static website + scraper that aggregates upcoming seminars from several Goethe University / IMFS pages into a single JSON file and shows them in a small dashboard.

## Included sources

- Finance Seminar Series (Goethe Finance) – Winter term calendar
- Finance Brown Bag (Goethe Finance)
- AMOS – Applied Microeconomics and Organization Seminar
- Brown Bag Seminar (Management & Microeconomics)
- Quantitative Economic Policy Seminar (EQ)
- Macroeconomics Seminar (Money & Macroeconomics)
- Brown Bag Seminar (Money & Macroeconomics – currently inactive, scraper will just find no events)
- IMFS – “Alle kommenden Veranstaltungen” page (for Working Lunches etc.)

All pages are scraped regularly by a GitHub Action which regenerates `events.json`.

## File overview

- `scraper.py` – downloads all seminar pages, parses the upcoming events and writes `events.json`
- `index.html` – static dashboard that reads `events.json` and displays the events
- `requirements.txt` – Python dependencies for the scraper
- `.github/workflows/update-events.yml` – GitHub Actions workflow to run the scraper on a schedule

## Local development

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python scraper.py  # generates events.json
