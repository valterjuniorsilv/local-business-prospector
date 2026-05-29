"""
Nichos pra prospecção multi-vertical.

Cada nicho define:
- slug: string curta usada no Supabase (prospec_leads.nicho, ig_templates.nicho)
- queries: termos de busca pra Google Maps (rotação aleatória entre eles aumenta cobertura)
- whitelist_re: regex de aceitação no nome do card (positivo)
- blacklist_re: regex de rejeição (drogaria, farmácia, etc — listinha grande pra cortar lixo)
- ads_lib_keywords: termos pra busca Meta Ads Library (enrich_meta_ads)
- audiencia_label: como o lead-cliente chama o cliente-final ("paciente", "cliente")

NUNCA referencie "odonto"/"dentista" hardcoded em código de produção — sempre passa pelo dict.
"""

import re

NICHOS = {
    "odonto": {
        "label": "Odontologia",
        "queries": ["dentista", "clínica odontológica", "consultório odontológico"],
        "audiencia": "paciente",
        "whitelist_re": re.compile(
            r"(odonto|dent|orto|implant|sorri|maxilo|periodont|endodont|"
            r"pr[óo]tes|harmon|facial|cl[íi]nic|consult[óo]rio|dr\.|dra\.|"
            r"doutor|doutora|oral|sou\s*smile)",
            re.I,
        ),
        "blacklist_re": re.compile(
            r"(drogaria|farm[áa]cia|biomax|pacheco|hipermercado|supermercado|"
            r"^mercado |varejo|atacado|restaurante|lanchonete|padaria|"
            r"confeitaria|a[çc]ougue|faculdade|universidade|col[ée]gio|"
            r"^upa\b|hospital|posto de sa[úu]de|imobili[áa]ria|autoescola|"
            r"^hotel\b|^posto |shopping|panificadora|pizzaria|cafeteria|"
            r"barbearia|petshop|pet shop|mercearia|distribuidora|"
            r"[óo]ptica|joalheria|papelaria|bazar|churrascaria|sorveteria|"
            r"a[çc]a[íi]|escola |loja )",
            re.I,
        ),
        "ads_lib_keywords": ["dentista", "odontologia", "implante dentário"],
    },
    "estetica": {
        "label": "Clínica de Estética",
        "queries": [
            "clínica de estética",
            "estética facial",
            "harmonização facial",
            "depilação a laser",
            "criolipólise",
        ],
        "audiencia": "cliente",
        "whitelist_re": re.compile(
            r"(est[ée]tica|harmoniz|skin|beauty|depila|laser|botox|"
            r"preench|criolipo|drenagem|peeling|microagulhamento|"
            r"dermato|cl[íi]nic|spa\b|bem.estar|esteticista|biom[ée]dica?\b|"
            r"dr\.|dra\.|doutor|doutora)",
            re.I,
        ),
        "blacklist_re": re.compile(
            r"(drogaria|farm[áa]cia|hipermercado|supermercado|^mercado |"
            r"varejo|atacado|restaurante|lanchonete|padaria|confeitaria|"
            r"a[çc]ougue|faculdade|universidade|col[ée]gio|^upa\b|hospital|"
            r"posto de sa[úu]de|imobili[áa]ria|autoescola|^hotel\b|^posto |"
            r"shopping|panificadora|pizzaria|cafeteria|petshop|pet shop|"
            r"mercearia|distribuidora|[óo]ptica|joalheria|papelaria|bazar|"
            r"churrascaria|sorveteria|a[çc]a[íi]|escola |loja |academia|"
            r"crossfit|barbearia)",
            re.I,
        ),
        "ads_lib_keywords": ["clínica de estética", "harmonização facial", "criolipólise"],
    },
    "fisio": {
        "label": "Fisioterapia",
        "queries": [
            "fisioterapeuta",
            "clínica de fisioterapia",
            "fisioterapia ortopédica",
            "pilates clínico",
            "rpg",
        ],
        "audiencia": "paciente",
        "whitelist_re": re.compile(
            r"(fisio|ortop[ée]|pilates|rpg\b|reabilit|quiropr|osteopa|"
            r"pisado|postura|coluna|cinesio|terap[íi]a manual|"
            r"cl[íi]nic|consult[óo]rio|dr\.|dra\.|doutor|doutora)",
            re.I,
        ),
        "blacklist_re": re.compile(
            r"(drogaria|farm[áa]cia|hipermercado|supermercado|^mercado |"
            r"varejo|atacado|restaurante|lanchonete|padaria|confeitaria|"
            r"a[çc]ougue|faculdade|universidade|col[ée]gio|^upa\b|hospital|"
            r"posto de sa[úu]de|imobili[áa]ria|autoescola|^hotel\b|^posto |"
            r"shopping|panificadora|pizzaria|cafeteria|petshop|pet shop|"
            r"mercearia|distribuidora|[óo]ptica|joalheria|papelaria|bazar|"
            r"churrascaria|sorveteria|a[çc]a[íi]|escola |loja |academia|"
            r"crossfit|barbearia)",
            re.I,
        ),
        "ads_lib_keywords": ["fisioterapia", "pilates clínico", "rpg postura"],
    },
}


# Reexportado pra retrocompatibilidade (cidades.py virou parte daqui)
CIDADES = [
    # Capitais (peso alto)
    {"slug": "sao-paulo", "nome": "São Paulo", "uf": "SP", "max_pages": 30},
    {"slug": "rio-de-janeiro", "nome": "Rio de Janeiro", "uf": "RJ", "max_pages": 25},
    {"slug": "belo-horizonte", "nome": "Belo Horizonte", "uf": "MG", "max_pages": 20},
    {"slug": "curitiba", "nome": "Curitiba", "uf": "PR", "max_pages": 18},
    {"slug": "porto-alegre", "nome": "Porto Alegre", "uf": "RS", "max_pages": 18},
    {"slug": "brasilia", "nome": "Brasília", "uf": "DF", "max_pages": 18},
    {"slug": "goiania", "nome": "Goiânia", "uf": "GO", "max_pages": 15},
    {"slug": "fortaleza", "nome": "Fortaleza", "uf": "CE", "max_pages": 15},
    {"slug": "salvador", "nome": "Salvador", "uf": "BA", "max_pages": 15},
    {"slug": "recife", "nome": "Recife", "uf": "PE", "max_pages": 12},
    {"slug": "manaus", "nome": "Manaus", "uf": "AM", "max_pages": 10},
    {"slug": "florianopolis", "nome": "Florianópolis", "uf": "SC", "max_pages": 10},
    # Cidades médias / interior
    {"slug": "campinas", "nome": "Campinas", "uf": "SP", "max_pages": 12},
    {"slug": "sao-jose-dos-campos", "nome": "São José dos Campos", "uf": "SP", "max_pages": 8},
    {"slug": "ribeirao-preto", "nome": "Ribeirão Preto", "uf": "SP", "max_pages": 8},
    {"slug": "santos", "nome": "Santos", "uf": "SP", "max_pages": 8},
    {"slug": "sorocaba", "nome": "Sorocaba", "uf": "SP", "max_pages": 6},
    {"slug": "maringa", "nome": "Maringá", "uf": "PR", "max_pages": 6},
    {"slug": "londrina", "nome": "Londrina", "uf": "PR", "max_pages": 6},
    {"slug": "joinville", "nome": "Joinville", "uf": "SC", "max_pages": 6},
    {"slug": "uberlandia", "nome": "Uberlândia", "uf": "MG", "max_pages": 6},
    {"slug": "juiz-de-fora", "nome": "Juiz de Fora", "uf": "MG", "max_pages": 5},
    {"slug": "vitoria", "nome": "Vitória", "uf": "ES", "max_pages": 6},
    {"slug": "natal", "nome": "Natal", "uf": "RN", "max_pages": 6},
    {"slug": "joao-pessoa", "nome": "João Pessoa", "uf": "PB", "max_pages": 5},
    {"slug": "cuiaba", "nome": "Cuiabá", "uf": "MT", "max_pages": 5},
    {"slug": "campo-grande", "nome": "Campo Grande", "uf": "MS", "max_pages": 5},
    {"slug": "belem", "nome": "Belém", "uf": "PA", "max_pages": 6},
    {"slug": "aracaju", "nome": "Aracaju", "uf": "SE", "max_pages": 5},
    {"slug": "teresina", "nome": "Teresina", "uf": "PI", "max_pages": 5},
]


def get_nicho(slug: str) -> dict:
    if slug not in NICHOS:
        raise ValueError(f"Nicho desconhecido: '{slug}'. Disponíveis: {list(NICHOS.keys())}")
    return NICHOS[slug]


def list_nichos() -> list[str]:
    return list(NICHOS.keys())
