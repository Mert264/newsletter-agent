-- Run this in the Supabase SQL Editor to create the newsletter corrections table.
-- Only needed once.

CREATE TABLE IF NOT EXISTS newsletter_corrections (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  ts TIMESTAMPTZ DEFAULT now(),
  figure TEXT,
  specialist TEXT DEFAULT '',
  chart_type TEXT DEFAULT '',
  comment TEXT NOT NULL,
  layer TEXT DEFAULT 'all',
  source TEXT DEFAULT 'user',
  title TEXT DEFAULT '',
  brief TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_nl_corrections_specialist ON newsletter_corrections(specialist);
CREATE INDEX IF NOT EXISTS idx_nl_corrections_layer ON newsletter_corrections(layer);
CREATE INDEX IF NOT EXISTS idx_nl_corrections_ts ON newsletter_corrections(ts DESC);
