#!/usr/bin/env python3
"""Génère et publie le prochain article du blog Actu Éco & Finance.

Deux types d'articles, en alternance :
  - « actu »  : un sujet économique ou financier des derniers jours, trouvé par
                recherche web, avec ses sources ;
  - « fond »  : le prochain sujet pédagogique non publié de scripts/topics.json.

Étapes :
  1. Vérifie que le dernier article date d'au moins BLOG_INTERVAL_DAYS jours (2 par défaut).
  2. Choisit le type (l'inverse du dernier article publié, ou BLOG_MODE=actu|fond).
  3. Demande l'article à l'API Anthropic (clé dans ANTHROPIC_API_KEY), avec la
     recherche web pour l'actualité et la vérification des chiffres.
  4. Valide le résultat (longueur, format, liens, sources, avertissement sur les risques...).
  5. Écrit _posts/AAAA-MM-JJ-slug.md (et marque le sujet comme publié pour un article de fond).

Si la validation échoue (après MAX_ATTEMPTS essais), rien n'est écrit et le
script se termine avec le code 1 : le workflow échoue proprement.

Options :
  --dry-run          n'écrit rien dans _posts/ ni topics.json ; l'aperçu va dans _preview/
  --from-file PATH   valide un texte déjà rédigé au lieu d'appeler l'API (tests hors ligne)
  --not-before HOUR  ne publie pas avant cette heure (heure de Paris) ; utilisé par le cron
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TOPICS_FILE = ROOT / "scripts" / "topics.json"
POSTS_DIR = ROOT / "_posts"
PREVIEW_DIR = ROOT / "_preview"
TZ = ZoneInfo("Europe/Paris")

MODEL = os.environ.get("BLOG_MODEL", "claude-sonnet-5-5")
EFFORT = os.environ.get("BLOG_EFFORT", "medium")
INTERVAL_DAYS = int(os.environ.get("BLOG_INTERVAL_DAYS", "2"))
MAX_ATTEMPTS = 2
MAX_CONTINUATIONS = 1  # reprises après pause_turn (recherche web longue)
# Plafond de recherches web par article : chaque résultat est relu en entrée, c'est le premier poste de coût.
MAX_SEARCHES = {"actu": int(os.environ.get("BLOG_MAX_SEARCHES_ACTU", "2")),
                "fond": int(os.environ.get("BLOG_MAX_SEARCHES_FOND", "2"))}

MIN_WORDS, MAX_WORDS = 650, 1250
MAX_DESCRIPTION = 155

SITE = "https://www.moovapp.org"
SITE_PAGES = {
    "/": "page d'accueil : terminal de marché (prix en temps réel, signaux, niveaux institutionnels)",
    "/calendrier-economique": "calendrier économique (dates et heures des publications CPI, NFP, PIB, décisions de taux)",
    "/fed": "page consacrée à la Fed et à ses décisions",
    "/bce": "page consacrée à la BCE et à ses décisions",
    "/inflation": "page consacrée à l'inflation",
    "/indicateurs": "indicateurs économiques",
    "/marches": "vue des marchés (actions, devises, matières premières, crypto)",
    "/guide": "guides pour débuter",
    "/calculateur-taille-position": "calculateur de taille de position (gestion du risque)",
}

# Formulations interdites : promesses de gain ou incitations directes à l'achat / la vente.
FORBIDDEN = [
    r"rendements? garantis?", r"gains? garantis?", r"gains? assur[ée]s?", r"profits? assur[ée]s?",
    # « placement sans risque » est une promesse ; « aucun placement n'est sans risque » est un avertissement légitime.
    r"(placements?|investissements?|gains?|rendements?|profits?|strat[ée]gies?|trades?) (100 ?% )?sans (aucun )?risque",
    r"devenir riche", r"argent facile", r"enrichissez[- ]vous",
    r"achetez (d[eè]s )?maintenant", r"vendez (d[eè]s )?maintenant", r"il faut (absolument )?(acheter|vendre)",
    r"\b(achetez|vendez) (l'action|les actions|le titre)\b", r"\b100 ?% (s[uû]r|gagnant)",
    r"coup s[uû]r", r"\bne peut que monter\b",
]

COMMON_RULES = f"""RÈGLES DE RÉDACTION (toutes obligatoires)
- Longueur du corps : entre 800 et 1000 mots (jamais moins de {MIN_WORDS}, jamais plus de {MAX_WORDS}). Les sources et l'avertissement final comptent dans ce total.
- Méta-description : 140 caractères maximum, espaces compris.
- Titre accrocheur et précis qui contient le mot-clé principal mot pour mot.
- Intro courte (2 à 4 phrases) qui dit pourquoi le sujet compte pour le lecteur, puis au moins 3 sous-titres H2 (## ...). Pas de titre H1.
- Au moins une liste à puces ou numérotée. Un tableau Markdown quand il aide à comparer.
- Contenu précis et vérifiable : chiffres datés, mécanismes expliqués, exemples chiffrés. Aucun remplissage.
- Ton clair, direct, pédagogique, sans jargon non expliqué. Vouvoiement.
- N'invente jamais un chiffre, une date, une citation ou une décision. Utilise la recherche web pour tout fait récent ou chiffre susceptible d'avoir changé (taux, plafonds, fiscalité, cours). Si une information n'est pas confirmée, ne l'écris pas.

CADRE RÉGLEMENTAIRE (France, AMF) — strict
- Information générale et pédagogique uniquement. Jamais de conseil personnalisé, jamais de recommandation d'acheter ou de vendre un titre, une crypto ou une devise précise, jamais d'objectif de cours.
- Aucune promesse de gain ou de rendement. Rappelle les risques quand tu parles d'un placement ou d'une stratégie.
- Pas de ton sensationnaliste (« krach imminent », « opportunité unique »).

MOOVAPP (le site promu)
- Mentionne MoovApp exactement DEUX fois, toujours sous forme de lien Markdown vers une page de {SITE} :
  1) une fois dans le corps, là où c'est naturellement utile ;
  2) une fois dans la conclusion (dernière section H2).
- Choisis la page la plus pertinente parmi :
{chr(10).join(f"  - {SITE}{p} : {d}" for p, d in SITE_PAGES.items())}
- Présente MoovApp comme un outil pour suivre les marchés et l'actualité économique, jamais comme une source de gains. Ton naturel, jamais publicitaire. Aucune autre mention.

FIN DE L'ARTICLE (dans cet ordre, après la conclusion)
{{sources_rule}}
- Dernier paragraphe, en italique, exactement dans cet esprit : « *Cet article est fourni à titre d'information générale et ne constitue pas un conseil en investissement. Investir comporte un risque de perte en capital.* »

FORMAT DE SORTIE (strict). Ta réponse finale doit commencer directement par TITLE: et ne rien contenir après l'article :
TITLE: <titre>
KEYWORD: <mot-clé principal, 1 à 4 mots>
DESCRIPTION: <méta-description, 155 caractères maximum, avec le mot-clé>
TAGS: <3 à 5 tags en minuscules séparés par des virgules>
---
<corps de l'article en Markdown>"""

SOURCES_ACTU = "- Un paragraphe qui commence par « **Sources :** » suivi d'au moins 2 liens Markdown vers les articles ou publications officielles consultés (titre du média ou de l'institution + date)."
SOURCES_FOND = "- Si tu as utilisé des sources web, un paragraphe qui commence par « **Sources :** » avec leurs liens Markdown (facultatif)."

SYSTEM_PROMPT = (
    "Tu es journaliste économique et pédagogue pour « Actu Éco & Finance », un blog francophone qui décrypte "
    "l'actualité économique et les marchés financiers pour les particuliers (25-55 ans, curieux, pas forcément experts).\n\n"
)

TYPE_HINTS = {
    "explication": "Article « Comprendre » : définition simple, mécanisme expliqué pas à pas, exemple chiffré, ce que cela change concrètement pour le lecteur.",
    "guide": "Guide pratique : étapes numérotées, exemples chiffrés, erreurs à éviter, points de vigilance sur les risques.",
    "comparatif": "Comparatif : critères clairs (fonctionnement, frais, fiscalité, risque, liquidité), un tableau Markdown récapitulatif et une conclusion nuancée selon le profil, sans désigner de « meilleur » choix universel.",
    "liste": "Liste : éléments numérotés, chacun avec une explication concrète et un exemple.",
}


def actu_prompt(today: str, recent_titles: list[str]) -> str:
    avoid = "\n".join(f"  - {t}" for t in recent_titles) or "  (aucun)"
    return (
        f"Nous sommes le {today}. Rédige l'article d'actualité du jour.\n\n"
        "1. Fais des recherches web pour identifier LE sujet économique ou financier le plus important des 3 derniers jours "
        "pour un lecteur français : décision ou discours de banque centrale (BCE, Fed), inflation, emploi, croissance, "
        "taux, budget et dette, mouvement marquant des marchés (actions, obligations, devises, pétrole, or, crypto), "
        "résultats d'une grande entreprise.\n"
        f"Tu disposes de {MAX_SEARCHES['actu']} recherches web au maximum : fais des requêtes larges et utiles "
        "(ex. « actualité économique France cette semaine », « BCE décision », « marchés européens clôture »).\n"
        "2. Vérifie les faits et les chiffres dans au moins deux sources fiables et récentes "
        "(institutions officielles, INSEE, Eurostat, BCE, Fed, presse économique reconnue). Note la date de chaque chiffre.\n"
        "3. Écris l'article : ce qui s'est passé, pourquoi c'est arrivé, ce que ça change pour le lecteur (épargne, crédit, "
        "pouvoir d'achat, marchés), et les prochaines échéances à surveiller (avec leurs dates).\n\n"
        f"Sujets déjà traités récemment (ne les répète pas, sauf fait nouveau majeur) :\n{avoid}\n"
    )


def fond_prompt(topic: dict, today: str) -> str:
    return (
        f"Nous sommes le {today}. Rédige l'article suivant.\n"
        f"- Sujet / titre de travail : {topic['title']}\n"
        f"- Mot-clé principal : {topic['keyword']} (utilise-le tel quel sur la ligne KEYWORD)\n"
        f"- Intention de recherche : {topic['search_intent']}\n"
        f"- Type d'article : {TYPE_HINTS.get(topic['type'], '')}\n"
        "- Fais une ou deux recherches web pour vérifier les chiffres qui peuvent avoir changé (taux, plafonds, fiscalité, "
        "niveaux de marché). Ancre l'article dans le contexte économique actuel quand c'est pertinent.\n"
    )


# --------------------------------------------------------------------------- utils

def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def norm_words(text: str) -> list[str]:
    text = strip_accents(text.lower()).replace("œ", "oe").replace("’", "'")
    return re.findall(r"[a-z0-9]+", text)


def slugify(text: str, max_len: int = 70) -> str:
    slug = "-".join(norm_words(text))
    return slug[:max_len].rstrip("-") or "article"


def count_words(markdown: str) -> int:
    text = re.sub(r"\]\([^)]*\)", "]", markdown)
    return len(re.findall(r"\w+(?:['’-]\w+)*", text))


def load_topics() -> list[dict]:
    return json.loads(TOPICS_FILE.read_text(encoding="utf-8"))


def save_topics(topics: list[dict]) -> None:
    TOPICS_FILE.write_text(json.dumps(topics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def yaml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def posts() -> list[Path]:
    return sorted(p for p in POSTS_DIR.glob("*.md") if re.match(r"\d{4}-\d{2}-\d{2}-", p.name))


def front_matter(path: Path, key: str) -> str | None:
    m = re.search(rf"^{key}:\s*\"?(.*?)\"?\s*$", path.read_text(encoding="utf-8").split("\n---", 1)[0], flags=re.M)
    return m.group(1) if m else None


def latest_post_date() -> date | None:
    all_posts = posts()
    return date.fromisoformat(all_posts[-1].name[:10]) if all_posts else None


def next_mode() -> str:
    forced = os.environ.get("BLOG_MODE", "").strip().lower()
    if forced in ("actu", "fond"):
        return forced
    all_posts = posts()
    if not all_posts:
        return "actu"
    return "fond" if front_matter(all_posts[-1], "type") == "actu" else "actu"


# ------------------------------------------------------------------ génération API

def call_api(prompt: str, mode: str) -> str:
    import anthropic  # importé ici pour que --from-file fonctionne sans le SDK

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ERREUR : la variable d'environnement ANTHROPIC_API_KEY n'est pas définie.")

    client = anthropic.Anthropic()
    tools = [{
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": MAX_SEARCHES[mode],
        "user_location": {"type": "approximate", "country": "FR", "timezone": "Europe/Paris"},
    }]
    messages = [{"role": "user", "content": prompt}]
    system = SYSTEM_PROMPT + COMMON_RULES.replace("{sources_rule}", SOURCES_ACTU if mode == "actu" else SOURCES_FOND)
    texts, searches, tok_in, tok_out = [], 0, 0, 0

    for _ in range(MAX_CONTINUATIONS + 1):
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=32000,
            system=system,
            messages=messages,
            tools=tools,
            # Si le modèle refuse, l'API relance automatiquement la requête sur un modèle de repli.
            betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default", "output_config": {"effort": EFFORT}},
        ) as stream:
            message = stream.get_final_message()

        tok_in += message.usage.input_tokens
        tok_out += message.usage.output_tokens
        for block in message.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "server_tool_use" and block.name == "web_search":
                searches += 1

        if message.stop_reason == "pause_turn":  # recherche longue : on relance, le serveur reprend
            tools[0]["max_uses"] = max(0, MAX_SEARCHES[mode] - searches)
            messages = [messages[0], {"role": "assistant", "content": message.content}]
            continue
        if message.stop_reason == "refusal":
            raise ValueError("le modèle a refusé la requête")
        if message.stop_reason == "max_tokens":
            raise ValueError("réponse tronquée (max_tokens atteint)")
        break
    else:
        raise ValueError("trop de reprises (pause_turn)")

    print(f"  API : {MODEL}, {searches} recherche(s) web, {tok_in} tokens en entrée, {tok_out} en sortie")
    return "".join(texts)


# -------------------------------------------------------------------- validation

def parse_output(raw: str) -> dict:
    start = raw.rfind("TITLE:")
    if start == -1:
        raise ValueError("ligne TITLE: introuvable")
    raw = raw[start:].strip()
    raw = re.sub(r"\n```\s*$", "", raw)
    head, sep, body = raw.partition("\n---\n")
    if not sep:
        raise ValueError("séparateur '---' introuvable entre l'en-tête et le corps")
    fields = {}
    for line in head.splitlines():
        m = re.match(r"^(TITLE|KEYWORD|DESCRIPTION|TAGS)\s*:\s*(.+)$", line.strip())
        if m:
            fields[m.group(1)] = m.group(2).strip().strip('"')
    missing = {"TITLE", "KEYWORD", "DESCRIPTION", "TAGS"} - fields.keys()
    if missing:
        raise ValueError(f"champs manquants dans l'en-tête : {', '.join(sorted(missing))}")
    tags = [t.strip().lower() for t in fields["TAGS"].split(",") if t.strip()]
    desc = fields["DESCRIPTION"]
    if len(desc) > MAX_DESCRIPTION:  # raccourcit proprement au dernier mot entier plutôt que de tout rejeter
        desc = desc[:MAX_DESCRIPTION - 1].rsplit(" ", 1)[0].rstrip(" ,;:.-–") + "…"
    return {"title": fields["TITLE"], "keyword": fields["KEYWORD"], "description": desc,
            "tags": tags, "body": body.strip()}


def validate(article: dict, mode: str, topic: dict | None) -> list[str]:
    errors = []
    title, desc, tags, body = article["title"], article["description"], article["tags"], article["body"]
    keyword = topic["keyword"] if topic else article["keyword"]

    title_words = set(norm_words(title))
    missing_kw = [w for w in norm_words(keyword) if len(w) > 2 and w not in title_words]
    if missing_kw:
        errors.append(f"le titre ne contient pas le mot-clé « {keyword} » (manque : {', '.join(missing_kw)})")
    if not (20 <= len(title) <= 120):
        errors.append(f"titre de longueur anormale ({len(title)} caractères)")
    if not (50 <= len(desc) <= MAX_DESCRIPTION):
        errors.append(f"description de {len(desc)} caractères (attendu : 50 à {MAX_DESCRIPTION})")
    if not (2 <= len(tags) <= 6):
        errors.append(f"{len(tags)} tags (attendu : 2 à 6)")

    words = count_words(body)
    if not (MIN_WORDS <= words <= MAX_WORDS):
        errors.append(f"{words} mots (attendu : {MIN_WORDS} à {MAX_WORDS})")

    if re.search(r"^#\s", body, flags=re.M):
        errors.append("le corps contient un titre H1")
    h2 = [m.start() for m in re.finditer(r"^##\s+\S", body, flags=re.M)]
    if len(h2) < 3:
        errors.append(f"{len(h2)} sous-titres H2 (minimum 3)")
    if not re.search(r"^\s*(?:[-*]|\d+\.)\s+\S", body, flags=re.M):
        errors.append("aucune liste dans l'article")

    links = [m.start() for m in re.finditer(r"\]\(https?://(?:www\.)?moovapp\.org[^)]*\)", body)]
    mentions = len(re.findall(r"moovapp", body, flags=re.I))
    if len(links) != 2:
        errors.append(f"{len(links)} lien(s) vers moovapp.org (attendu : exactement 2)")
    elif h2 and not (links[0] < h2[-1] < links[1]):
        errors.append("il faut un lien MoovApp dans le corps et un dans la conclusion (dernière section)")
    if mentions > 2 * max(len(links), 1):
        errors.append("MoovApp est mentionné en dehors des deux liens prévus")

    sources = re.search(r"\*\*Sources\s*:\*\*(.*)", body)
    ext_links = re.findall(r"\]\((https?://(?!(?:www\.)?moovapp\.org)[^)]+)\)", sources.group(1)) if sources else []
    if mode == "actu" and len(ext_links) < 2:
        errors.append(f"{len(ext_links)} source(s) citée(s) dans le paragraphe **Sources :** (minimum 2 pour l'actualité)")

    tail = strip_accents(body[-500:].lower())
    if "conseil en investissement" not in tail or "perte en capital" not in tail:
        errors.append("avertissement final manquant (conseil en investissement / risque de perte en capital)")

    plain = strip_accents(body.lower())
    for pattern in FORBIDDEN:
        m = re.search(strip_accents(pattern), plain)
        if m:
            errors.append(f"formulation interdite détectée : « {m.group(0)} »")

    if "```" in body:
        errors.append("bloc de code inattendu dans l'article")
    return errors


# -------------------------------------------------------------------- écriture

def render_post(article: dict, post_type: str, now: datetime) -> str:
    tags = ", ".join(yaml_str(t) for t in article["tags"])
    return (
        "---\n"
        "layout: post\n"
        f"type: {post_type}\n"
        f"title: {yaml_str(article['title'])}\n"
        f"date: {now.strftime('%Y-%m-%d %H:%M:%S %z')}\n"
        f"description: {yaml_str(article['description'])}\n"
        f"tags: [{tags}]\n"
        "---\n\n"
        f"{article['body']}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--from-file", type=Path)
    parser.add_argument("--not-before", type=int, default=None, metavar="HOUR")
    args = parser.parse_args()

    now = datetime.now(TZ).replace(microsecond=0)
    today = now.strftime("%Y-%m-%d")

    if args.not_before is not None and now.hour < args.not_before:
        print(f"Il est {now:%H:%M} à Paris, avant {args.not_before}h : rien à faire pour l'instant.")
        return 0
    last = latest_post_date()
    if not args.dry_run and last and (now.date() - last).days < INTERVAL_DAYS:
        next_day = last + timedelta(days=INTERVAL_DAYS)
        print(f"Dernier article le {last:%d/%m/%Y} ; prochain prévu le {next_day:%d/%m/%Y} : rien à faire.")
        return 0

    mode = next_mode()
    topics = load_topics()
    topic = None
    if mode == "actu":
        recent = [front_matter(p, "title") or p.stem for p in posts()[-10:]]
        prompt = actu_prompt(now.strftime("%d/%m/%Y"), recent)
        print("Article d'actualité (sujet choisi par recherche web)")
    else:
        topic = next((t for t in topics if not t.get("published")), None)
        if topic is None:
            print("ERREUR : tous les sujets de fond de topics.json ont été publiés. Ajoutez-en de nouveaux.")
            return 1
        prompt = fond_prompt(topic, now.strftime("%d/%m/%Y"))
        print(f"Article de fond, sujet n°{topic['id']} : {topic['title']} [{topic['type']}]")

    article, errors = None, []
    attempts = 1 if args.from_file else MAX_ATTEMPTS
    for attempt in range(1, attempts + 1):
        attempt_prompt = prompt
        if errors:  # le second essai sait pourquoi le premier a été refusé
            attempt_prompt += ("\nUne première version a été refusée par le contrôle automatique pour ces raisons, "
                               "corrige-les :\n" + "\n".join(f"- {e}" for e in errors) + "\n")
        try:
            raw = args.from_file.read_text(encoding="utf-8") if args.from_file else call_api(attempt_prompt, mode)
            article = parse_output(raw)
            errors = validate(article, mode, topic)
        except Exception as exc:  # erreur API ou format illisible
            errors = [str(exc)]
        if not errors:
            break
        print(f"  Essai {attempt}/{attempts} rejeté :")
        for e in errors:
            print(f"    - {e}")

    if errors:
        print("ÉCHEC : l'article ne respecte pas les règles. Rien n'est publié.")
        return 1

    post_type = "actu" if mode == "actu" else topic["type"]
    content = render_post(article, post_type, now)
    filename = f"{today}-{slugify(article['title'])}.md"
    print(f"  OK : « {article['title']} », {count_words(article['body'])} mots, "
          f"{len(article['description'])} car. de description")

    if args.dry_run:
        PREVIEW_DIR.mkdir(exist_ok=True)
        out = PREVIEW_DIR / filename
        out.write_text(content, encoding="utf-8")
        print(f"[dry-run] Aperçu écrit dans {out.relative_to(ROOT)} (topics.json inchangé)")
        return 0

    (POSTS_DIR / filename).write_text(content, encoding="utf-8")
    if topic is not None:
        topic["published"] = today
        topic["post"] = filename
        save_topics(topics)
    print(f"Publié : _posts/{filename}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
