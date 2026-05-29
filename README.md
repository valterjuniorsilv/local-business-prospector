# Local Business Prospector

[![CI](https://github.com/valterjuniorsilv/local-business-prospector/actions/workflows/ci.yml/badge.svg)](https://github.com/valterjuniorsilv/local-business-prospector/actions) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) [![Release](https://img.shields.io/github/v/release/valterjuniorsilv/local-business-prospector)](https://github.com/valterjuniorsilv/local-business-prospector/releases)

> Pipeline pra prospecção B2B de PMEs locais (clínicas, salões, lojas físicas). Vai do **scraping do Google Maps** ao **lead qualificado com IA**, passando por enriquecimento de email, Instagram e Meta Ads Library.
>
> Sanitizado e extraído de uma operação real rodando em produção há ~12 meses — onde nasceu como `dentist-prospector`, depois virou multi-vertical (odonto, estética, nail, barber, imobiliária).

---

## O que faz

```
┌─────────────────────────────────────────────────────────────────┐
│  Google Maps (cidade + nicho)                                   │
│        │                                                         │
│        ▼  scrape_maps.py                                        │
│  ┌─────────────────┐                                            │
│  │ Lead bruto      │  name, address, phone, gmaps_url           │
│  └────────┬────────┘                                            │
│           │                                                      │
│   ┌───────┼───────┬───────────┬───────────┐                     │
│   ▼       ▼       ▼           ▼           ▼                     │
│  email   IG      Meta Ads    site         CNPJ                  │
│  scrape  scrape  Library     details      lookup                │
│           │                                                      │
│           ▼  enrich_summary_ai.py (Claude)                      │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Lead qualificado (JSON)                                  │   │
│  │  - Anúncia? Rotacionou criativos? Frequência?            │   │
│  │  - IG ativo? Frequência de posts? Reels?                 │   │
│  │  - Email válido? Site profissional?                       │   │
│  │  - Score de "lead quente" (1-10)                          │   │
│  └────────────┬─────────────────────────────────────────────┘    │
│               ▼                                                  │
│         Supabase (postgres) ← multi-tenant via RLS               │
└─────────────────────────────────────────────────────────────────┘
```

---

## Stack

- **Python 3.11+**
- **Playwright** (browser automation, anti-detection com `playwright-stealth`)
- **httpx + BeautifulSoup4** (scraping leve)
- **Supabase** (Postgres + auth)
- **Anthropic Claude** (sumarização do lead, score de qualificação)

---

## Niches incluídos por padrão

`niches.py` ([src/niches.py](./src/niches.py)) tem dicts pré-configurados para:

| Slug | Vertical | Audience term |
|---|---|---|
| `odonto` | Odontologia | paciente |
| `estetica` | Clínicas de estética | cliente |
| `nail` | Estúdios de nail / manicure | cliente |
| `barber` | Barbearias | cliente |
| `imobiliaria` | Imobiliárias / corretores | cliente |
| `odonto-prosp-emp` | Odonto-prosp (variação ICP empresarial) | paciente |

Cada nicho define:

- `queries` — termos rotativos pra Google Maps
- `whitelist_re` — regex aceita
- `blacklist_re` — regex rejeita (drogaria, farmácia, etc — corta ~30% de lixo)
- `ads_lib_keywords` — termos pra Meta Ads Library
- `audiencia_label` — o nome que o lead chama o cliente final

**Adicionar um nicho novo:** copia um dict existente, ajusta os regex e queries. ~20 linhas de Python.

---

## Scripts

| Script | O que faz |
|---|---|
| [`src/scrape_maps.py`](./src/scrape_maps.py) | Scraping Google Maps por cidade + nicho. Salva no Supabase com dedup. |
| [`src/scraper.py`](./src/scraper.py) | Scraping de sites (extrai email, telefone, links sociais). |
| [`src/enrich_email_from_site.py`](./src/enrich_email_from_site.py) | Pega lead com site, raspa o site, extrai email. |
| [`src/enrich_meta_ads.py`](./src/enrich_meta_ads.py) | Bate Meta Ads Library, vê se o lead anuncia + frequência de criativos. |
| [`src/enrich_summary_ai.py`](./src/enrich_summary_ai.py) | Resumo + score do lead via Claude (1-10 score). |
| [`src/cities.py`](./src/cities.py) | Helper de cidades BR (por estado, por região). |
| [`src/niches.py`](./src/niches.py) | Definição de cada vertical. |

---

## Schema (Postgres / Supabase)

```sql
-- migrations/001_ig_outreach.sql
CREATE TABLE prospec_leads (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  nicho         TEXT NOT NULL,
  name          TEXT NOT NULL,
  city          TEXT NOT NULL,
  state         TEXT NOT NULL,
  phone         TEXT,
  email         TEXT,
  site          TEXT,
  ig_handle     TEXT,
  gmaps_url     TEXT,
  -- enrichment
  ads_active    BOOLEAN,
  ads_count     INTEGER,
  ig_score      INTEGER,
  ai_summary    TEXT,
  lead_score    INTEGER,  -- 1-10
  -- audit
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Full migrations in [`migrations/`](./migrations/).

---

## Quickstart

```bash
git clone https://github.com/valterjuniorsilv/local-business-prospector.git
cd local-business-prospector

python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# Fill in: SUPABASE_URL, SUPABASE_SERVICE_KEY, ANTHROPIC_API_KEY

# Run migrations on Supabase
psql $DATABASE_URL -f migrations/001_ig_outreach.sql
psql $DATABASE_URL -f migrations/002_cold_call_status.sql
psql $DATABASE_URL -f migrations/003_multi_nicho.sql

# Scrape leads for one niche + city
python -m src.scrape_maps --niche odonto --city "Maringá" --state PR --limit 100

# Enrich
python -m src.enrich_email_from_site
python -m src.enrich_meta_ads
python -m src.enrich_summary_ai
```

---

## Cost (real-world)

For ~1000 leads enriched fully:

| Item | Cost |
|---|---|
| Playwright (your own machine) | $0 |
| Supabase (free tier suficiente até ~10k leads) | $0 |
| Claude Haiku 4.5 para resumo+score (~500 tokens out cada) | ~$0.50 |
| **Total** | **~$0.50 / 1000 leads enriquecidos** |

Compare com Apollo/ZoomInfo: $300+/mês fixo.

---

## What this does NOT do

- **DM outreach automation** — esse pedaço fica fora do template público (cada plataforma tem seus termos de uso, e fazer mass-DM via scraping é cinza legal). Você prospecta aqui, depois decide manualmente o canal de aproximação.
- **CRM integration** — não tem conector Pipedrive/HubSpot pronto. Tem schema Postgres que você integra via webhook.
- **Anti-CAPTCHA** — Google Maps eventualmente exibe CAPTCHA. Mitigação: `playwright-stealth` + delays randomizados + IPs residenciais. Não é defesa permanente.

---

## Ethics

Esta ferramenta acessa dados públicos via Google Maps e sites publicados. Você é responsável por:

- Respeitar `robots.txt` (o scraper respeita por padrão; passe `--ignore-robots` se quiser, sob seu risco)
- LGPD/GDPR — não retenha PII além do necessário pro ciclo de venda
- Termos de uso das plataformas que você scrapa
- Não fazer cold outreach em escala sem opt-out claro

Se você usar isso pra spam, **eu desligo o repo**. Não brinco.

---

## License

MIT — see [LICENSE](./LICENSE).

---

## Author

**Valter Silva** · Founder [NodusHub](https://nodushub.com.br) · Maringá, PR · 🇧🇷

Companion repos:

- [claude-skills](https://github.com/valterjuniorsilv/claude-skills) — Claude Code skills
- [nodus-agents](https://github.com/valterjuniorsilv/nodus-agents) — agency multi-agent setup
- [claude-whatsapp-template](https://github.com/valterjuniorsilv/claude-whatsapp-template) — bot WhatsApp + Claude
- [antigravity-lab](https://github.com/valterjuniorsilv/antigravity-lab) — Go backend reference

> "Na area, não nas arquibancadas."
