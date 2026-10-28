# greenscreen-batch

Werkzeuge, mit denen sich hunderte Greenscreen-Fotos automatisch freistellen und von grünen Reflexen (Green Spill) befreien lassen. Entstanden für Team- und Portrait-Shootings vor einem grünen Hintergrund, wo das grüne Licht auf Haare, Haut, Schmuck und weiße Trikots zurückfällt.

**Ergebnis:** PNGs mit transparentem Hintergrund und natürlichen Farben an Haaren und Hautkanten. Das eingebettete Farbprofil bleibt dabei erhalten.

## Inhalt

| Datei | Zweck |
| --- | --- |
| [`gruen_entfernen.py`](gruen_entfernen.py) | **Hauptwerkzeug.** Entfernt grüne Reflexe aus bereits freigestellten PNGs, zum Beispiel aus Photoshop. Die Transparenz bleibt unverändert. |
| [`photoshop/png_speichern_tiff_loeschen.jsx`](photoshop/png_speichern_tiff_loeschen.jsx) | Photoshop-Script für die Aktion: speichert das freigestellte Bild als PNG, löscht danach das Quell-TIFF und leert den Speicher. |
| [`greenscreen_freistellen.py`](greenscreen_freistellen.py) | Alternative ohne Photoshop: stellt selbst per Chroma-Key frei, entfernt den Spill und gleicht die Belichtung über die Serie an. |
| [`docs/photoshop.md`](docs/photoshop.md) | Einrichtung von Photoshop, Aufbau der Aktion, Stapelverarbeitung und Tipps für bessere Freistellungen |
| [`docs/funktionsweise.md`](docs/funktionsweise.md) | Was die Scripts technisch machen und welche Parameter man anpassen kann |

## Empfohlener Workflow

```
Lightroom ──► TIFF-Export ──► Photoshop-Stapel ──► gruen_entfernen.py ──► fertige PNGs
              (16 Bit, sRGB)   „Hintergrund entfernen“  (Spill-Korrektur)
                               + PNG speichern
                               + TIFF löschen
```

1. **Lightroom:** Bilder entwickeln und als TIFF exportieren (16 Bit, sRGB, volle Auflösung). Grün dabei **nicht** entsättigen, das übernimmt später das Script. Details in [docs/photoshop.md](docs/photoshop.md#1-export-aus-lightroom).
2. **Photoshop:** Die Aktion „Hintergrund entfernen + `png_speichern_tiff_loeschen.jsx`“ per *Datei → Automatisieren → Stapelverarbeitung* über den TIFF-Ordner laufen lassen. Die PNGs landen im Unterordner `photoshop/`. Einrichtung siehe [docs/photoshop.md](docs/photoshop.md).
3. **Spill entfernen:** `gruen_entfernen.py` über den Ordner `photoshop/` laufen lassen. Die fertigen Bilder landen in `photoshop/fertig/`.

## Installation

Voraussetzung ist Python 3.9 oder neuer. Auf macOS mit Homebrew-Python legst du eine eigene virtuelle Umgebung an, denn Homebrew erlaubt keine globalen `pip install`:

```bash
python3 -m venv ~/.venvs/greenscreen
~/.venvs/greenscreen/bin/pip install -r requirements.txt
```

Danach rufst du die Scripts immer mit `~/.venvs/greenscreen/bin/python` auf. Alternativ aktivierst du die Umgebung einmal pro Terminal-Sitzung mit `source ~/.venvs/greenscreen/bin/activate` und schreibst danach nur `python`.

## Nutzung

### `gruen_entfernen.py`: Spill aus freigestellten Bildern entfernen

```bash
# erst ein Bild testen
~/.venvs/greenscreen/bin/python gruen_entfernen.py ~/Bilder/shooting/photoshop --nur DSC00655.png

# dann alle
~/.venvs/greenscreen/bin/python gruen_entfernen.py ~/Bilder/shooting/photoshop
```

| Option | Bedeutung | Standard |
| --- | --- | --- |
| `ORDNER` | Ordner mit den PNGs mit Transparenz | – |
| `--nur DATEI …` | nur diese Dateien verarbeiten | alle |
| `--ziel ORDNER` | Ausgabeordner | `ORDNER/fertig` |
| `--staerke X` | Stärke der Kantenkorrektur, 0 bis 1,5 | `1.0` |
| `--16bit` | 16-Bit-PNGs statt 8 Bit ausgeben | aus |
| `--workers N` | Anzahl gleichzeitig verarbeiteter Bilder | halbe CPU-Kerne, max. 4 |
| `--neu` | vorhandene Ergebnisse überschreiben | aus |

Dateien ohne Transparenz werden mit einem Hinweis übersprungen. Wenn du den Lauf abbrichst, macht ein erneuter Start beim nächsten unfertigen Bild weiter.

### `greenscreen_freistellen.py`: alles in einem, ohne Photoshop

```bash
~/.venvs/greenscreen/bin/python greenscreen_freistellen.py ~/Bilder/shooting/tiffs
```

Das Script stellt per Chroma-Key frei, entfernt den Spill und gleicht die Belichtung aller Bilder an. Es ist schneller eingerichtet als Photoshop, schneidet an schwierigen Kanten aber eher etwas zu viel weg. Haben die Eingabedateien schon Transparenz, übernimmt es diese und keyt nicht selbst.

| Option | Bedeutung |
| --- | --- |
| `--referenz DATEI` | Helligkeit aller Bilder an dieses Bild angleichen (Standard: Mittelwert aus 15 Stichproben) |
| `--belichtung EV` | zusätzliche Belichtung für alle Bilder, z. B. `0.3` oder `-0.2` |
| `--ohne-belichtung` | keine Belichtungsangleichung |
| `--ohne-gruenfilter` | bei vorhandener Transparenz keine Leinwand-Grün-Reste entfernen (für grüne Kleidung) |
| `--nur`, `--ziel`, `--16bit`, `--workers`, `--neu` | wie oben, Ausgabe nach `ORDNER/freigestellt` |

Die angewandte Belichtungskorrektur pro Bild steht in `freigestellt/belichtung.csv`.

## Leistung und Speicher

Gemessen an 33-Megapixel-Bildern (7008 × 4672, 16-Bit-TIFF):

| | pro Bild | RAM pro Bild |
| --- | --- | --- |
| `gruen_entfernen.py` | ca. 10–15 s | ca. 2 GB |
| `greenscreen_freistellen.py` | ca. 15–20 s | ca. 2,5 GB |

Auf einem Mac mit 8 GB RAM `--workers 2` verwenden. Ein 8-Bit-PNG mit Transparenz ist bei dieser Auflösung etwa 40 MB groß.

## Grenzen

- Eine **leuchtend grüne Kleidung** wird mit entsättigt. Das betrifft vor allem `greenscreen_freistellen.py`, aber auch die Spill-Korrektur kann grüne Stoffe Richtung neutral ziehen.
- Die Korrektur geht davon aus, dass die Bilder **sRGB-ähnlich** kodiert sind. Bei ProPhoto RGB funktioniert sie, ist aber weniger genau.
- Fehler in der Photoshop-Maske, zum Beispiel ein abgeschnittenes Ohr, korrigiert `gruen_entfernen.py` nicht. Es verändert die Transparenz absichtlich nicht.

## Bekannte Probleme

### Photoshop gibt bei langen Stapelverarbeitungen den Arbeitsspeicher nicht vollständig frei

Bei Stapeln mit hunderten großen Bildern (33 MP, 16 Bit) steigt der Speicherverbrauch von Photoshop von Bild zu Bild an, obwohl jedes Dokument wieder geschlossen wird. Photoshop wird dadurch zunehmend langsamer und kann irgendwann mit einem Speicherfehler abbrechen.

`png_speichern_tiff_loeschen.jsx` schließt deshalb jedes Dokument ausdrücklich ohne Speichern und ruft danach `app.purge(PurgeTarget.ALLCACHES)` auf. Das leert Protokoll, Zwischenablage und Bildcaches. Es mildert das Problem, behebt es aber nicht vollständig. Ein Teil des Speichers wird erst beim Beenden von Photoshop wieder frei.

**Workarounds:**
- Den Stapel in **Teilen von etwa 50–100 Bildern** laufen lassen und Photoshop zwischendurch neu starten. Da das Script verarbeitete TIFFs löscht, enthält der Quellordner beim nächsten Start nur noch die offenen Bilder.
- Unter *Einstellungen → Leistung* die **Protokollobjekte** auf etwa 5 reduzieren (siehe [docs/photoshop.md](docs/photoshop.md#23-leistung-für-lange-stapel)).
- Während des Stapels keine anderen speicherintensiven Programme laufen lassen, zum Beispiel Lightroom.

## Lizenz

[MIT](LICENSE)
