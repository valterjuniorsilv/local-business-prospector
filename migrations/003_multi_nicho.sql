-- 003_multi_nicho.sql
-- Generaliza prospec_leads e ig_templates pra múltiplos nichos (odonto, estetica, fisio, ...).
-- Pré-existente: prospec_leads.nicho já existe e está populado com 'odonto'.
-- Esta migration: garante constraint + adiciona nicho em ig_templates + backfill.

-- 1) Garante NOT NULL em prospec_leads.nicho (já populado com 'odonto')
UPDATE prospec_leads SET nicho = 'odonto' WHERE nicho IS NULL;
ALTER TABLE prospec_leads ALTER COLUMN nicho SET NOT NULL;

-- 2) Index pra filtros frequentes por nicho
CREATE INDEX IF NOT EXISTS idx_prospec_leads_nicho ON prospec_leads(nicho);
CREATE INDEX IF NOT EXISTS idx_prospec_leads_nicho_tag ON prospec_leads(nicho, tag);

-- 3) Adiciona nicho em ig_templates pra filtrar copy por vertical
ALTER TABLE ig_templates ADD COLUMN IF NOT EXISTS nicho TEXT;
UPDATE ig_templates SET nicho = 'odonto' WHERE nicho IS NULL;
ALTER TABLE ig_templates ALTER COLUMN nicho SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ig_templates_nicho_active ON ig_templates(nicho, active);

-- 4) Templates iniciais ESTÉTICA (ângulo TRÁFEGO/AGENDA)
INSERT INTO ig_templates (key, message, weight, nicho) VALUES
  ('estetica_curiosidade_clinica',
   E'Oi, {primeiro_nome}. Vi o perfil da {clinica}. Vocês hoje rodam anúncio pra trazer cliente novo ou é tudo indicação?',
   2, 'estetica'),
  ('estetica_volume_clinica',
   E'Oi, {primeiro_nome}. Dei uma olhada na {clinica}. Quantas clientes novas vocês atendem por mês hoje?',
   1, 'estetica'),
  ('estetica_aberta_clinica',
   E'Oi, {primeiro_nome}. Posso te perguntar uma coisa rápida sobre como vocês atraem cliente novo na {clinica}?',
   1, 'estetica'),
  ('estetica_curiosidade_pessoa',
   E'Oi, {primeiro_nome}. Vi seu perfil. Você hoje roda anúncio pra trazer cliente novo ou é tudo indicação?',
   2, 'estetica'),
  ('estetica_aberta_pessoa',
   E'Oi, {primeiro_nome}. Posso te perguntar uma coisa rápida sobre como você atrai cliente novo hoje?',
   1, 'estetica')
ON CONFLICT (key) DO NOTHING;

-- 5) Templates iniciais FISIO (ângulo TRÁFEGO/AGENDA)
INSERT INTO ig_templates (key, message, weight, nicho) VALUES
  ('fisio_curiosidade_clinica',
   E'Oi, {primeiro_nome}. Vi o perfil da {clinica}. Vocês hoje rodam anúncio pra trazer paciente novo ou é tudo indicação médica?',
   2, 'fisio'),
  ('fisio_volume_clinica',
   E'Oi, {primeiro_nome}. Dei uma olhada na {clinica}. Quantos pacientes novos vocês atendem por mês hoje?',
   1, 'fisio'),
  ('fisio_aberta_clinica',
   E'Oi, {primeiro_nome}. Posso te perguntar uma coisa rápida sobre como vocês atraem paciente novo na {clinica}?',
   1, 'fisio'),
  ('fisio_curiosidade_pessoa',
   E'Oi, {primeiro_nome}. Vi seu perfil. Você hoje roda anúncio pra trazer paciente novo ou é tudo indicação?',
   2, 'fisio'),
  ('fisio_aberta_pessoa',
   E'Oi, {primeiro_nome}. Posso te perguntar uma coisa rápida sobre como você atrai paciente novo hoje?',
   1, 'fisio')
ON CONFLICT (key) DO NOTHING;
