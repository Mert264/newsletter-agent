-- Run this in the Supabase SQL Editor to create the newsletter corrections table.
-- Only needed once. If table already exists, run the ALTER statements at the bottom.

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
  brief TEXT DEFAULT '',
  figure_type TEXT DEFAULT '',
  topic TEXT DEFAULT 'general',
  status TEXT DEFAULT 'active'
);

CREATE INDEX IF NOT EXISTS idx_nl_corrections_specialist ON newsletter_corrections(specialist);
CREATE INDEX IF NOT EXISTS idx_nl_corrections_layer ON newsletter_corrections(layer);
CREATE INDEX IF NOT EXISTS idx_nl_corrections_ts ON newsletter_corrections(ts DESC);
CREATE INDEX IF NOT EXISTS idx_nl_corrections_status ON newsletter_corrections(status);
CREATE INDEX IF NOT EXISTS idx_nl_corrections_topic ON newsletter_corrections(topic);
CREATE INDEX IF NOT EXISTS idx_nl_corrections_figure_type ON newsletter_corrections(figure_type);

-- If table already exists, add the new columns:
-- ALTER TABLE newsletter_corrections ADD COLUMN IF NOT EXISTS figure_type TEXT DEFAULT '';
-- ALTER TABLE newsletter_corrections ADD COLUMN IF NOT EXISTS topic TEXT DEFAULT 'general';
-- ALTER TABLE newsletter_corrections ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active';
-- CREATE INDEX IF NOT EXISTS idx_nl_corrections_status ON newsletter_corrections(status);
-- CREATE INDEX IF NOT EXISTS idx_nl_corrections_topic ON newsletter_corrections(topic);
-- CREATE INDEX IF NOT EXISTS idx_nl_corrections_figure_type ON newsletter_corrections(figure_type);
