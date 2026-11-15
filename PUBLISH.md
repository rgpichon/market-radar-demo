# Publish Market Radar (portfolio demo)

## What ships

Flask app + SQLite (`events.db` with seeded events) + frontend. No Gmail secrets. Scraping/LLM features degrade if keys/services are absent.

## Local

```bash
cd Codes
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt gunicorn
cd backend
HOST=127.0.0.1 PORT=5001 ../.venv/bin/python app.py
```

Or from repo root: `./market_radar_ctl.sh start` → http://localhost:5001/

## Docker

```bash
cd Codes
docker build -t market-radar .
docker run --rm -p 5001:5001 market-radar
```

## Cloud

Needs a host that runs a container or Procfile (Render / Railway / Fly).  
`Dockerfile` and `Procfile` are ready. Set `PORT` from the platform. Do **not** upload `backend/_secrets/`.
