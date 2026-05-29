"""
Enricher IA — gera resumo + hook de cold call pra cada lead em prospec_leads.

Usa Claude Haiku 4.5 (mais barato e rápido) com os campos disponíveis:
nome, cidade, instagram, site, telefone, reviews_count, tag, tem_anuncio_ativo,
anuncios_ativos_count.

Output:
- enrichment_summary: 2-3 frases sobre a clínica (humano leria pra entender contexto)
- cold_call_hook: 1 frase pronta pra Maintainer falar no telefone, abrindo a call

Uso:
    cd services/local-business-prospector && source venv/bin/activate
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 enrich_summary_ai.py --nicho odonto [--limit 5] [--tag quente] [--dry-run]
    python3 enrich_summary_ai.py --nicho estetica --tag morno
    python3 enrich_summary_ai.py --nicho fisio

--dry-run imprime o output mas NÃO escreve no banco. Use pra validar prompt antes de
rodar na base inteira.
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote_plus

import httpx
from dotenv import load_dotenv
from supabase import create_client

from nichos import get_nicho, list_nichos

load_dotenv()

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"


def build_system_prompt(nicho_cfg: dict) -> str:
    label = nicho_cfg["label"]
    audiencia = nicho_cfg["audiencia"]  # "paciente" ou "cliente"
    return f"""Você é assistente de cold call B2B do Maintainer, fundador da YOUR_COMPANY (operação de marketing focada em clínicas brasileiras de {label}).

Pra cada lead, recebe os campos disponíveis (nome, cidade, IG, site, ads ativos etc.) e gera DOIS output curtos:

1. summary (2-3 frases): contexto humano sobre a clínica — quem é, onde está, sinais visíveis (presença digital, ads, reputação). Frases curtas, sem floreio, sem julgamento. Útil pra Maintainer ler em 5 segundos antes de discar.

2. hook (1 frase, máx 25 palavras): o QUE Maintainer fala no telefone após "é o Maintainer da YOUR_COMPANY". Começa com observação concreta sobre a clínica que abre porta. Pode ser:
   - sinal de quem NÃO ROOA ads ("vi que vocês não estão rodando anúncio")
   - sinal de quem RODA ads sem chamada clara ("vi que tem N anúncios rodando")
   - sinal de IG fraco ("o Insta de vocês tá lindo mas quase nada falando como agendar")
   - sinal de site sem CTA ("o site de vocês não tem botão de agendar")
   - sinal de reputação ("vi que vocês têm N avaliações no Google, reputação forte")
   Sempre BRASILEIRO INFORMAL ("vi que", "tô olhando"), nunca robotizado.

REGRAS:
- Sem emoji
- Sem hífen/travessão (use vírgula ou ponto)
- Sem "deixa eu me apresentar", "tudo bem?", "espero que esteja bem"
- Não promete resultado, não vende, não cita preço, não cita método
- Hook nunca começa com saudação — Maintainer já cumprimentou antes
- Refira-se ao público da clínica como "{audiencia} novo" (mesmo termo o lead usa)
- Output APENAS JSON válido com chaves `summary` e `hook`. Sem markdown, sem comentário.

EXEMPLOS (ajuste mental o termo "{audiencia}" pro nicho atual):

Lead sem ads, com IG, 87 reviews:
{{"summary": "Clínica em Toledo PR. Tem Instagram ativo mas sem anúncios pagos no momento. Reputação razoável com 87 avaliações no Google.", "hook": "vi que vocês não estão rodando anúncio. Aqui em Toledo tem clínica gastando 30, 50 reais por dia em Meta Ads e movendo agenda."}}

Lead com 12 ads ativos, IG forte, 340 reviews:
{{"summary": "Clínica em São Paulo. Já investe em tráfego (12 ads ativos) e tem boa presença digital. 340 avaliações no Google indica volume estabelecido.", "hook": "vi que vocês têm 12 anúncios rodando. Reparei que o criativo não tem chamada clara pra agendar, quem vê não sabe o próximo passo."}}

Lead sem IG, sem site, sem ads, 23 reviews:
{{"summary": "Clínica em Maringá PR. Presença digital muito limitada, sem Instagram nem site identificado, sem ads. 23 avaliações no Google.", "hook": "vi que vocês não têm presença digital ativa hoje. Em cidade do porte de Maringá isso significa {audiencia} novo só por indicação, sem previsibilidade."}}
"""


def build_user_msg(lead: dict) -> str:
    parts = [f"Nome: {lead.get('nome', 'N/A')}"]
    if lead.get("cidade"):
        parts.append(f"Cidade: {lead['cidade']}")
    if lead.get("instagram"):
        parts.append(f"Instagram: {lead['instagram']}")
    else:
        parts.append("Instagram: NÃO IDENTIFICADO")
    if lead.get("site"):
        parts.append(f"Site: {lead['site']}")
    else:
        parts.append("Site: NÃO IDENTIFICADO")
    if lead.get("facebook_url"):
        parts.append(f"Facebook: {lead['facebook_url']}")
    rc = lead.get("reviews_count")
    if rc is not None:
        parts.append(f"Reviews Google: {rc}")
    rating = lead.get("rating")
    if rating:
        parts.append(f"Rating Google: {rating}")
    taa = lead.get("tem_anuncio_ativo")
    if taa is True:
        n = lead.get("anuncios_ativos_count") or 0
        parts.append(f"Ads ativos: SIM ({n} anúncios rodando)")
    elif taa is False:
        parts.append("Ads ativos: NÃO ROOA NENHUM")
    else:
        parts.append("Ads ativos: NÃO VERIFICADO")
    return "\n".join(parts)


def call_haiku(client: httpx.Client, api_key: str, lead: dict, system_prompt: str) -> dict | None:
    body = {
        "model": MODEL,
        "max_tokens": 400,
        "system": system_prompt,
        "messages": [{"role": "user", "content": build_user_msg(lead)}],
    }
    try:
        r = client.post(
            ANTHROPIC_URL,
            json=body,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            timeout=60.0,
        )
        if r.status_code != 200:
            print(f"  [haiku {r.status_code}] {r.text[:200]}", file=sys.stderr)
            return None
        text = r.json()["content"][0]["text"].strip()
        # Remove markdown fence se vier
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        data = json.loads(text)
        return data if "summary" in data and "hook" in data else None
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        print(f"  [parse erro] {e} :: {text[:120]}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [http erro] {e}", file=sys.stderr)
        return None


def build_ads_library_url(lead: dict) -> str:
    q = lead.get("nome", "")
    return f"https://www.facebook.com/ads/library/?active_status=all&ad_type=all&country=BR&q={quote_plus(q)}&search_type=keyword_unordered"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--nicho", required=True, choices=list_nichos(),
                   help=f"nicho a enriquecer: {', '.join(list_nichos())}")
    p.add_argument("--limit", type=int, default=5, help="quantos leads processar")
    p.add_argument("--tag", default="quente", choices=["quente", "morno", "frio"])
    p.add_argument("--dry-run", action="store_true", help="imprime, não escreve")
    p.add_argument("--skip-existing", action="store_true",
                   help="pula leads que já tem cold_call_hook preenchido")
    args = p.parse_args()

    nicho_cfg = get_nicho(args.nicho)
    system_prompt = build_system_prompt(nicho_cfg)

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not url or not key:
        print("ERRO: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
        sys.exit(1)
    if not api_key:
        print("ERRO: ANTHROPIC_API_KEY não definida", file=sys.stderr)
        sys.exit(1)

    supabase = create_client(url, key)

    fields = ("id, nome, cidade, instagram, facebook_url, site, telefone, "
              "reviews_count, rating, tag, tem_anuncio_ativo, "
              "anuncios_ativos_count, cold_call_hook")
    q = (supabase.table("prospec_leads")
         .select(fields)
         .eq("tag", args.tag)
         .eq("nicho", args.nicho))
    q = q.order("score", desc=True).limit(args.limit)
    leads = q.execute().data

    if args.skip_existing:
        leads = [l for l in leads if not l.get("cold_call_hook")]

    print(f"Processando {len(leads)} leads (nicho={args.nicho}, tag={args.tag}, dry_run={args.dry_run})...")
    ok = 0
    falha = 0

    with httpx.Client() as client:
        for lead in leads:
            time.sleep(0.3)
            result = call_haiku(client, api_key, lead, system_prompt)
            if not result:
                falha += 1
                print(f"  ❌ {lead['nome'][:50]}")
                continue

            ads_url = build_ads_library_url(lead)
            patch = {
                "enrichment_summary": result["summary"],
                "cold_call_hook": result["hook"],
                "ads_library_url": ads_url,
            }

            if args.dry_run:
                print(f"\n--- {lead['nome']} ({lead.get('cidade', '?')}) ---")
                print(f"SUMMARY: {result['summary']}")
                print(f"HOOK:    {result['hook']}")
                print(f"ADS_URL: {ads_url[:80]}...")
            else:
                supabase.table("prospec_leads").update(patch).eq("id", lead["id"]).execute()
                print(f"  ✓ {lead['nome'][:60]}")
            ok += 1

    print(f"\n══════════════════════")
    print(f"Processados: {len(leads)}")
    print(f"OK: {ok}  Falhas: {falha}")
    if not args.dry_run:
        print(f"Persistido em prospec_leads (enrichment_summary, cold_call_hook, ads_library_url)")


if __name__ == "__main__":
    main()
