// png_speichern_tiff_loeschen.jsx
// Fuer die Photoshop-Aktion nach "Hintergrund entfernen":
//   1. speichert das freigestellte Bild als PNG in den Unterordner "photoshop"
//      (neben dem TIFF, wird bei Bedarf angelegt)
//   2. prueft, ob das PNG wirklich geschrieben wurde
//   3. loescht erst dann das Original-TIFF (endgueltig, ohne Papierkorb)
//   4. schliesst das Dokument ohne weitere Rueckfrage
//   5. NEU: leert Protokoll und Caches, damit der Arbeitsspeicher
//      bei langen Stapelverarbeitungen nicht volllaeuft
#target photoshop
(function () {
    var UNTERORDNER = "photoshop";   // Name des PNG-Ordners neben den TIFFs
    var TIFF_LOESCHEN = true;        // auf false setzen, um nur zu speichern

    if (!app.documents.length) return;
    var doc = app.activeDocument;

    var src;
    try { src = doc.fullName; } catch (e) { alert("Bild hat keinen Speicherort – nichts geloescht."); return; }

    var base = decodeURI(src.name).replace(/\.[^.]+$/, "");
    var outDir = new Folder(src.parent.fsName + "/" + UNTERORDNER);
    if (!outDir.exists) outDir.create();
    var png = new File(outDir.fsName + "/" + base + ".png");

    var opts = new PNGSaveOptions();
    opts.interlaced = false;
    try { opts.compression = 1; } catch (e) {}       // schnell speichern
    doc.saveAs(png, opts, true, Extension.LOWERCASE); // als Kopie: Dokument bleibt das TIFF

    png = new File(png.fsName);                        // Dateiinfo neu lesen
    var ok = png.exists && png.length > 100000;

    if (ok && TIFF_LOESCHEN && /\.tiff?$/i.test(src.name)) {
        new File(src.fsName).remove();
    }

    // Dokument aus dem Speicher schliessen (klappt auch, wenn das TIFF schon geloescht ist)
    doc.close(SaveOptions.DONOTSAVECHANGES);
    doc = null;

    // NEU: Protokoll, Zwischenablage und Caches leeren, damit nichts liegen bleibt
    try { app.purge(PurgeTarget.ALLCACHES); } catch (e) {}

    if (!ok) throw new Error("PNG fuer " + base + " fehlt – TIFF wurde NICHT geloescht.");
})();
