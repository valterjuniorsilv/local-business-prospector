"""
Pra cada lead com site mas sem email, fetch HTML/contato e extrai email.

Estratégia:
1. Fetch homepage
2. Procura mailto: + regex de email no HTML
3. Se nada na home, tenta /contato, /contact, /fale-conosco
4. Filtra emails genéricos (no-reply, sender, contato@dominio-ferramenta)
5. Prefere email com domínio == domínio do site
"""
import os
import re
import sys
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", re.IGNORECASE)
MAILTO_RE = re.compile(r'mailto:([^"\'\s?>]+)', re.IGNORECASE)

# Emails genéricos / de ferramenta — pular
BLACKLIST_EMAIL = {
    "no-reply", "noreply", "no_reply", "donotreply",
    "sender", "robot", "mailer", "postmaster", "abuse",
    "wordpress", "wpadmin", "info@example", "test@test",
    "sentry", "wix", "google", "facebook",
}

# Páginas de contato comuns
CONTACT_PATHS = ["/contato", "/contact", "/fale-conosco", "/sobre", "/about"]


def is_valid(email: str, site_domain: str | None = None) -> bool:
    e = email.lower().strip()
    if any(b in e for b in BLACKLIST_EMAIL):
        return False
    if e.endswith((".png", ".jpg", ".gif", ".svg", ".webp", ".css", ".js")):
        return False
    if "sentry" in e or "wix" in e:
        return False
    # Email com domínio do site = excelente
    if site_domain and site_domain in e:
        return True
    # Email gmail/hotmail/yahoo de pessoa = OK
    if any(d in e for d in ["gmail.com", "hotmail.com", "yahoo.com", "outlook.com", "live.com", "uol.com.br", "bol.com.br"]):
        return True
    return True


def domain_of(url: str) -> str | None:
    try:
        p = urlparse(url)
        host = (p.netloc or "").lower().replace("www.", "")
        # tira .com.br, .com — fica só o nome principal
        parts = host.split(".")
        if len(parts) >= 2:
            return parts[-2]
        return None
    except Exception:
        return None


def extract_emails(html: str, site_domain: str | None) -> list[str]:
    found = set()
    # mailto: tem prioridade
    for m in MAILTO_RE.finditer(html):
        e = m.group(1).split("?")[0].strip()
        if is_valid(e, site_domain):
            found.add(e.lower())
    # regex geral
    for m in EMAIL_RE.finditer(html):
        e = m.group(0).strip()
        if is_valid(e, site_domain):
            found.add(e.lower())
    # Prioriza emails com domínio do site
    if site_domain:
        with_domain = [e for e in found if site_domain in e]
        if with_domain:
            return with_domain
    return list(found)


def main():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    sb = create_client(url, key)

    leads = (
        sb.table("prospec_leads")
        .select("id, nome, site, cidade")
        .is_("email", "null")
        .is_("email_source", "null")
        .not_.is_("site", "null")
        .in_("tag", ["quente", "morno"])
        .limit(2000)
        .execute()
        .data
    )

    print(f"Vai enriquecer {len(leads)} leads com site sem email...")
    com_email = falhas = 0

    with httpx.Client(
        timeout=15.0,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 Safari/605.1.15"},
    ) as client:
        for i, lead in enumerate(leads, 1):
            site = lead["site"]
            site_dom = domain_of(site)
            emails = []

            # Tenta home + páginas de contato
            urls_try = [site] + [site.rstrip("/") + p for p in CONTACT_PATHS]

            for u in urls_try:
                try:
                    r = client.get(u)
                    if r.status_code != 200:
                        continue
                    emails = extract_emails(r.text, site_dom)
                    if emails:
                        break
                except Exception:
                    continue

            if emails:
                # Pega o primeiro email válido
                email = emails[0]
                source = "site_dominio" if site_dom and site_dom in email else "site_geral"
                sb.table("prospec_leads").update({
                    "email": email,
                    "email_source": source,
                }).eq("id", lead["id"]).execute()
                com_email += 1
                mark = "📧"
            else:
                # Marca como tentado pra não reprocessar no próximo loop
                sb.table("prospec_leads").update({
                    "email_source": "not_found",
                }).eq("id", lead["id"]).execute()
                falhas += 1
                mark = "  "

            print(f"  {i:3d}/{len(leads)} {mark} {lead['nome'][:50]:50s} → {emails[0] if emails else '—'}")

    print(f"\n══════════════════════")
    print(f"Verificados: {len(leads)}")
    print(f"Com email:   {com_email}")
    print(f"Falhas:      {falhas}")
    print(f"══════════════════════")


if __name__ == "__main__":
    main()
