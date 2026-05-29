-- Cold call status pra Roleta de Leads (tools/roleta-leads)
-- Permite Maintainer percorrer leads quentes e marcar resultado da ligação/abordagem.

ALTER TABLE prospec_leads
  ADD COLUMN IF NOT EXISTS cold_call_status TEXT
    CHECK (cold_call_status IN ('PENDENTE','NAO_ATENDEU','SEM_INTERESSE','FOLLOW_UP','AGENDOU')),
  ADD COLUMN IF NOT EXISTS cold_call_last_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS cold_call_attempts INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS follow_up_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS cold_call_notes TEXT;

CREATE INDEX IF NOT EXISTS idx_prospec_leads_cold_call_status
  ON prospec_leads(cold_call_status);

CREATE INDEX IF NOT EXISTS idx_prospec_leads_tag_status
  ON prospec_leads(tag, cold_call_status);
