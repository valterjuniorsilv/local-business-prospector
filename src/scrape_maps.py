"""
Google Maps scraper via Playwright — multi-nicho.

Pra cada cidade: busca "<query do nicho> <cidade>", scrolla a sidebar, coleta cards.
Pra cada card: clica → pega telefone, site, rating, reviews, endereço.

Uso:
    python3 scrape_maps.py --nicho odonto --cidade "Maringá - PR" [--limit 60]
    python3 scrape_maps.py --nicho estetica  # roda todas as cidades pro nicho estética
    python3 scrape_maps.py --nicho fisio --limit 40

Nichos disponíveis: odonto, estetica, fisio (ver nichos.py).
"""
import argparse
import os
import random
import re
import sys
import time
from typing import Optional
from urllib.parse import quote_plus

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from supabase import create_client

from nichos import CIDADES, get_nicho, list_nichos

load_dotenv()

PHONE_RE = re.compile(r"\(?\d{2}\)?[\s-]*\d{4,5}[\s-]?\d{4}")
DIGITS_RE = re.compile(r"\D")


def normalize_phone(s: str) -> Optional[str]:
    digits = DIGITS_RE.sub("", s)
    if len(digits) == 11 or len(digits) == 10:
        return f"+55{digits}"
    if len(digits) == 13 and digits.startswith("55"):
        return f"+{digits}"
    return None


def calc_score(lead: dict) -> tuple[int, str, str]:
    s = 0
    if lead.get("instagram"): s += 30
    if lead.get("telefone") or lead.get("whatsapp"): s += 35
    if lead.get("facebook_url"): s += 5
    if lead.get("site"): s += 5
    rc = lead.get("reviews_count") or 0
    if rc >= 5: s += 10
    if rc >= 30: s += 5
    if (lead.get("rating") or 0) >= 4.5: s += 5
    if 5 <= rc <= 80: s += 5
    if s >= 70: return s, "alto", "quente"
    if s >= 40: return s, "medio", "morno"
    return s, "baixo", "frio"


def upsert_lead(supabase, lead: dict, cidade_nome: str, uf: str, nicho: str):
    payload = {
        "nicho": nicho,
        "nome": lead["nome"],
        "cidade": cidade_nome,
        "estado": uf,
        "endereco": lead.get("endereco"),
        "telefone": lead.get("telefone"),
        "whatsapp": lead.get("telefone"),
        "site": lead.get("site"),
        "instagram": lead.get("instagram"),
        "facebook_url": lead.get("facebook_url"),
        "rating": lead.get("rating"),
        "reviews_count": lead.get("reviews_count"),
        "fonte": "google_maps",
        "fonte_url": lead.get("fonte_url"),
        "raw_data": lead.get("raw_data") or {},
    }
    score, potencial, tag = calc_score(lead)
    payload["score"] = score
    payload["potencial"] = potencial
    payload["tag"] = tag

    try:
        supabase.table("prospec_leads").insert(payload).execute()
        return "inserted"
    except Exception as e:
        if "23505" in str(e) or "duplicate" in str(e):
            try:
                existing = supabase.table("prospec_leads").select("id, score") \
                    .filter("nome", "ilike", lead["nome"]) \
                    .filter("cidade", "ilike", cidade_nome) \
                    .limit(1).execute()
                if existing.data:
                    rid = existing.data[0]["id"]
                    cur = existing.data[0].get("score") or 0
                    patch = {k: v for k, v in payload.items() if v not in (None, "", [])}
                    if (patch.get("score") or 0) <= cur:
                        for k in ("score", "tag", "potencial"): patch.pop(k, None)
                    patch.pop("nome", None); patch.pop("cidade", None)
                    if patch:
                        supabase.table("prospec_leads").update(patch).eq("id", rid).execute()
                    return "updated"
            except Exception as e2:
                print(f"  [sb update] {e2}", file=sys.stderr)
                return "error"
        print(f"  [sb] {str(e)[:200]}", file=sys.stderr)
        return "error"


def scrape_cidade(page, cidade_nome: str, uf: str, nicho_cfg: dict, max_results: int = 80) -> list[dict]:
    """Abre Maps, busca <query do nicho> na cidade, scrolla sidebar, coleta cards."""
    query_term = random.choice(nicho_cfg["queries"])
    query = f"{query_term} {cidade_nome} {uf}"
    url = f"https://www.google.com/maps/search/{quote_plus(query)}/?hl=pt-BR"
    print(f"\n=== {cidade_nome}/{uf} · nicho={nicho_cfg.get('label', '?')} · q='{query_term}' ===")
    print(f"GET {url}")

    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(3500)

    # Sidebar com lista de resultados
    try:
        page.wait_for_selector('div[role="feed"]', timeout=15000)
    except PWTimeout:
        print("  [WARN] sidebar não carregou — talvez Google mudou layout")
        return []

    # Scroll na sidebar até "You've reached the end" ou max_results
    feed_sel = 'div[role="feed"]'
    seen = 0
    stagnant = 0
    for _ in range(40):
        cards = page.locator(f'{feed_sel} > div > div > a.hfpxzc').all()
        n = len(cards)
        if n >= max_results:
            break
        if n == seen:
            stagnant += 1
            if stagnant >= 3:
                break
        else:
            stagnant = 0
            seen = n
        page.evaluate("(sel) => document.querySelector(sel).scrollBy(0, 800)", feed_sel)
        page.wait_for_timeout(900)

    cards = page.locator(f'{feed_sel} > div > div > a.hfpxzc').all()
    print(f"  {len(cards)} cards encontrados")

    # Filtros vêm do dict do nicho (nichos.py)
    BLACKLIST = nicho_cfg["blacklist_re"]
    WHITELIST = nicho_cfg["whitelist_re"]

    leads = []
    skipped_blacklist = 0
    for i, card in enumerate(cards[:max_results]):
        try:
            nome = card.get_attribute("aria-label")
            href = card.get_attribute("href")
            if not nome:
                continue

            # Pular se bate na blacklist E não bate na whitelist (ex: "Hipermercado X" sem "odonto")
            if BLACKLIST.search(nome) and not WHITELIST.search(nome):
                skipped_blacklist += 1
                print(f"    [skip blacklist] {nome[:55]}")
                continue

            # Click pra abrir o painel à direita
            card.click()
            page.wait_for_timeout(1800)

            # Extrai do painel direito
            details = extract_details(page)
            details["nome"] = nome
            details["fonte_url"] = href
            leads.append(details)

            tel_mark = "📱" if details.get("telefone") else "  "
            site_mark = "🌐" if details.get("site") else "  "
            ig_mark = "📸" if details.get("instagram") else "  "
            print(f"    {i+1:2d}. {tel_mark}{site_mark}{ig_mark} {nome[:55]}")

        except Exception as e:
            print(f"    [erro] {e}", file=sys.stderr)
            continue

    return leads


def extract_details(page) -> dict:
    """Extrai detalhes do painel direito do Maps após click."""
    out: dict = {}

    # Telefone — botão com aria-label começando com "Telefone" ou contendo "+55"
    try:
        phone_btn = page.locator('button[data-item-id^="phone:tel:"]').first
        if phone_btn.count() > 0:
            label = phone_btn.get_attribute("aria-label") or ""
            m = PHONE_RE.search(label)
            if m:
                out["telefone"] = normalize_phone(m.group(0))
    except Exception:
        pass

    # Site — link com data-item-id="authority"
    try:
        site_btn = page.locator('a[data-item-id="authority"]').first
        if site_btn.count() > 0:
            href = site_btn.get_attribute("href")
            if href and href.startswith("http"):
                out["site"] = href
    except Exception:
        pass

    # Endereço — botão com data-item-id="address"
    try:
        addr_btn = page.locator('button[data-item-id="address"]').first
        if addr_btn.count() > 0:
            label = addr_btn.get_attribute("aria-label") or ""
            out["endereco"] = label.replace("Endereço:", "").strip()
    except Exception:
        pass

    # Rating + reviews count — geralmente em um span próximo ao h1
    try:
        rating_el = page.locator('div[role="main"] span[role="img"]').first
        if rating_el.count() > 0:
            label = rating_el.get_attribute("aria-label") or ""
            m = re.search(r"(\d[.,]\d+)", label)
            if m:
                try:
                    out["rating"] = float(m.group(1).replace(",", "."))
                except ValueError:
                    pass
    except Exception:
        pass

    try:
        reviews_btn = page.locator('button[aria-label*="avaliações" i], button[aria-label*="reviews" i]').first
        if reviews_btn.count() > 0:
            label = reviews_btn.get_attribute("aria-label") or ""
            m = re.search(r"([\d\.]+)\s*(avaliações|reviews)", label, re.I)
            if m:
                try:
                    out["reviews_count"] = int(m.group(1).replace(".", "").replace(",", ""))
                except ValueError:
                    pass
    except Exception:
        pass

    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--nicho", required=True, choices=list_nichos(),
                   help=f"nicho a prospectar: {', '.join(list_nichos())}")
    p.add_argument("--cidade", help="ex: Maringá - PR")
    p.add_argument("--limit", type=int, default=80, help="máximo de cards por cidade")
    p.add_argument("--headful", action="store_true", help="abrir browser visível pra debug")
    args = p.parse_args()

    nicho_cfg = get_nicho(args.nicho)

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("ERRO: defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY no .env", file=sys.stderr)
        sys.exit(1)
    sb = create_client(url, key)

    if args.cidade:
        if " - " in args.cidade:
            nome, uf = [s.strip() for s in args.cidade.split(" - ", 1)]
        else:
            match = next((c for c in CIDADES if c["nome"].lower() == args.cidade.lower()), None)
            if not match:
                print(f"cidade '{args.cidade}' não achada — passe 'Nome - UF'", file=sys.stderr)
                sys.exit(1)
            nome, uf = match["nome"], match["uf"]
        cidades = [{"nome": nome, "uf": uf}]
    else:
        cidades = CIDADES

    total_inserted = total_updated = total_errors = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headful)
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
            locale="pt-BR",
            viewport={"width": 1400, "height": 900},
        )
        page = ctx.new_page()

        for c in cidades:
            try:
                leads = scrape_cidade(page, c["nome"], c["uf"], nicho_cfg, max_results=args.limit)
            except Exception as e:
                print(f"  [erro cidade] {e}", file=sys.stderr)
                continue

            for lead in leads:
                result = upsert_lead(sb, lead, c["nome"], c["uf"], args.nicho)
                if result == "inserted": total_inserted += 1
                elif result == "updated": total_updated += 1
                else: total_errors += 1

        browser.close()

    print(f"\n══════════════════════")
    print(f"Inseridos:   {total_inserted}")
    print(f"Atualizados: {total_updated}")
    print(f"Erros:       {total_errors}")


if __name__ == "__main__":
    main()
