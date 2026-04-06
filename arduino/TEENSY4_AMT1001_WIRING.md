# Cablage Teensy 4.0 + AMT1001 + joystick

## Objectif

Brancher sur une Teensy 4.0:

- un capteur AMT1001
- un joystick analogique type KY-023
- une liaison USB vers le Raspberry Pi 3

## Regle de securite la plus importante

Les entrees analogiques de la Teensy 4.0 sont en `3.3V max`.

Donc:

- ne jamais envoyer une sortie analogique 5V directement sur `A0`, `A1`, `A2` ou `A3`
- le joystick doit etre alimente en `3.3V`
- les sorties analogiques de l'AMT1001 doivent passer par un diviseur resistif avant d'entrer dans la Teensy si le module est alimente en 5V

## Composants recommandes

- 2 resistances `20k`
- 2 resistances `10k`
- fils Dupont
- breadboard

Les couples `20k + 10k` servent a ramener une sortie max de `5V` vers environ:

$$
V_{out} = V_{in} \times \frac{10}{20 + 10} = 0.333 \times V_{in}
$$

Donc pour `5V` en entree, on obtient environ `3.33V`, ce qui est compatible avec la Teensy.

## Broches Teensy 4.0 utilisees

- `VIN` ou `5V` logique capteur: alimentation AMT1001
- `3.3V`: alimentation joystick
- `GND`: masse commune
- `A0`: humidite AMT1001 apres diviseur
- `A1`: temperature AMT1001 apres diviseur
- `A2`: axe X joystick
- `A3`: axe Y joystick
- `D4`: bouton joystick
- `USB`: liaison serie vers RPi3

Repere pratique courant sur Teensy 4.0:

- `A0` correspond generalement a la broche `14`
- `A1` correspond generalement a la broche `15`
- `A2` correspond generalement a la broche `16`
- `A3` correspond generalement a la broche `17`

## Cablage exact

### 1. Masse commune

Relier ensemble:

- `GND` Teensy
- `GND` AMT1001
- `GND` joystick
- les resistances du bas des deux diviseurs

Sans cette masse commune, les lectures analogiques seront fausses.

### 2. AMT1001 alimentation

- `VCC` AMT1001 -> `VIN / 5V` Teensy
- `GND` AMT1001 -> `GND` Teensy

### 3. AMT1001 humidite vers A0

Faire ce montage:

- `OUT humidite AMT1001` -> resistance `20k` -> noeud milieu
- noeud milieu -> `A0` Teensy
- noeud milieu -> resistance `10k` -> `GND`

Schema texte:

```text
OUT humidite ---- 20k ----+---- A0 Teensy
                          |
                         10k
                          |
                         GND
```

### 4. AMT1001 temperature vers A1

Si ta breakout AMT1001 fournit deja une sortie analogique temperature exploitable:

- `OUT temperature / NTC module` -> resistance `20k` -> noeud milieu
- noeud milieu -> `A1` Teensy
- noeud milieu -> resistance `10k` -> `GND`

Schema texte:

```text
OUT temperature -- 20k ----+---- A1 Teensy
                           |
                          10k
                           |
                          GND
```

Si ta carte n'expose que la NTC brute, ce schema ne suffira pas a lui seul. Dans ce cas, il faut faire un pont de mesure autour de la thermistance. Le sketch actuel part de l'hypothese qu'une tension analogique temperature existe deja.

### 5. Joystick

- `VCC joystick` -> `3.3V` Teensy
- `GND joystick` -> `GND` Teensy
- `VRx joystick` -> `A2` Teensy
- `VRy joystick` -> `A3` Teensy
- `SW joystick` -> `D4` Teensy

Le bouton `SW` fonctionne avec `INPUT_PULLUP` dans le sketch, donc aucun composant externe n'est necessaire pour ce bouton.

### 6. USB vers Raspberry Pi 3

- `USB` Teensy -> `USB` RPi3

Le Raspberry Pi verra ensuite un port serie USB du type:

- `/dev/ttyACM0`
- ou `/dev/ttyACM1`

## Tableau broche par broche

| Fonction | Module | Vers Teensy 4.0 | Remarque |
|---|---|---|---|
| Alim capteur | `VCC` AMT1001 | `VIN / 5V` | pas vers `3.3V` sans verifier la breakout |
| Masse capteur | `GND` AMT1001 | `GND` | masse commune |
| Humidite | `OUT humidity` | `A0` via `20k/10k` | diviseur obligatoire si sortie 5V |
| Temperature | `OUT temp/NTC` | `A1` via `20k/10k` | seulement si sortie analogique deja conditionnee |
| Alim joystick | `VCC` joystick | `3.3V` | direct, sans diviseur |
| Masse joystick | `GND` joystick | `GND` | masse commune |
| Axe X joystick | `VRx` | `A2` | direct |
| Axe Y joystick | `VRy` | `A3` | direct |
| Bouton joystick | `SW` | `D4` | direct |
| Liaison RPi3 | `USB` Teensy | `USB` RPi3 | serial JSON |

## Verifications avant mise sous tension

1. Verifier que le joystick est bien alimente en `3.3V`, pas en `5V`.
2. Verifier que les sorties analogiques AMT1001 passent bien par le diviseur `20k/10k` avant `A0` et `A1`.
3. Verifier que toutes les masses sont reliees.
4. Verifier qu'aucune sortie capteur 5V n'entre directement dans une entree analogique de la Teensy.

## Test pratique conseille

1. Brancher d'abord seulement le joystick.
2. Televerser le sketch `ceibo_amt1001_joystick.ino`.
3. Verifier que les axes joystick bougent correctement dans le JSON serie.
4. Ajouter ensuite l'humidite AMT1001 sur `A0` via le diviseur.
5. Ajouter enfin la temperature AMT1001 sur `A1` via le diviseur.

## Cas de panne classique

### Humidite toujours a 0 ou 100

- diviseur mal cable
- mauvaise broche de sortie AMT1001
- masse non commune

### Temperature a `null`

- pas de vraie sortie analogique temperature sur la breakout
- NTC brute non conditionnee
- tension hors plage ou cablage incorrect sur `A1`

### Valeurs joystick incoherentes

- joystick alimente en `5V` au lieu de `3.3V`
- inversion `VRx` / `VRy`
- masse flottante

## Fichier de code associe

Le cablage ci-dessus correspond au sketch:

- `arduino/ceibo_amt1001_joystick/ceibo_amt1001_joystick.ino`