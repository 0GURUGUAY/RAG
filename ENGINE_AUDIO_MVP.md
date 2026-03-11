# CEIBO – MVP détection acoustique moteur (iPad)

## Objectif
Détecter tôt des dérives de comportement moteur en combinant:
- snapshots audio courts,
- contexte navigation/moteur,
- score d’anomalie vs baseline.

## Stratégie MVP
- Ne pas enregistrer en continu.
- Capturer des fenêtres de 10–20 s toutes les 2–5 min moteur ON.
- Sauvegarder surtout les features + score, et l’audio seulement en cas d’alerte.

## Pipeline recommandé
1. Capture iPad (micro fixe près moteur, gain constant).
2. Pré-traitement local:
   - normalisation niveau,
   - filtre bande utile moteur,
   - suppression segments silence.
3. Features:
   - RMS,
   - centroid/rolloff,
   - ZCR,
   - MFCC,
   - énergies de bandes.
4. Contexte joint:
   - heures moteur,
   - RPM (si dispo),
   - vitesse, gîte, vent, mer.
5. Scoring:
   - baseline par régime (idle/cruise/high),
   - score distance baseline,
   - niveau: normal/watch/alert/critical.

## Baseline pragmatique
- 3 profils initiaux: `idle`, `cruise`, `high`.
- Apprentissage initial sur 3 à 5 sorties sans incident.
- Exclure les conditions extrêmes (vent/mer très forts) du modèle de référence principal.

## Règles d’alerte MVP
- `watch`: score > seuil_1 sur 3 snapshots consécutifs.
- `alert`: score > seuil_2 sur 2 snapshots consécutifs.
- `critical`: score > seuil_3 ou dérive brutale + montée vibration.

## UX CEIBO minimal
- Bouton ON/OFF: “Surveillance son moteur”.
- Statut live: dernier score + niveau.
- Historique: liste des anomalies avec timestamp et raisons.
- Filtre: `watch+`.

## Schéma SQL
Migration prête: `supabase/sql/engine_sound_snapshots_schema.sql`.

## Intégration CEIBO (ordre conseillé)
1. Appliquer migration SQL.
2. Ajouter push/pull cloud (table `engine_sound_snapshots`).
3. Ajouter service capture/analyse iPad.
4. Ajouter panneau UI minimal dans onglet moteur/log.
5. Ajuster seuils après 1–2 semaines de navigation réelle.

## Conseils terrain
- Position micro fixe et répétable > précision absolue du modèle.
- Marquer les événements maintenance (vidange, courroie, hélice) pour interpréter les ruptures de série.
- Garder un mode dégradé hors réseau: stockage local puis synchro cloud.
