# Funktionsweise

Hier steht, was die Scripts technisch machen. Das hilft, die Parameter gezielt anzupassen.

## Was „Green Spill“ ist

Ein beleuchteter Greenscreen wirkt wie eine große grüne Lichtquelle. Ihr Licht fällt zurück auf die Person, besonders auf:

- **helle, glänzende Flächen:** blonde Haare, Goldschmuck, weiße Trikots
- **Flächen, die zum Hintergrund zeigen:** Unterseite der Arme, Wangen im Profil, Schultern
- **halbtransparente Kanten:** feine Haare und Bewegungsunschärfe, in denen sich Vorder- und Hintergrundfarbe mischen

Eine KI-Maske, etwa „Hintergrund entfernen“ in Photoshop, trennt zwar Motiv und Hintergrund, lässt die grüne Färbung im Motiv aber unverändert.

Ausführlich zu den Ursachen und dazu, wie man Spill schon beim Shooting vermeidet: [gruene-reflexe.md](gruene-reflexe.md).

## `gruen_entfernen.py`

Die Korrektur läuft im **CIE-Lab-Farbraum**. Der Kanal **a\*** beschreibt dort die Achse Grün (negativ) bis Magenta/Rot (positiv), **b\*** die Achse Blau (negativ) bis Gelb (positiv). Grüner Spill zeigt sich als zu niedriges a\*. Helligkeit (L) und Gelbanteil (b\*) werden nicht verändert.

### Schritt 1: globaler Farbstich

Für jedes Pixel gilt: a\* muss mindestens `GLOBAL_RATIO × b*` betragen, Standard `0.18`. Liegt a\* darunter, wird es auf diesen Wert angehoben.

- Weiß und Grau (b\* ≈ 0) werden neutral.
- Gelbe Töne wie blonde Haare oder Gold bekommen einen leicht warmen Rotanteil, statt ins Gelbgrün zu kippen.
- **Schutz für Blau, Cyan und Lila:** Bei b\* < 0 wird die Korrektur zunehmend ausgeblendet. Bei b\* ≤ −8 ist sie ganz aus. Jeans, lila Trikots und blaue Logos bleiben so unverändert.

### Schritt 2: Kantenzone

An Haut- und Haarkanten ist der Spill am stärksten, und die globale Regel reicht dort nicht. Haut hat natürlicherweise ein a\*/b\*-Verhältnis von etwa 0,4–0,7 und würde mit 0,18 olivfarben wirken.

1. Mit einer **Distanztransformation** wird für jedes Motivpixel der Abstand zum Hintergrund berechnet.
2. Im **Inneren** des Motivs, weiter als 60 % der Zonenbreite vom Rand entfernt, misst das Script das typische a\*/b\*-Verhältnis. Das geschieht lokal mit einem großen Gaußfilter: In der Nähe des Gesichts ergibt sich so das Verhältnis der Haut, in der Nähe der Haare das der Haare.
3. In der **Kantenzone** (`EDGE_ZONE`, Standard 3 % der Bildbreite, bei 7008 px also etwa 210 px) wird a\* auf dieses lokale Verhältnis angehoben. Die Stärke fällt linear vom Rand zum Inneren ab.

`--staerke` skaliert diese Gewichtung. Bei 0 gibt es keine Kantenkorrektur, bei 1,5 ist sie stärker und reicht weiter ins Motiv hinein.

### Schritt 3: halbtransparente Randpixel

Pixel mit Alpha < 0,98 enthalten noch Hintergrundfarbe. Ihre Farbe wird durch die Farbe der **benachbarten, voll deckenden Motivpixel** ersetzt. Dafür wird ein normalisierter Gaußfilter über die deckenden Pixel gelegt, mit einem Radius von etwa 6 px bei 2576 px Bildbreite, skaliert auf die tatsächliche Auflösung. Je transparenter ein Pixel ist, desto vollständiger wird seine Farbe ersetzt.

### Schritt 4: Rest-Grün begrenzen

In Randpixeln wird der Grünkanal auf den Mittelwert aus Rot und Blau begrenzt, mit einem kleinen Spielraum von 15 %. Diese klassische Despill-Regel fängt letzte grüne Pixel ab.

### Was unverändert bleibt

- **Alpha/Transparenz:** wird aus der Eingabedatei übernommen (bei gleicher Bittiefe von Ein- und Ausgabe bitgenau)
- **Helligkeit (L\*)** und **Gelb-Blau-Achse (b\*)**
- **ICC-Farbprofil:** wird als iCCP-Chunk in das PNG geschrieben

## `greenscreen_freistellen.py`

Enthält dieselbe Spill-Korrektur und zusätzlich:

### Chroma-Key

- **Grün-Überschuss** pro Pixel: `d = G − max(R, B)`, relativ zur Helligkeit `rel = d / G`
- Alpha geht von 1 bei `rel ≤ 0.18` linear auf 0 bei `rel ≥ 0.40` (`KEY_LO`, `KEY_HI`). Weil der Wert relativ zur Helligkeit gemessen wird, werden auch die dunklen Schattenstreifen eines Greenscreen-Gestells sicher als Hintergrund erkannt.
- **Aufräumen:** Morphologisches Öffnen, nur große zusammenhängende Flächen behalten, kleine Löcher im Motiv füllen. Große Lücken, zum Beispiel zwischen Arm und Körper, bleiben transparent.
- Alle Größen (Kernel, Flächen-Schwellen) skalieren mit der Bildbreite. Abgestimmt wurden sie bei 2576 px.

Ist die Eingabedatei bereits transparent, wird ihre Maske übernommen. Nur eindeutig leinwandgrüne Pixel (`rel > 0.35`) werden zusätzlich entfernt, außer bei `--ohne-gruenfilter`.

### Belichtungsangleichung

1. **Messwert pro Bild:** das 90. Perzentil der Luminanz aller deckenden Motivpixel, in linearem Licht. Bei hellen Trikots entspricht das ungefähr der Helligkeit des Stoffs, ein stabiler Bezugspunkt.
2. **Zielwert:** der Median der Messwerte von 15 gleichmäßig über die Serie verteilten Bildern, oder der Messwert von `--referenz`. Der Zielwert wird in `freigestellt/.belichtung_ziel` gespeichert, damit ein fortgesetzter Lauf dieselbe Helligkeit trifft.
3. **Korrektur:** `log2(Ziel / Messwert)` in Blendenstufen, begrenzt auf ±1,5 EV (`EXPO_MAX_EV`). Die Verstärkung wird in linearem Licht angewendet. Bei Aufhellung schützt eine weiche Schulter ab 85 % die Lichter vor dem Ausbrennen.

## Anpassbare Konstanten

Am Anfang der Scripts:

| Konstante | Script | Standard | Wirkung |
| --- | --- | --- | --- |
| `GLOBAL_RATIO` | beide | `0.18` | höher = wärmerer Ausgleich überall (Haare werden rötlicher) |
| `EDGE_ZONE` | beide | `0.03` | Breite der Kantenzone relativ zur Bildbreite |
| `KEY_LO`, `KEY_HI` | freistellen | `0.18`, `0.40` | höher = weniger wird transparent (mehr Kante bleibt, aber mehr Grünreste) |
| `EXPO_PCT` | freistellen | `90` | Perzentil für die Helligkeitsmessung |
| `EXPO_MAX_EV` | freistellen | `1.5` | maximale automatische Belichtungskorrektur |
