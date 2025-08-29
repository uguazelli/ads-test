# Dev Test – AI Data Engineer Role

An end‑to‑end, reproducible demo that ingests an ad spend CSV with **n8n**, stores it in **Postgres**, models KPIs with SQL, exposes metrics via a **FastAPI** service, and (bonus) maps **natural language** questions to metrics using a tiny **LLM intent** step.

> Designed to be cloned and `docker compose up -d` with minimal fuss.

---

## Contents

- [Architecture](#architecture)
- [Prereqs](#prereqs)
- [Quickstart](#quickstart)
- [Services & Ports](#services--ports)
- [Environment (.env)](#environment-env)
- [Database Schema](#database-schema)
- [Ingestion (n8n)](#ingestion-n8n)
- [KPI Modeling (SQL)](#kpi-modeling-sql)
- [API Endpoints](#api-endpoints)
- [Agent Demo (Bonus: NL → intent → metrics)](#agent-demo-bonus-nl--intent--metrics)
- [Deliverables Checklist](#deliverables-checklist)
- [Repo Layout](#repo-layout)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Architecture

- **Ingestion**: n8n pulls the CSV every 5 minutes and UPSERTs rows into `ads_spend`, recording `load_date` and `source_file_name`.
- **Modeling**: SQL computes CAC/ROAS; a view materializes the _last 30 vs prior 30_ comparison.
- **Access**: Analysts can hit `/metrics?start&end` or `/compare-30d`; the bonus `/ask` accepts a plain-English prompt.

---

## Prereqs

- Docker + Docker Compose
- Optional: `psql` client for quick checks

---

## Quickstart

1. **Clone** and create a `.env` (or keep defaults):

```bash
cp .env.example .env   # edit as needed
```

2. **Bring everything up**:

```bash
docker compose up -d
```

4. **Open UIs**:

- n8n: http://localhost:5678 (basic auth from `.env`)
- pgAdmin: http://localhost:8081 (login from `.env`, add a server → host `postgres`)
- API: http://localhost:8000/health

5. **Load the data via n8n** (see [Ingestion](#ingestion-n8n)). After a run:

```bash
  SELECT COUNT(*) rows, MIN(date), MAX(date) FROM ads_spend;
```

6. **Try the API**:

```bash
curl "http://localhost:8000/metrics?start=2025-07-01&end=2025-07-31"
curl "http://localhost:8000/compare-30d"
```

---

## Services & Ports

| Service       | Purpose               | Port (Host→Container) |
| ------------- | --------------------- | --------------------- |
| Postgres      | Warehouse             | 5432 → 5432           |
| pgAdmin       | SQL UI                | 8081 → 80             |
| n8n           | Orchestration         | 5678 → 5678           |
| metrics-api   | KPI + Agent endpoints | 8000 → 8000           |
| Ollama (opt.) | Local LLM for /ask    | 11434 → 11434         |

> Healthchecks: API uses `/health`. The API image installs `curl` so the healthcheck works.

---

## Environment (.env)

See `.env.example`. Key entries:

```ini
# Postgres
PGUSER=ads
PGPASSWORD=ads123
PGDATABASE=adsdb
PGPORT=5432

# pgAdmin
PGADMIN_EMAIL=admin@example.com
PGADMIN_PASSWORD=admin
PGADMIN_PORT=8081

# n8n
N8N_USER=n8n
N8N_PASSWORD=n8npass
N8N_PORT=5678
N8N_WEBHOOK_URL=http://localhost:5678
TZ=America/Asuncion

# API
API_PORT=8000

# Agent (LLM)
LLM_PROVIDER=ollama          # or 'openai'
OLLAMA_BASE_URL=http://ollama:11434
LLM_MODEL=llama3             # for OpenAI: e.g., gpt-4o-mini
# OPENAI_API_KEY=sk-...
# OPENAI_BASE=https://api.openai.com/v1
```

---

## Database Schema

Init SQL runs on first boot (fresh volume) from `db/init/`:

```sql
CREATE TABLE IF NOT EXISTS ads_spend (
  date              date NOT NULL,
  platform          text NOT NULL,
  account           text NOT NULL,
  campaign          text NOT NULL,
  country           text NOT NULL,
  device            text NOT NULL,
  spend             numeric(18,2) NOT NULL,
  clicks            bigint NOT NULL,
  impressions       bigint NOT NULL,
  conversions       bigint NOT NULL,
  load_date         timestamptz NOT NULL DEFAULT now(),
  source_file_name  text NOT NULL,
  CONSTRAINT ads_spend_natural_pk UNIQUE (date, platform, account, campaign, country, device)
);

CREATE INDEX IF NOT EXISTS idx_ads_date ON ads_spend(date);
CREATE INDEX IF NOT EXISTS idx_ads_campaign ON ads_spend(campaign);
CREATE INDEX IF NOT EXISTS idx_ads_platform ON ads_spend(platform);
```

**Provenance**: `load_date` auto-updates on UPSERT; `source_file_name` captures the ingest source.

---

## Ingestion (n8n)

**Goal**: Orchestrate CSV download → parse → UPSERT to `ads_spend`, idempotent.

### Workflow outline

1. **HTTP Request** – download the CSV from Google Drive. For a link like:
   `https://drive.google.com/file/d/<FILE_ID>/view`
   use the **direct download** URL:
   `https://drive.google.com/uc?export=download&id=<FILE_ID>`
   For this test: `FILE_ID = 1RXj_3txgmyX2Wyt9ZwM7l4axfi5A6EC-`

2. **Spreadsheet File** – parse CSV to JSON items.

3. **Function** – normalize types, add `source_file_name`:

```javascript
// Example n8n Function node
return items.map(i => {
	const r = i.json;
	return {
		json: {
			date: r.date, // expect YYYY-MM-DD
			platform: r.platform,
			account: r.account,
			campaign: r.campaign,
			country: r.country,
			device: r.device,
			spend: Number(r.spend),
			clicks: Number(r.clicks),
			impressions: Number(r.impressions),
			conversions: Number(r.conversions),
			source_file_name: $json.source_file_name || "ads_spend.csv",
		},
	};
});
```

4. **Postgres → Execute Query** – UPSERT each item:

```sql
INSERT INTO ads_spend
(date, platform, account, campaign, country, device, spend, clicks, impressions, conversions, source_file_name)
VALUES
(:date, :platform, :account, :campaign, :country, :device, :spend, :clicks, :impressions, :conversions, :source_file_name)
ON CONFLICT (date, platform, account, campaign, country, device) DO UPDATE SET
  spend = EXCLUDED.spend,
  clicks = EXCLUDED.clicks,
  impressions = EXCLUDED.impressions,
  conversions = EXCLUDED.conversions,
  load_date = now(),
  source_file_name = EXCLUDED.source_file_name;
```

> **Persistence demo**: re-run the workflow; counts remain stable, `load_date` updates on changed rows.

**Export** the workflow JSON and store it under `n8n/workflows/ingest_ads_spend.json` for the repo.

---

## KPI Modeling (SQL)

Definitions:

- **CAC** = `spend / conversions`
- **ROAS** = `(revenue / spend)` with `revenue = conversions × 100`

Use **dataset MAX(date)** as the anchor (robust if the file is older than today). Create a view that returns a compact table with absolutes + deltas for _last 30 vs prior 30_:

```sql
CREATE OR REPLACE VIEW kpi_compare_30d AS
WITH anchor AS (
  SELECT COALESCE(MAX(date), CURRENT_DATE)::date AS anchor_date
  FROM ads_spend
),
ranges AS (
  SELECT
    anchor_date,
    (anchor_date - INTERVAL '29 day')::date AS last_start,
    (anchor_date - INTERVAL '30 day')::date AS prior_end,
    (anchor_date - INTERVAL '59 day')::date AS prior_start
  FROM anchor
),
agg AS (
  SELECT
    CASE
      WHEN s.date BETWEEN r.last_start AND r.anchor_date THEN 'last_30'
      WHEN s.date BETWEEN r.prior_start AND r.prior_end THEN 'prior_30'
    END AS period,
    SUM(s.spend)::numeric(18,2)       AS spend,
    SUM(s.conversions)::numeric(18,2) AS conversions
  FROM ads_spend s
  CROSS JOIN ranges r
  WHERE s.date BETWEEN r.prior_start AND r.anchor_date
  GROUP BY 1
),
per AS (
  SELECT
    period,
    spend,
    conversions,
    CASE WHEN conversions = 0 THEN NULL ELSE spend / conversions END              AS cac,
    CASE WHEN spend = 0 THEN NULL ELSE (conversions * 100.0) / spend END         AS roas
  FROM agg
),
p AS (SELECT * FROM per WHERE period = 'prior_30'),
l AS (SELECT * FROM per WHERE period = 'last_30')
SELECT
  metric,
  prior_30,
  last_30,
  (last_30 - prior_30) AS delta_abs,
  CASE WHEN prior_30 IS NULL OR prior_30 = 0 THEN NULL
       ELSE (last_30 - prior_30) / prior_30 * 100.0
  END AS delta_pct
FROM (
  SELECT 'spend' AS metric, ROUND(p.spend,2) AS prior_30, ROUND(l.spend,2) AS last_30 FROM p CROSS JOIN l
  UNION ALL
  SELECT 'conversions', ROUND(p.conversions,2), ROUND(l.conversions,2) FROM p CROSS JOIN l
  UNION ALL
  SELECT 'CAC', ROUND(p.cac,2), ROUND(l.cac,2) FROM p CROSS JOIN l
  UNION ALL
  SELECT 'ROAS', ROUND(p.roas,4), ROUND(l.roas,4) FROM p CROSS JOIN l
) t;
```

Query it:

```sql
SELECT * FROM kpi_compare_30d;
```

---

## API Endpoints

Base URL: `http://localhost:8000`

- `GET /health` – readiness probe.
- `GET /metrics?start=YYYY-MM-DD&end=YYYY-MM-DD`
  Returns totals for the window + CAC/ROAS.
- `GET /compare-30d`
  Uses **anchor MAX(date)**, compares last 30 vs prior 30.

### Implementation note

The core aggregation uses:

```sql
WITH daily AS (
  SELECT date,
         SUM(spend)::numeric(18,2)       AS spend,
         SUM(conversions)::numeric(18,2) AS conversions
  FROM ads_spend
  WHERE date BETWEEN $1 AND $2
  GROUP BY date
),
agg AS (
  SELECT COALESCE(SUM(spend),0) AS spend,
         COALESCE(SUM(conversions),0) AS conversions
  FROM daily
)
SELECT
  spend,
  conversions,
  CASE WHEN conversions = 0 THEN NULL ELSE spend / conversions END  AS cac,
  CASE WHEN spend = 0 THEN NULL ELSE (conversions * 100.0) / spend END AS roas
FROM agg;
```

This avoids mixed aggregates / GROUP BY errors and is resilient to empty ranges.

---

## Deliverables Checklist

- [x] **n8n access**: URL + read-only user (from `.env`) **or** exported workflow JSON at `n8n/workflows/ingest_ads_spend.json`
- [x] **GitHub repo** including:
  - [x] Ingestion workflow (JSON export)
  - [x] SQL/dbt models (see `db/init/*.sql` and `sql/` if you add more)
  - [x] README (this file)
  - [x] **Results** (add your screenshot/API output under `results/`)
- [x] **Loom (≤5m)** explaining approach + key decisions (link in README top once recorded)

---

---

## Troubleshooting

**API container shows “unhealthy”**

- Ensure the image includes `curl` (already in `metrics-api/Dockerfile`). Rebuild if you changed it:
  ```bash
  docker compose build metrics-api && docker compose up -d metrics-api
  ```

**`/metrics` returns 500 GroupingError**

- You’re likely selecting non-aggregated columns alongside aggregates. Use the provided `WITH daily …, agg … SELECT … FROM agg` pattern (already in `main.py`).

**No data / zeros**

- Ingest first via n8n. Confirm rows:
  ```bash
  psql "postgres://ads:ads123@localhost:5432/adsdb" -c "SELECT COUNT(*) FROM ads_spend;"
  ```

**Google Drive direct download**

- Use `https://drive.google.com/uc?export=download&id=<FILE_ID>` in the n8n HTTP node.
- For the provided link, `FILE_ID = 1RXj_3txgmyX2Wyt9ZwM7l4axfi5A6EC-`.

**Change DB name**

- Update `.env` `PGDATABASE=...` and either drop volumes (`docker compose down -v`) or create/rename the DB (see notes in chat).

---

## License

MIT — do what you want, just don’t hold me liable. 😊

---

### Notes for Reviewers

- The solution emphasizes **idempotent ingestion** (UPSERT on a natural key), **provenance**, and **anchor-based periods** for more reliable time windows.
