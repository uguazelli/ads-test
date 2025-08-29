import os
from datetime import date, timedelta, datetime
from typing import Optional
import json
import psycopg2
from fastapi import FastAPI, HTTPException
from dateutil.parser import isoparse

app = FastAPI()

def get_conn():
    return psycopg2.connect(
        host=os.getenv("PGHOST", "postgres"),
        port=os.getenv("PGPORT", "5432"),
        user=os.getenv("PGUSER", "ads"),
        password=os.getenv("PGPASSWORD", "ads123"),
        dbname=os.getenv("PGDATABASE", "adsdb"),
    )

def fetch_metrics(start: date, end: date):
    sql = """
    WITH daily AS (
      SELECT
        date,
        SUM(spend)::numeric(18,2)       AS spend,
        SUM(conversions)::numeric(18,2) AS conversions
      FROM ads_spend
      WHERE date >= %s AND date <= %s
      GROUP BY date
    ),
    agg AS (
      SELECT
        COALESCE(SUM(spend), 0)::numeric(18,2)       AS spend,
        COALESCE(SUM(conversions), 0)::numeric(18,2) AS conversions
      FROM daily
    )
    SELECT
      spend,
      conversions,
      CASE WHEN conversions = 0 THEN NULL ELSE spend / conversions END              AS cac,
      CASE WHEN spend = 0 THEN NULL ELSE (conversions * 100.0) / spend END         AS roas
    FROM agg;
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, (start, end))
        row = cur.fetchone()
        if not row:
            return None
        spend, conv, cac, roas = row
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "spend": float(spend or 0),
            "conversions": float(conv or 0),
            "CAC": None if cac is None else float(cac),
            "ROAS": None if roas is None else float(roas),
            "assumptions": {"revenue_per_conversion": 100}
        }

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/metrics")
def metrics(start: str, end: str):
    try:
        start_date = isoparse(start).date()
        end_date = isoparse(end).date()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format; use YYYY-MM-DD")
    if start_date > end_date:
        raise HTTPException(status_code=400, detail="start must be <= end")
    data = fetch_metrics(start_date, end_date)
    if data is None:
        raise HTTPException(status_code=404, detail="No data")
    return data

@app.get("/compare-30d")
def compare_30d():
    today = date.today()
    last_30_start = today - timedelta(days=30)
    prior_30_start = today - timedelta(days=60)
    prior_30_end = today - timedelta(days=31)

    last = fetch_metrics(last_30_start, today)
    prior = fetch_metrics(prior_30_start, prior_30_end)

    def pct_delta(a, b):
        if b in (0, None):
            return None
        if a is None or b is None:
            return None
        return (a - b) / b * 100.0

    out = {
        "last_30": last,
        "prior_30": prior,
        "deltas_pct": {
            "spend": pct_delta(last["spend"], prior["spend"]) if last and prior else None,
            "conversions": pct_delta(last["conversions"], prior["conversions"]) if last and prior else None,
            "CAC": pct_delta(last["CAC"], prior["CAC"]) if last and prior and last["CAC"] and prior["CAC"] else None,
            "ROAS": pct_delta(last["ROAS"], prior["ROAS"]) if last and prior and last["ROAS"] and prior["ROAS"] else None,
        }
    }
    return out
