# Actu Éco & Finance

Blog Jekyll hébergé sur GitHub Pages. Tous les 2 jours à 8h (heure de Paris), GitHub Actions publie un article rédigé par l'API Anthropic. Chaque article renvoie vers [MoovApp](https://www.moovapp.org).

Site : https://looprun-lab.github.io/actu-eco-finance/

## Deux types d'articles, en alternance

| Type | Sujet | Recherche web |
|---|---|---|
| Actualité | Le sujet économique ou financier marquant des 3 derniers jours, choisi par le modèle | Oui : au moins 2 sources citées en fin d'article |
| Fond | Le prochain sujet de `scripts/topics.json` (60 sujets SEO : inflation, BCE, ETF, PEA…) | Oui : pour vérifier les chiffres qui changent (taux, plafonds, fiscalité) |

## Contenu du repo

| Fichier | Rôle |
|---|---|
| `scripts/generate_post.py` | Choisit le type d'article, appelle l'API avec la recherche web, vérifie l'article, l'écrit |
| `scripts/topics.json` | Les 60 sujets de fond ; `published` est rempli quand un sujet est publié |
| `.github/workflows/daily-post.yml` | Vérification quotidienne (publication tous les 2 jours) + lancement manuel |
| `_data/moovapp.yml` | Textes des bannières MoovApp (modifiables sans toucher au code) |
| `_layouts/`, `_includes/`, `assets/css/blog.css` | Design du site |
| `_config.yml`, `index.md`, `about.md` | Configuration, accueil, page « À propos » avec l'avertissement sur les risques |

## Contrôles avant publication

Le script refuse de publier (et le workflow échoue, sans commit) si l'article :
- ne fait pas entre 700 et 1 100 mots, n'a pas au moins 3 sous-titres H2 et une liste, ou si le mot-clé n'est pas dans le titre ;
- n'a pas exactement 2 liens vers moovapp.org (un dans le corps, un dans la conclusion) ;
- est un article d'actualité avec moins de 2 sources ;
- ne se termine pas par l'avertissement « ne constitue pas un conseil en investissement… risque de perte en capital » ;
- contient une formulation interdite : promesse de gain (« rendement garanti », « sans risque », « devenir riche »…) ou incitation directe (« il faut acheter », « achetez maintenant »…).

En cas d'échec, le script fait un second essai avant d'abandonner. GitHub vous prévient alors par e-mail.

## Réglages (Settings → Secrets and variables → Actions)

- Secret `ANTHROPIC_API_KEY` : obligatoire.
- Variables facultatives :
  - `BLOG_INTERVAL_DAYS` : jours entre deux articles (`2` par défaut) ;
  - `BLOG_MODEL` : `claude-opus-5-5` par défaut ;
  - `BLOG_EFFORT` : `low`, `medium` (défaut) ou `high`.

Pour forcer le type du prochain article lors d'un test local : `BLOG_MODE=actu` ou `BLOG_MODE=fond`.

## Tester en local

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...        # dans votre terminal, jamais dans un fichier commité
python3 scripts/generate_post.py --dry-run
```
`--dry-run` écrit l'aperçu dans `_preview/` (ignoré par git) sans toucher à `_posts/` ni à `topics.json`. `--from-file mon-article.txt` vérifie un texte déjà rédigé sans appeler l'API.

## Coût indicatif

Le premier coût vient des résultats de recherche web, relus en entrée par le modèle. Les recherches sont plafonnées à 4 par article d'actualité et 2 par article de fond (variables `BLOG_MAX_SEARCHES_ACTU` et `BLOG_MAX_SEARCHES_FOND`). Comptez environ 0,30 à 0,60 $ par article d'actualité et 0,15 à 0,30 $ par article de fond avec Claude Opus 5.5, soit environ 3 à 7 $ par mois à raison de 15 articles. Le coût réel de chaque article (recherches et tokens) est affiché dans le log du workflow. GitHub Pages et GitHub Actions sont gratuits pour un repo public.
