# Photoshop: Einrichtung für die Stapel-Freistellung

Diese Anleitung beschreibt, wie Photoshop hunderte TIFFs automatisch freistellt, als PNG speichert und die Quelldateien danach löscht. Danach entfernt [`gruen_entfernen.py`](../gruen_entfernen.py) die grünen Reflexe.

Die Menübezeichnungen beziehen sich auf die deutsche Photoshop-Version für macOS (Stand 2026). In anderen Versionen können Namen leicht abweichen.

---

## 1. Export aus Lightroom

Die Freistellung wird besser, wenn Photoshop ein sauberes, kontrastreiches Ausgangsbild bekommt.

| Einstellung | Wert | Warum |
| --- | --- | --- |
| Format | TIFF | verlustfrei, keine JPEG-Artefakte an den Kanten |
| Bittiefe | 16 Bit | feinere Abstufungen für die Spill-Korrektur |
| Farbraum | sRGB | darauf ist die Spill-Korrektur abgestimmt |
| Größe | keine Größenänderung | volle Auflösung für feine Haare |
| Komprimierung | Ohne | schneller zu öffnen; kostet aber viel Platz |
| Schärfen | aus oder gering | starkes Schärfen erzeugt helle Säume, die die KI als Motiv wertet |

**In Lightroom vorab erledigen:**
- **Weißabgleich** mit der Pipette auf eine neutrale Stelle im Motiv setzen, zum Beispiel ein weißes Trikot.
- **Belichtung** über die Serie angleichen. Am einfachsten an einem Referenzbild einstellen und mit *Synchronisieren* übertragen.
- **Grün nicht entsättigen.** Ein kräftiges, gleichmäßiges Grün hilft der KI bei der Kantenerkennung. Die Reflexe entfernt später das Script.
- **Rauschreduzierung** bei hohen ISO-Werten moderat einsetzen. Rauschen im Grün erschwert saubere Haarkanten.

---

## 2. Photoshop einmalig einrichten

### 2.1 KI-Qualität für „Motiv auswählen“ und „Hintergrund entfernen“

*Photoshop → Einstellungen → Bildverarbeitung*:

- **„Verarbeitung von Motiv auswählen und Hintergrund entfernen“: Cloud (detaillierte Ergebnisse)**

Die Cloud-Verarbeitung liefert deutlich bessere Haarkanten als die Option „Gerät“. Sie braucht eine Internetverbindung und ist pro Bild etwas langsamer.

### 2.2 Farbmanagement

*Bearbeiten → Farbeinstellungen* (Umschalt+Cmd+K):

- RGB: **„Eingebettete Profile beibehalten“**
- Profilabweichung: Haken bei **„Beim Öffnen wählen“** und **„Beim Einfügen wählen“** entfernen
- Fehlende Profile: Haken bei „Beim Öffnen wählen“ entfernen

Ohne diese Einstellungen hält die Stapelverarbeitung bei jedem Bild mit der Meldung „Abweichung vom eingebetteten Profil“ an.

### 2.3 Leistung für lange Stapel

*Photoshop → Einstellungen → Leistung*:

- **Arbeitsspeicher** für Photoshop auf etwa 60–70 % setzen. Mehr ist bei langen Stapeln kontraproduktiv: Auf einem Mac mit 16 GB belegte Photoshop in der Praxis rund 13 GB, macOS musste massiv auf die SSD auslagern, und der freie Festplattenplatz schrumpfte um über 20 GB.
- **Protokollobjekte** auf etwa 5 reduzieren. Bei 33-Megapixel-Bildern füllt jeder Protokollschritt sonst Hunderte Megabyte.

Das Script `png_speichern_tiff_loeschen.jsx` leert nach jedem Bild zusätzlich alle Caches.

### 2.4 Ausgabeordner

Das Script legt neben den TIFFs automatisch den Unterordner `photoshop/` an. Du musst nichts vorbereiten.

---

## 3. Aktion aufzeichnen

### 3.1 Script ablegen

Lege [`photoshop/png_speichern_tiff_loeschen.jsx`](../photoshop/png_speichern_tiff_loeschen.jsx) an einen festen Ort, zum Beispiel `~/Scripts/`. Die Aktion merkt sich den Pfad. Verschiebst du die Datei später, musst du den Schritt neu aufzeichnen.

Das Script hat oben zwei Einstellungen:

```js
var UNTERORDNER = "photoshop";   // Name des PNG-Ordners neben den TIFFs
var TIFF_LOESCHEN = true;        // auf false setzen, um nur zu speichern
```

> **Achtung:** Mit `TIFF_LOESCHEN = true` wird das Quell-TIFF **endgültig** gelöscht, ohne Papierkorb. Gelöscht wird nur, wenn das PNG vorher erfolgreich geschrieben wurde. Ob die Freistellung gut aussieht, prüft das Script aber nicht. Die RAW-Dateien in Lightroom bleiben unberührt, die TIFFs lassen sich also jederzeit neu exportieren.

### 3.2 Aktion anlegen

1. Ein TIFF aus der Serie öffnen.
2. *Fenster → Aktionen* (Option+F9).
3. Unten im Panel auf das **Ordner-Symbol** klicken und ein neues Set anlegen, zum Beispiel „Greenscreen“.
4. Auf das **Plus-Symbol** klicken und die Aktion „Freistellen“ nennen → **Aufzeichnen**. Der rote Punkt unten im Panel leuchtet jetzt.
5. **Freistellen.** Eine der beiden Varianten wählen:
   - **Variante A (einfach):** in der Kontext-Taskleiste oder im Eigenschaften-Bedienfeld unter *Schnelle Aktionen* **„Hintergrund entfernen“** klicken.
   - **Variante B (mehr Kontrolle):**
     1. *Ebene → Neu → Ebene aus Hintergrund* → OK
     2. *Auswahl → Motiv*
     3. *Auswahl → Auswählen und maskieren* → „Haare verfeinern“ klicken, Kante verbessern mit Radius 3–5 px und „Objektgenaue Kante“ an, Ausgabe: **Ebenenmaske**
6. *Datei → Skripten → Durchsuchen…* → `png_speichern_tiff_loeschen.jsx` → Öffnen. Das Script speichert das PNG, löscht das TIFF und schließt das Dokument.
7. Unten im Panel auf das **Quadrat** klicken, um die Aufnahme zu beenden.

Die fertige Aktion sieht so aus:

```
Freistellen
├─ Hintergrund entfernen      (bzw. Ebene aus Hintergrund / Motiv auswählen / Auswählen und maskieren)
└─ Skripten: png_speichern_tiff_loeschen.jsx
```

> Beim Aufzeichnen läuft das Script bereits einmal. Das geöffnete Test-TIFF wird also gelöscht, sein PNG liegt dann aber schon in `photoshop/`.

**Hinweise zu Variante B:**
- In *Auswählen und maskieren* **nicht** „Farben dekontaminieren“ aktivieren. Die Option erzeugt eine zusätzliche Ebene und verfälscht die Kantenfarben. Den grünen Saum entfernt `gruen_entfernen.py` sauberer.
- Prüfe die Aktion nach dem Aufzeichnen an zwei, drei anderen Bildern. Nicht jede Einstellung im Dialog „Auswählen und maskieren“ wird in jeder Photoshop-Version gleich zuverlässig aufgezeichnet.

### 3.3 Aktion testen

Ein anderes TIFF öffnen, die Aktion markieren und auf das **Dreieck** („Auswahl ausführen“) klicken. Danach sollte im Ordner `photoshop/` ein PNG mit transparentem Hintergrund liegen.

---

## 4. Stapelverarbeitung

*Datei → Automatisieren → Stapelverarbeitung*:

| Bereich | Einstellung |
| --- | --- |
| Set / Aktion | „Greenscreen“ / „Freistellen“ |
| Quelle | **Ordner** → der Ordner mit den TIFFs |
| | ☐ „Öffnen“ in Aktionen überschreiben (die Aktion enthält kein Öffnen) |
| | ☐ Alle Unterordner einschließen |
| | ☑ Optionsdialoge für Datei öffnen unterdrücken |
| | ☑ **Farbprofil-Warnungen unterdrücken** |
| Ziel | **Ohne**, denn das Script speichert selbst |
| Fehler | **Fehler in Protokolldatei speichern** → Datei wählen |

Mit OK starten. Photoshop arbeitet die TIFFs nacheinander ab. Bei Fehlern, zum Beispiel wenn kein PNG geschrieben wurde, bleibt das TIFF erhalten und der Fehler steht in der Protokolldatei.

---

## 5. Danach: grüne Reflexe entfernen

```bash
~/.venvs/greenscreen/bin/python gruen_entfernen.py PFAD/ZUM/TIFF-ORDNER/photoshop
```

Die fertigen Bilder liegen in `photoshop/fertig/`. Details siehe [README](../README.md#nutzung).

---

## 6. Tipps für bessere Freistellungen schon beim Shooting

| Maßnahme | Effekt |
| --- | --- |
| **2–3 m Abstand** zwischen Person und Greenscreen | deutlich weniger grünes Streulicht auf Haaren und Schultern |
| Hintergrund **separat und gleichmäßig** ausleuchten | gleichmäßiges Grün ohne dunkle Falten oder Schatten vom Gestell; die KI trennt dann sicherer |
| Hintergrund **nicht überbelichten** | überstrahltes Grün färbt die Kanten stärker ein |
| **Haarlicht / Kante von hinten** | überstrahlt den Spill an Haarkanten und trennt das Motiv sauber vom Hintergrund |
| Greenscreen **faltenfrei** spannen | weniger Schatten, die als dunkle Flächen ins Motiv übergehen |
| **Keine grüne Kleidung** oder grünen Accessoires | sonst werden sie mit freigestellt oder entsättigt |
| Ganze Personen **nicht am Bildrand anschneiden** | die KI erkennt angeschnittene Körperteile schlechter |
| Eher **geschlossene Blende** (f/5.6–f/8) | scharfe Haarkanten lassen sich sauberer freistellen als unscharfe |

---

## Fehlerbehebung

| Problem | Lösung |
| --- | --- |
| „Abweichung vom eingebetteten Profil“ hält den Stapel an | Farbeinstellungen wie in [2.2](#22-farbmanagement) setzen und „Farbprofil-Warnungen unterdrücken“ in der Stapelverarbeitung aktivieren |
| PNG fehlt unter *Speichern unter* | Nur relevant, wenn du ohne das Script speicherst: *Einstellungen → Dateihandhabung →* „Legacy-Dialogfeld ‚Speichern unter‘ aktivieren“ |
| Photoshop wird mit der Zeit langsam oder bricht mit Speicherfehler ab | Bekanntes Problem: Photoshop gibt Speicher bei langen Stapeln nicht vollständig frei, auch nicht nach dem Cache-Leeren durch das Script. Stapel in Teilen von 50–100 Bildern laufen lassen und Photoshop dazwischen neu starten, Protokollobjekte reduzieren ([2.3](#23-leistung-für-lange-stapel)). Siehe [Bekannte Probleme](../README.md#bekannte-probleme) |
| Haare wirken abgehackt | Cloud-Verarbeitung aktivieren ([2.1](#21-ki-qualität-für-motiv-auswählen-und-hintergrund-entfernen)) oder Variante B mit „Haare verfeinern“ |
| Script-Schritt findet die .jsx nicht mehr | Die Datei wurde verschoben. Den Schritt in der Aktion löschen und neu aufzeichnen |
| `gruen_entfernen.py` meldet „keine Transparenz“ | Das PNG wurde ohne Maske gespeichert. Prüfen, ob der Freistellungsschritt in der Aktion vor dem Script steht |
