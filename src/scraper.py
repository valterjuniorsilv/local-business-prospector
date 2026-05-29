"""
Scraper Doctoralia → Supabase prospec_leads.

Estratégia:
1. Itera cidades (cidades.py)
2. Pra cada cidade, pagina /dentista/{slug}?page=N
3. Extrai cards (nome, endereço, URL perfil, reviews)
4. Visita perfil pra capturar telefone, site externo, IG quando disponível
5. Resolve IG via DuckDuckGo HTML quando ausente
6. Calcula score
7. Upserta no Supabase via service role (bypass RLS)

Uso:
    cd services/local-business-prospector
    python3 -m venv venv && source venv/bin/activate
    pip install -r requirements.txt
    export SUPABASE_URL=...
    export SUPABASE_SERVICE_ROLE_KEY=...
    python3 scraper.py [--cidade slug] [--max-pages N] [--limit N]
"""

import argparse
import os
import random
import re
import sys
import time
from typing import Optional
from urllib.parse import quote, urljoin

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from supabase import Client, create_client

from cidades import CIDADES

load_dotenv()

BASE = "https://www.doctoralia.com.br"

UAS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
]


def headers() -> dict:
    return {
        "User-Agent": random.choice(UAS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


def jitter(a: float = 1.5, b: float = 3.5):
    time.sleep(random.uniform(a, b))


def get(client: httpx.Client, url: str, retries: int = 3) -> Optional[str]:
    for attempt in range(retries):
        try:
            r = client.get(url, headers=headers(), timeout=20.0, follow_redirects=True)
            if r.status_code == 200:
                return r.text
            if r.status_code == 404:
                return None
            if r.status_code in (429, 503):
                wait = (attempt + 1) * 8
                print(f"  [{r.status_code}] backoff {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  [{r.status_code}] {url}", file=sys.stderr)
            return None
        except (httpx.RequestError, httpx.TimeoutException) as e:
            print(f"  [erro] {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))
    return None


PHONE_RE = re.compile(r"\(?\d{2}\)?[\s-]*\d{4,5}[\s-]?\d{4}")
IG_RE = re.compile(r"instagram\.com/([a-zA-Z0-9_.]{2,30})", re.IGNORECASE)
DIGITS_RE = re.compile(r"\D")


def normalize_phone(s: str) -> Optional[str]:
    digits = DIGITS_RE.sub("", s)
    if len(digits) == 11 or len(digits) == 10:
        return f"+55{digits}"
    if len(digits) == 13 and digits.startswith("55"):
        return f"+{digits}"
    return None


def parse_listing(html: str) -> list[dict]:
    """Extrai cards da listagem /dentista/{cidade}?page=N do Doctoralia."""
    soup = BeautifulSoup(html, "lxml")
    leads = []

    cards = soup.select('div[data-test-id="result-items-details"]')

    for card in cards:
        nome_el = card.select_one('[itemprop="name"]') or card.select_one("h3")
        nome = nome_el.get_text(strip=True) if nome_el else None
        if not nome:
            continue

        # URL do perfil
        url = None
        link = card.select_one('a[data-tracking-id="result-card-name"]') or card.select_one(
            'a[data-id="address-context-cta"]'
        )
        if not link:
            link = card.find("a", href=True)
        if link and link.get("href"):
            url = urljoin(BASE, link["href"])

        # Especialização
        spec_el = card.select_one('[data-test-id="doctor-specializations"]')
        especializacao = spec_el.get_text(" ", strip=True) if spec_el else None

        # Endereço — pega só a primeira linha útil (vem com "Mapa" e nome do dr juntos)
        end_el = card.select_one('[itemprop="address"]')
        endereco = None
        if end_el:
            raw = end_el.get_text(" ", strip=True)
            raw = re.sub(r"\s*•\s*Mapa.*$", "", raw)
            raw = re.sub(r"\s+Dr[a]?\.?\s+.*$", "", raw)
            endereco = raw.strip() or None

        # Reviews count
        reviews_count = None
        rev_el = card.select_one('[data-tracking-id="result-card-reviews"]')
        if rev_el:
            m = re.search(r"(\d+)", rev_el.get_text())
            if m:
                reviews_count = int(m.group(1))

        # Rating (às vezes aparece em data-tracking-id rating ou similar)
        rating = None
        rate_el = card.select_one('[itemprop="ratingValue"]')
        if rate_el:
            try:
                rating = float(rate_el.get_text(strip=True).replace(",", "."))
            except ValueError:
                pass
        if rating is None:
            # Doctoralia às vezes embute "5" ou "4.8" perto do bloco de reviews
            rate_text_el = card.select_one('.dp-doctor-rating-mark, [data-test-id*="rating"], .rating-value')
            if rate_text_el:
                m = re.search(r"(\d[.,]\d|\d)", rate_text_el.get_text())
                if m:
                    try:
                        rating = float(m.group(1).replace(",", "."))
                    except ValueError:
                        pass

        leads.append({
            "nome": nome,
            "endereco": endereco,
            "especializacao": especializacao,
            "fonte_url": url,
            "reviews_count": reviews_count,
            "rating": rating,
        })

    return leads


FB_URL_RE = re.compile(
    r"facebook\.com/(?!sharer|share|tr|plugins|dialog|ads)([a-zA-Z0-9._-]{2,80})",
    re.IGNORECASE,
)

# Lista negra: handles institucionais do Doctoralia/DocPlanner (rodapé do site)
INSTITUTIONAL_HANDLES = {
    "doctoralia", "doctoralia_br", "doctoralia.brasil", "docplanner",
    "doctoralia.es", "doctoralia.it", "doctoralia.pt", "doctoralia_es",
}
INSTITUTIONAL_DOMAINS = (
    "docplanner.com", "doctoralia.com", "docplanner.net",
)


def is_institutional_handle(handle: str) -> bool:
    return handle.lower().strip("/").split("/")[0] in INSTITUTIONAL_HANDLES


def parse_perfil(html: str, dentist_name: str | None = None) -> dict:
    """Extrai telefone, site, IG, Facebook + max info do perfil individual."""
    soup = BeautifulSoup(html, "lxml")

    # Foco: capturar info DENTRO do bloco principal do perfil (não rodapé do site)
    # O Doctoralia tem main[role=main] ou article principal
    main = (
        soup.find("main")
        or soup.select_one('[role="main"]')
        or soup.select_one('article[itemtype*="Person"]')
        or soup.select_one('article')
        or soup
    )

    text = main.get_text(" ", strip=True)

    telefone = None
    m = PHONE_RE.search(text)
    if m:
        telefone = normalize_phone(m.group(0))

    site = None
    ig = None
    fb = None

    # Procura links APENAS dentro do main, e filtra institucionais
    for a in main.find_all("a", href=True):
        href = a["href"]
        if "instagram.com" in href and not ig:
            mm = IG_RE.search(href)
            if mm:
                handle = mm.group(1).strip("/")
                if not is_institutional_handle(handle):
                    ig = handle
        elif "facebook.com" in href and not fb:
            mm = FB_URL_RE.search(href)
            if mm:
                slug = mm.group(1).strip("/")
                if slug.lower() not in {"profile.php", "people"} and not is_institutional_handle(slug):
                    fb = f"https://facebook.com/{slug}"
        elif (
            href.startswith(("http://", "https://"))
            and not site
            and not any(d in href.lower() for d in INSTITUTIONAL_DOMAINS)
            and not any(x in href.lower() for x in [
                "facebook.com", "instagram.com", "wa.me", "whatsapp",
                "google.com/maps", "youtube.com", "noa.ai", "twitter.com",
                "x.com", "linkedin.com", "tiktok.com", "doctoralia",
                "wp.me", "wordpress.com",
            ])
        ):
            site = href

    # Captura extra: especialidades completas, formação, planos, foto, CRO
    extra: dict = {}

    # Foto do dentista
    img = main.find("img", attrs={"itemprop": "image"})
    if img and img.get("src"):
        extra["foto"] = img["src"].replace("_medium_square", "_large")

    # Especialidades completas (vem na lista expandida)
    spec_block = main.select_one('.specializations-text, [data-test-id="doctor-specializations"]')
    if spec_block:
        extra["especialidades"] = spec_block.get_text(" ", strip=True)

    # CRO
    cro_match = re.search(r"CRO[\s/-]+([A-Z]{2})?\s*(\d{3,6})", text, re.I)
    if cro_match:
        extra["cro"] = f"CRO {cro_match.group(1) or ''} {cro_match.group(2)}".strip()

    # Tempo de experiência ("Experiência: 22 anos")
    exp_match = re.search(r"Experi[êe]ncia[:\s]+(\d+)\s*anos?", text, re.I)
    if exp_match:
        extra["anos_experiencia"] = int(exp_match.group(1))

    # Idiomas
    lang_match = re.search(r"Idiomas?[:\s]+([^\.]+?)(?:\.|·|$)", text, re.I)
    if lang_match:
        extra["idiomas"] = lang_match.group(1).strip()[:120]

    # Planos de saúde
    plans_match = re.search(
        r"Planos? de sa[úu]de aceitos?[:\s]+([^\.]{5,300})", text, re.I
    )
    if plans_match:
        extra["planos_saude"] = plans_match.group(1).strip()

    # Preço primeira consulta (R$ X)
    price_match = re.search(r"Primeira consulta[^R]*R\$\s*([\d.,]+)", text, re.I)
    if price_match:
        try:
            extra["preco_consulta"] = float(price_match.group(1).replace(".", "").replace(",", "."))
        except ValueError:
            pass

    extra["tem_teleconsulta"] = "Teleconsulta" in text

    return {
        "telefone": telefone,
        "site": site,
        "instagram": ig,
        "facebook_url": fb,
        **extra,
    }


def resolve_ig_via_search(client: httpx.Client, nome: str, cidade: str) -> Optional[str]:
    """Busca handle de IG via DuckDuckGo HTML."""
    query = quote(f'"{nome}" {cidade} site:instagram.com')
    url = f"https://html.duckduckgo.com/html/?q={query}"
    html = get(client, url, retries=2)
    if not html:
        return None
    m = IG_RE.search(html)
    if m:
        handle = m.group(1).strip("/").split("/")[0]
        if handle.lower() not in {"explore", "p", "reels", "accounts"}:
            return handle
    return None


def calc_score(lead: dict) -> tuple[int, str, str]:
    """Score 0-100. Retorna (score, potencial, tag)."""
    s = 0
    if lead.get("instagram"):
        s += 25
    if lead.get("telefone") or lead.get("whatsapp"):
        s += 25
    if (lead.get("reviews_count") or 0) >= 5:
        s += 15
    if (lead.get("reviews_count") or 0) >= 30:
        s += 10
    if (lead.get("rating") or 0) >= 4.5:
        s += 10
    if lead.get("site"):
        s += 5

    reviews = lead.get("reviews_count") or 0
    # Heurística pra ticket ≤ 30k: pouca review = clínica menor = ticket menor = nosso target
    if 5 <= reviews <= 50:
        s += 10  # ponto-doce: ativa mas não premium

    if s >= 70:
        return s, "alto", "quente"
    if s >= 45:
        return s, "medio", "morno"
    return s, "baixo", "frio"


def upsert_lead(supabase: Client, lead: dict, cidade: dict):
    payload = {
        "nicho": "odonto",
        "nome": lead["nome"],
        "cidade": cidade["nome"],
        "estado": cidade["uf"],
        "endereco": lead.get("endereco"),
        "instagram": lead.get("instagram"),
        "telefone": lead.get("telefone"),
        "whatsapp": lead.get("telefone"),  # mesmo número como WhatsApp por default no BR
        "site": lead.get("site"),
        "facebook_url": lead.get("facebook_url"),
        "rating": lead.get("rating"),
        "reviews_count": lead.get("reviews_count"),
        "foto": lead.get("foto"),
        "especialidades": lead.get("especialidades") or lead.get("especializacao"),
        "cro": lead.get("cro"),
        "anos_experiencia": lead.get("anos_experiencia"),
        "idiomas": lead.get("idiomas"),
        "planos_saude": lead.get("planos_saude"),
        "preco_consulta": lead.get("preco_consulta"),
        "tem_teleconsulta": lead.get("tem_teleconsulta"),
        "fonte": "doctoralia",
        "fonte_url": lead.get("fonte_url"),
        "raw_data": {"reviews_count": lead.get("reviews_count")},
    }
    score, potencial, tag = calc_score(lead)
    payload["score"] = score
    payload["potencial"] = potencial
    payload["tag"] = tag

    # Tenta INSERT; se bater na unique constraint, faz UPDATE pelo nome normalizado
    try:
        supabase.table("prospec_leads").insert(payload).execute()
        return "inserted"
    except Exception as e:
        msg = str(e)
        if "23505" in msg or "duplicate key" in msg or "already exists" in msg:
            try:
                # Busca normalizada — case-insensitive em nome+cidade
                existing = (
                    supabase.table("prospec_leads")
                    .select("id, score")
                    .filter("nome", "ilike", lead["nome"])
                    .filter("cidade", "ilike", cidade["nome"])
                    .limit(1)
                    .execute()
                )
                if existing.data:
                    row_id = existing.data[0]["id"]
                    cur_score = existing.data[0].get("score") or 0
                    patch = {k: v for k, v in payload.items() if v not in (None, "", [])}
                    if (patch.get("score") or 0) <= cur_score:
                        patch.pop("score", None)
                        patch.pop("tag", None)
                        patch.pop("potencial", None)
                    patch.pop("nome", None)
                    patch.pop("cidade", None)
                    if patch:
                        supabase.table("prospec_leads").update(patch).eq("id", row_id).execute()
                    return "updated"
                return "duplicate_no_match"
            except Exception as e2:
                print(f"  [supabase update] {e2}", file=sys.stderr)
                return "error"
        print(f"  [supabase insert] {msg[:200]}", file=sys.stderr)
        return "error"


_DDG_BLOCKED = False
_DDG_FAILS = 0


def resolve_ig_with_circuit_breaker(client: httpx.Client, nome: str, cidade: str) -> Optional[str]:
    """DDG resolve com circuit breaker — para de tentar após 5 falhas seguidas."""
    global _DDG_BLOCKED, _DDG_FAILS
    if _DDG_BLOCKED:
        return None
    result = resolve_ig_via_search(client, nome, cidade)
    if result is None:
        _DDG_FAILS += 1
        if _DDG_FAILS >= 5:
            print("  [ddg] desistindo de DDG nesta rodada (5 falhas seguidas)", file=sys.stderr)
            _DDG_BLOCKED = True
    else:
        _DDG_FAILS = 0
    return result


def run(args):
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("ERRO: defina SUPABASE_URL e SUPABASE_SERVICE_ROLE_KEY", file=sys.stderr)
        sys.exit(1)

    supabase = create_client(url, key)

    cidades = CIDADES
    if args.cidade:
        cidades = [c for c in CIDADES if c["slug"] == args.cidade]
        if not cidades:
            print(f"Cidade '{args.cidade}' não encontrada em cidades.py", file=sys.stderr)
            sys.exit(1)

    total_inserted = 0
    total_updated = 0
    total_errors = 0
    total_processed = 0

    with httpx.Client(http2=False) as client:
        for cidade in cidades:
            max_pages = args.max_pages or cidade.get("max_pages", 10)
            print(f"\n=== {cidade['nome']}/{cidade['uf']} (até {max_pages} pgs) ===")

            for page in range(1, max_pages + 1):
                if args.limit and total_processed >= args.limit:
                    break

                url_listing = f"{BASE}/dentista/{cidade['slug']}"
                if page > 1:
                    url_listing += f"?page={page}"

                print(f"\n→ pg {page}: {url_listing}")
                jitter(2.0, 4.0)
                html = get(client, url_listing)
                if not html:
                    print("  (sem html — fim da paginação ou bloqueio)")
                    break

                cards = parse_listing(html)
                if not cards:
                    print("  (sem cards na página)")
                    break

                print(f"  {len(cards)} cards encontrados")

                for card in cards:
                    if args.limit and total_processed >= args.limit:
                        break

                    total_processed += 1

                    if card.get("fonte_url"):
                        jitter(1.0, 2.5)
                        perfil_html = get(client, card["fonte_url"])
                        if perfil_html:
                            extra = parse_perfil(perfil_html)
                            card.update(extra)

                    if not card.get("instagram") and not args.no_ig_search:
                        jitter(0.8, 1.8)
                        ig = resolve_ig_with_circuit_breaker(client, card["nome"], cidade["nome"])
                        if ig:
                            card["instagram"] = ig

                    result = upsert_lead(supabase, card, cidade)
                    if result == "inserted":
                        total_inserted += 1
                        marker = "+"
                    elif result == "updated":
                        total_updated += 1
                        marker = "~"
                    else:
                        total_errors += 1
                        marker = "x"

                    ig_mark = "📸" if card.get("instagram") else "  "
                    tel_mark = "📱" if card.get("telefone") else "  "
                    print(f"    {marker} {ig_mark}{tel_mark} {card['nome'][:50]}")

            if args.limit and total_processed >= args.limit:
                break

    print(f"\n══════════════════════")
    print(f"Inseridos: {total_inserted}")
    print(f"Atualizados: {total_updated}")
    print(f"Erros: {total_errors}")
    print(f"Total processado: {total_processed}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--cidade", help="slug de uma cidade específica (ex: maringa)")
    p.add_argument("--max-pages", type=int, help="máx páginas por cidade (override)")
    p.add_argument("--limit", type=int, help="parar após N leads totais")
    p.add_argument("--no-ig-search", action="store_true", help="desabilita busca de IG via DuckDuckGo (mais rápido)")
    args = p.parse_args()
    run(args)
