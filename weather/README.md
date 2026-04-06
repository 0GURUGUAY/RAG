# Analyse météo locale CEIBO

## Objectif

Ajouter un moteur d'analyse météo plus explicatif que la simple prévision point par point.

Le service combine:
- prévisions horaires Open-Meteo;
- climatologie historique Open-Meteo Archive;
- diagnostics vectoriels via Pandas + MetPy;
- lecture régionale simplifiée pour expliquer un flux local.

## Installation

L'environnement CEIBO contient déjà l'essentiel. Si nécessaire:

```bash
source .venv/bin/activate
pip install -r weather/requirements.txt
```

## Lancer le serveur

```bash
python weather/server.py --host 127.0.0.1 --port 8777
```

Puis, dans l'onglet météo de CEIBO, cliquer sur `Analyse synoptique locale`.

## Ce que le service explique

- pourquoi le vent observé est plausible à l'endroit courant;
- si le régime paraît stable, frontal, thermique ou lié à un gradient régional;
- comment la situation évolue sur 2 à 7 jours;
- si la semaine à venir est anormale par rapport aux mêmes dates passées;
- si un signal atlantique lointain est compatible avec une propagation vers l'est.

## Limites

- le service reste un diagnostic local/régional, pas un modèle NWP complet;
- il ne prouve pas la causalité exacte d'une dépression canadienne sur Barcelone;
- il qualifie une compatibilité synoptique, avec niveau de confiance explicite.