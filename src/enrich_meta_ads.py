"""
Enricher Meta Ad Library — pra cada lead em prospec_leads, verifica se tem ads ativos.

Uso:
    cd services/local-business-prospector && source venv/bin/activate
    export META_ACCESS_TOKEN=...   # token user/system com acesso ao Ad Library
    python3 enrich_meta_ads.py [--limit 50] [--cidade maringa]

Estratégia:
1. Lê leads sem `meta_ads_checked_at` ou checados há > 7 dias
2. Pra cada lead:
   - Se tem fb_page_id, busca por search_page_ids (preciso)
   - Senão usa search_terms=nome (impreciso, ~70% precisão)
3. Atualiza tem_anuncio_ativo + anuncios_ativos_count + meta_ads_checked_at

Endpoint Ad Library:
    GET https://graph.facebook.com/v21.0/ads_archive
        ?ad_active_status=ACTIVE
        &ad_reached_countries=['BR']
        &search_terms=...
        &fields=id,page_id,page_name,ad_creative_bodies
        &access_token=...
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from supabase import create_client

from cidades import CIDADES

load_dotenv()

GRAPH = "https://graph.facebook.com/v21.0/ads_archive"


def search_active_ads(client: httpx.Client, token: str, *, search_terms: str = None, page_id: str = None) -> int:
    params = {
        "ad_active_status": "ACTIVE",
        "ad_reached_countries": "['BR']",
        "ad_type": "ALL",
        "fields": "id,page_id,page_name",
        "limit": "100",
        "access_token": token,
    }
    if page_id:
        params["search_page_ids"] = f"['{page_id}']"
    elif search_terms:
        params["search_terms"] = search_terms
    else:
        return 0

    try:
        r = client.get(GRAPH, params=params, timeout=20.0)
        if r.status_code != 200:
            print(f"  [meta {r.status_code}] {r.text[:200]}", file=sys.stderr)
            return -1
        data = r.json().get("data", [])
        return len(data)
    except Exception as e:
        print(f"  [meta erro] {e}", file=sys.stderr)
        return -1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--cidade", help="filtra por cidade")
    p.add_argument("--recheck-days", type=int, default=7)
    args = p.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    token = os.environ.get("META_ACCESS_TOKEN")
    if not url or not key:
        print("ERRO: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY não definidos", file=sys.stderr)
        sys.exit(1)
    if not token:
        print("ERRO: META_ACCESS_TOKEN não definido", file=sys.stderr)
        sys.exit(1)

    supabase = create_client(url, key)

    q = supabase.table("prospec_leads").select(
        "id, nome, cidade, fb_page_id, facebook_url, meta_ads_checked_at"
    )
    if args.cidade:
        # resolve slug → nome real (com acento) pra matchar no banco
        match = next((c for c in CIDADES if c["slug"] == args.cidade), None)
        nome_real = match["nome"] if match else args.cidade
        q = q.eq("cidade", nome_real)
    q = q.order("score", desc=True).limit(args.limit)
    leads = q.execute().data

    print(f"Verificando {len(leads)} leads...")
    com_ad = 0
    com_fb = 0
    sem_match = 0

    with httpx.Client() as client:
        for lead in leads:
            time.sleep(0.4)  # rate limit gentil
            if lead.get("fb_page_id"):
                count = search_active_ads(client, token, page_id=lead["fb_page_id"])
                via = "page_id"
            elif lead.get("facebook_url"):
                slug = lead["facebook_url"].rstrip("/").split("/")[-1]
                count = search_active_ads(client, token, search_terms=slug)
                via = "fb_slug"
            else:
                count = search_active_ads(client, token, search_terms=lead["nome"])
                via = "nome"

            if count < 0:
                continue

            patch = {
                "tem_anuncio_ativo": count > 0,
                "anuncios_ativos_count": count,
                "meta_ads_checked_at": datetime.now(timezone.utc).isoformat(),
            }
            supabase.table("prospec_leads").update(patch).eq("id", lead["id"]).execute()

            if count > 0:
                com_ad += 1
            if lead.get("facebook_url"):
                com_fb += 1
            if count == 0 and via == "nome":
                sem_match += 1

            mark = "🎯" if count > 0 else "  "
            print(f"  {mark} ({count} ads via {via}) {lead['nome'][:50]}")

    print(f"\n══════════════════════")
    print(f"Verificados: {len(leads)}")
    print(f"Com ads ativos: {com_ad}")
    print(f"Com FB capturado: {com_fb}")
    print(f"Buscados por nome (impreciso): {len(leads) - com_fb}")


if __name__ == "__main__":
    main()
