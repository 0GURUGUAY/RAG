# Arduino capteur CEIBO

Ce dossier contient deux bases simples pour brancher une carte compatible Arduino au RPi3 avec:

- soit une sonde température / humidité DHT22
- soit une sonde AMT1001
- un joystick analogique type KY-023
- un lien USB série vers le Raspberry Pi

## 1. Hypothèse matérielle

Sketch DHT22:

- Arduino Uno / Nano ou Teensy 4.0
- DHT22
- joystick analogique 2 axes + bouton poussoir

Fichier:

- `arduino/ceibo_env_joystick/ceibo_env_joystick.ino`

Si ta sonde n'est pas une DHT22 mais une DHT11, il suffit de remplacer `DHT22` par `DHT11` dans le sketch.

Sketch AMT1001:

- Arduino Uno / Nano ou Teensy 4.0
- AMT1001 sortie humidité analogique + NTC température
- joystick analogique 2 axes + bouton poussoir

Fichier:

- `arduino/ceibo_amt1001_joystick/ceibo_amt1001_joystick.ino`

Remarque importante:

- l'AMT1001 n'est pas un remplaçant direct d'une DHT22
- l'humidité est généralement simple à lire en analogique
- la température dépend du câblage de la broche NTC et parfois d'un pont diviseur externe

### Cas particulier Teensy 4.0

Sur Teensy 4.0, les entrées analogiques sont en `3.3V max`.

Conséquence directe:

- ne jamais envoyer un signal analogique 5V directement vers `A0/A1/A2/A3`
- le joystick doit être alimenté en `3.3V`
- l'AMT1001 doit être validé avec précaution selon sa breakout

Règle simple:

- si la sortie du capteur peut dépasser `3.3V`, il faut un diviseur résistif avant l'entrée analogique du Teensy

## 2. Câblage Arduino

### Option A — DHT22

#### DHT22

- `VCC` -> `5V` Arduino
- `GND` -> `GND` Arduino
- `DATA` -> `D2` Arduino
- résistance `10k` entre `DATA` et `VCC`

### Option B — AMT1001

Le cas le plus courant pour l'AMT1001 est:

- une sortie humidité analogique
- une sortie NTC pour la température

Branchement conseillé avec le sketch fourni:

- `VCC` AMT1001 -> `5V` Arduino
- `GND` AMT1001 -> `GND` Arduino
- `OUT humidité` -> `A0`
- `NTC température` -> `A1`

Si tu es sur Teensy 4.0:

- ne relie pas directement une sortie AMT1001 5V au Teensy
- intercale un diviseur résistif sur chaque sortie analogique lue par le Teensy
- exemple simple: `20k` côté capteur et `10k` côté GND pour ramener `5V` vers environ `3.3V`

Chaîne recommandée sur Teensy:

- `OUT humidité AMT1001` -> `20k` -> nœud -> `A0`
- nœud -> `10k` -> `GND`
- `NTC température sortie analogique` -> `20k` -> nœud -> `A1`
- nœud -> `10k` -> `GND`

Point critique:

- si ta carte AMT1001 expose la NTC brute, il faut souvent un pont diviseur `10k` avec `5V`
- si ta breakout intègre déjà ce pont, la sortie NTC peut aller directement sur `A1`
- sur Teensy, même dans ce cas, il faut encore vérifier que la tension reste sous `3.3V`

En pratique:

- si tu branches l'humidité et que la température remonte `null`, c'est souvent la partie NTC qu'il faut ajuster
- l'humidité restera généralement exploitable beaucoup plus vite que la température

### Joystick analogique

- `VCC` -> `5V` sur Uno/Nano, ou `3.3V` sur Teensy 4.0
- `GND` -> `GND` Arduino
- `VRx` -> `A2` avec le sketch AMT1001, ou `A0` avec le sketch DHT22
- `VRy` -> `A3` avec le sketch AMT1001, ou `A1` avec le sketch DHT22
- `SW` -> `D4`

Pour Teensy 4.0:

- alimente le joystick en `3.3V`
- ainsi `VRx` et `VRy` resteront naturellement dans la plage sûre pour les entrées analogiques

## 3. Liaison avec le Raspberry Pi 3

La solution la plus simple et la plus sûre est:

- brancher les capteurs sur l'Arduino
- brancher l'Arduino au RPi3 uniquement par USB

Avantages:

- pas de problème de niveaux logiques entre la carte microcontrôleur et le Raspberry Pi côté USB
- port série disponible immédiatement sur le Pi
- alimentation et données sur un seul câble

Sur le Raspberry Pi, l'Arduino apparaîtra en général comme:

- `/dev/ttyACM0`
- ou `/dev/ttyUSB0`

## 4. Format des données envoyées

Le sketch envoie une ligne JSON par seconde, par exemple:

```json
{"device":"ceibo-arduino","temperature_c":23.4,"humidity_pct":57.8,"joystick":{"x":0,"y":92,"pressed":false,"direction":"up"},"ts_ms":12540}
```

Version AMT1001 typique:

```json
{"device":"ceibo-arduino","sensor":"amt1001","temperature_c":24.1,"humidity_pct":61.3,"joystick":{"x":0,"y":0,"pressed":false,"direction":"center"},"raw":{"humidity_adc":612,"temperature_adc":544},"ts_ms":12540}
```

Quand le bouton du joystick change d'état, un événement immédiat est aussi envoyé avec `"button_event": true`.

## 5. Test rapide sur le Raspberry Pi

Lister le port:

```bash
ls /dev/ttyACM* /dev/ttyUSB*
```

Lire le flux série:

```bash
stty -F /dev/ttyACM0 115200
cat /dev/ttyACM0
```

Pour éviter les changements de nom de port au reboot, tu peux créer un alias stable:

Identifier d'abord l'Arduino:

```bash
udevadm info -a -n /dev/ttyACM0 | grep -E 'idVendor|idProduct|serial' | head
```

Créer ensuite une règle `udev`:

```bash
sudo nano /etc/udev/rules.d/99-ceibo-arduino.rules
```

Exemple de contenu:

```text
SUBSYSTEM=="tty", ATTRS{idVendor}=="2341", ATTRS{idProduct}=="0043", SYMLINK+="ceibo-arduino"
```

Puis recharger:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
ls -l /dev/ceibo-arduino
```

## 6. Intégration conseillée avec CEIBO

Deux options propres:

### Option A — rapide

Lire le port série avec un petit script Python sur le RPi3 et pousser les valeurs vers CEIBO ou vers un fichier local.

### Option B — durable

Publier les données dans SignalK, par exemple:

- `environment.outside.temperature`
- `environment.outside.relativeHumidity`

CEIBO sait déjà écouter ces chemins via `signalk.js`.

## 7. Librairie Arduino requise

Pour le sketch DHT22, installer:

- `DHT sensor library` par Adafruit
- `Adafruit Unified Sensor`

Pour le sketch AMT1001, aucune librairie externe n'est nécessaire.

Sur Teensy 4.0, le sketch fixe explicitement `analogReadResolution(10)` pour garder la même échelle ADC que sur Uno/Nano.

## 8. Remarque importante

Ne branche pas directement un joystick alimenté en 5V sur les GPIO du Raspberry Pi. Si tu veux absolument câbler le joystick sur le Pi, il faut un convertisseur ADC et il faut vérifier les niveaux logiques. Avec l'Arduino en USB, ce risque disparaît.

Pour l'AMT1001, le vrai risque n'est pas logiciel mais matériel: selon la breakout, la broche température peut nécessiter une petite adaptation du pont diviseur.

Sur Teensy 4.0, il y a un deuxième risque: la surtension analogique. Si tu veux, je peux maintenant te préparer:

- un schéma de câblage Teensy 4.0 ultra concret avec les résistances exactes
- le mini script Python RPi3 qui lit le JSON série
- un mode calibration pour vérifier immédiatement si l'AMT1001 sort une tension correcte

## 9. Test sur banc avant soudure

Pour valider la chaîne `Teensy -> USB série -> Raspberry Pi -> flux SignalK -> CEIBO` sans brancher la sonde ni le joystick réels, il y a maintenant une solution dédiée:

- sketch Teensy: `arduino/ceibo_fake_signalk_bench/ceibo_fake_signalk_bench.ino`
- bridge Python: `arduino/ceibo_fake_signalk_bridge.py`
- dépendances Python: `arduino/requirements-signalk-bench.txt`
- procédure complète: `arduino/CEIBO_FAKE_SIGNALK_TEST.md`

Cette variante n'écrit pas dans un vrai serveur SignalK. Elle expose à la place un faux endpoint SignalK minimal compatible avec `signalk.js`, ce qui est suffisant pour vérifier la communication de bout en bout côté CEIBO avant soudure.