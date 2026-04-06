# Test banc Teensy -> faux SignalK -> CEIBO

Ce test ne dépend ni de l'AMT1001 ni du joystick câblé. Il sert à vérifier toute la chaîne de communication avant soudure:

1. Teensy 4.0 envoie un JSON aléatoire sur l'USB série.
2. Le Raspberry Pi lit ce JSON.
3. Le Pi expose un faux flux SignalK compatible avec `signalk.js`.
4. CEIBO se connecte à ce flux et doit afficher température + humidité qui bougent.

## 1. Charger le sketch Teensy

Sketch à flasher:

- `arduino/ceibo_fake_signalk_bench/ceibo_fake_signalk_bench.ino`

Réglages conseillés dans l'IDE Teensy:

- Board: `Teensy 4.0`
- USB Type: `Serial`
- Speed: `600 MHz` ou défaut

Le sketch envoie une ligne JSON par seconde, par exemple:

```json
{"device":"ceibo-teensy4-fake","sensor":"bench-simulator","frame":12,"uptime_ms":12034,"vref":3.30,"temperature_c":22.41,"humidity_pct":63.18,"joystick":{"x":731,"y":198,"button":0}}
```

## 2. Installer les dépendances sur le Pi

```bash
python3 -m pip install -r arduino/requirements-signalk-bench.txt
```

## 3. Lancer le faux serveur SignalK

Exemple Linux / Raspberry Pi:

```bash
python3 arduino/ceibo_fake_signalk_bridge.py --serial-port /dev/ttyACM0
```

Exemple macOS:

```bash
python3 arduino/ceibo_fake_signalk_bridge.py --serial-port /dev/cu.usbmodem98474801
```

Le bridge expose:

- `ws://<host>:3000/signalk/v1/stream`
- `http://<host>:3000/signalk`
- `http://<host>:3000/signalk/v1/api/`

Attention:

- `'/signalk/v1/stream'` est un endpoint WebSocket. Ne l'ouvre pas directement dans un navigateur.
- Si tu vois un message du type `You cannot access a WebSocket server directly with a browser`, c'est normal pour ce chemin.
- Pour un test navigateur, ouvre `http://<host>:3000/signalk` ou `http://<host>:3000/signalk/v1/api/`.

Chemins émis:

- `environment.outside.temperature`
- `environment.weather.temperature`
- `environment.outside.relativeHumidity`
- `environment.weather.relativeHumidity`

Les températures sont envoyées en Kelvin et l'humidité en ratio 0..1, donc dans le format attendu par SignalK.

## 4. Pointer CEIBO vers le faux flux

Dans CEIBO:

1. Ouvre le panneau SignalK.
2. Saisis l'IP ou le hostname du Pi.
3. Laisse le port implicite `3000`.
4. Clique `Tester la connexion` ou connecte-toi en mode SignalK.

Si tout est correct, CEIBO doit commencer à recevoir des mises à jour toutes les secondes.

## 5. Vérifications rapides

Dans un terminal sur le Pi:

```bash
curl http://127.0.0.1:3000/signalk
curl http://127.0.0.1:3000/signalk/v1/api/
```

Tu dois voir la discovery SignalK puis un snapshot minimal avec les branches `environment.outside` et `environment.weather`.

Dans les logs du bridge, tu dois voir passer les frames série avec température et humidité.

## 6. Ce que valide ce test

- USB série Teensy <-> Raspberry Pi
- Décodage JSON côté Pi
- Compatibilité protocole SignalK côté CEIBO
- Chemins météo utiles déjà consommés par `signalk.js`

## 7. Ce que ce test ne valide pas

- la calibration réelle de l'AMT1001
- le câblage analogique du joystick
- l'injection dans un vrai `signalk-server-node`

Pour le banc, c'est volontaire: on isole la couche transport avant de souder les entrées analogiques réelles.