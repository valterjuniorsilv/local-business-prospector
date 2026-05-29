-- Tabela de outreach IG (DM enviado pelo bot Playwright)
CREATE TABLE IF NOT EXISTS ig_outreach (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id     UUID NOT NULL REFERENCES prospec_leads(id) ON DELETE CASCADE,
  template_key TEXT NOT NULL,
  message_sent TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'SENT'
              CHECK (status IN ('SENT','FAILED','BLOCKED','REPLIED','BOUNCED')),
  error_reason TEXT,
  reply_text   TEXT,
  reply_at     TIMESTAMPTZ,
  ig_handle    TEXT NOT NULL,
  sender_account TEXT NOT NULL DEFAULT 'valterjuniorsilv',
  sent_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ig_outreach_lead ON ig_outreach(lead_id);
CREATE INDEX IF NOT EXISTS idx_ig_outreach_status ON ig_outreach(status);
CREATE INDEX IF NOT EXISTS idx_ig_outreach_sent_at ON ig_outreach(sent_at DESC);

-- Templates iniciais (3 variações ângulo TRÁFEGO)
CREATE TABLE IF NOT EXISTS ig_templates (
  key         TEXT PRIMARY KEY,
  message     TEXT NOT NULL,
  active      BOOLEAN NOT NULL DEFAULT TRUE,
  weight      INT NOT NULL DEFAULT 1,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ig_templates (key, message, weight) VALUES
  ('trafego_curiosidade',
   E'Dr(a) {primeiro_nome}, vi o perfil da {clinica}. Vocês hoje rodam anúncio pra trazer paciente novo ou é tudo indicação?',
   2),
  ('trafego_volume',
   E'Dr(a) {primeiro_nome}, dei uma olhada na {clinica}. Quantos pacientes novos vocês atendem por mês hoje?',
   1),
  ('trafego_aberta',
   E'Dr(a) {primeiro_nome}, posso te perguntar uma coisa rápida sobre como vocês atraem paciente novo na {clinica}?',
   1)
ON CONFLICT (key) DO NOTHING;

-- Coluna no prospec_leads pra ter linkagem fácil + dedup futuro
ALTER TABLE prospec_leads
  ADD COLUMN IF NOT EXISTS ig_dm_sent_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS ig_dm_count INT NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_prospec_leads_ig_dm_sent_at ON prospec_leads(ig_dm_sent_at);
