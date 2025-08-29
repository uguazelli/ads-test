CREATE TABLE IF NOT EXISTS ads_spend (
  date           date NOT NULL,
  platform       text NOT NULL,
  account        text NOT NULL,
  campaign       text NOT NULL,
  country        text NOT NULL,
  device         text NOT NULL,
  spend          numeric(18,2) NOT NULL,
  clicks         bigint NOT NULL,
  impressions    bigint NOT NULL,
  conversions    bigint NOT NULL,
  load_date      timestamptz NOT NULL DEFAULT now(),
  source_file_name text NOT NULL,
  CONSTRAINT ads_spend_natural_pk UNIQUE (date, platform, account, campaign, country, device)
);

-- Helpful indexes
CREATE INDEX IF NOT EXISTS idx_ads_date ON ads_spend(date);
CREATE INDEX IF NOT EXISTS idx_ads_campaign ON ads_spend(campaign);
CREATE INDEX IF NOT EXISTS idx_ads_platform ON ads_spend(platform);
