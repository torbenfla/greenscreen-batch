#!/usr/bin/env python3
"""
Gruene Reflexe (Greenscreen-Spill) aus freigestellten Bildern entfernen.

Erwartet PNGs mit Transparenz, z. B. aus Photoshop ("Hintergrund entfernen").
Die Maske/Transparenz wird NICHT veraendert. Das Script entfernt nur:
  * gruenen Farbstich auf Haaren, Haut, Schmuck und Kleidung
  * den olivgruenen Schimmer an Haut- und Haarkanten
  * gruene Saeume in halbtransparenten Randpixeln
Blau-, Cyan- und Lilatoene (Jeans, Trikots, Ball) bleiben geschuetzt.
Das eingebettete Farbprofil wird uebernommen.

Einrichtung (einmalig):
    python3 -m venv ~/.venvs/greenscreen
    ~/.venvs/greenscreen/bin/pip install numpy opencv-python pillow

Aufruf:
    ~/.venvs/greenscreen/bin/python gruen_entfernen.py ORDNER [Optionen]

Optionen:
    --nur DATEI [DATEI ...]   nur diese Bilder (zum Testen)
    --ziel ORDNER             Ausgabeordner (Standard: ORDNER/fertig)
    --staerke X               Staerke der Kantenkorrektur, 0 bis 1.5 (Standard 1.0)
    --16bit                   16-Bit-PNGs ausgeben
    --workers N               parallele Bilder (ca. 2 GB RAM pro Bild)
    --neu                     vorhandene Ergebnisse ueberschreiben
    --beobachten              laufend auf neue Bilder warten, z. B. waehrend die
                              Photoshop-Stapelverarbeitung noch laeuft (Strg+C beendet)

Bereits verarbeitete Bilder werden uebersprungen – ausser die Quelldatei ist
neuer als das Ergebnis (z. B. in Photoshop neu freigestellt). Dateien, die in
den letzten 10 Sekunden geschrieben wurden, werden erst spaeter verarbeitet.
"""
import argparse
import os
import signal
import struct
import sys
import time
import zlib
from concurrent.futures import ProcessPoolExecutor, as_completed

import cv2
import numpy as np

EXT = {".png", ".tif", ".tiff"}
GLOBAL_RATIO = 0.18   # gesamtes Motiv: a* mindestens 0,18 * b* (Gruen raus, neutral bis leicht warm)
EDGE_ZONE = 0.03      # Breite der Kantenzone (Anteil der Bildbreite)


def read_icc(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.info.get("icc_profile")
    except Exception:
        return None


def png_with_icc(png_bytes, icc):
    if not icc:
        return png_bytes
    data = b"ICC Profile\x00\x00" + zlib.compress(icc)
    chunk = struct.pack(">I", len(data)) + b"iCCP" + data
    chunk += struct.pack(">I", zlib.crc32(b"iCCP" + data) & 0xFFFFFFFF)
    ihdr_end = 8 + 4 + 4 + 13 + 4
    return png_bytes[:ihdr_end] + chunk + png_bytes[ihdr_end:]


def blur_small(x, sigma_px, factor=8):
    h, w = x.shape[:2]
    sm = cv2.resize(x, (max(1, w // factor), max(1, h // factor)), interpolation=cv2.INTER_AREA)
    sm = cv2.GaussianBlur(sm, (0, 0), max(0.5, sigma_px / factor))
    return cv2.resize(sm, (w, h), interpolation=cv2.INTER_LINEAR)


def remove_spill(rgb, a, strength=1.0):
    h, w = rgb.shape[:2]
    s = w / 2576.0
    m = (a > 0.5).astype(np.uint8)

    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2Lab)
    L, A, B = cv2.split(lab)
    del lab
    protect = np.clip((B + 8) / 8, 0, 1)    # Blau/Cyan/Lila nicht anfassen

    # 1) Farbstich im ganzen Motiv: nichts darf gruener als neutral sein
    tgt = GLOBAL_RATIO * np.maximum(B, 0)
    A = np.where(A < tgt, A + (tgt - A) * protect, A).astype(np.float32)

    # 2) Kantenzone: natuerlichen Farbton aus dem Motiv-Inneren an den Rand uebertragen
    dist = cv2.distanceTransform(m, cv2.DIST_L2, 5)
    zone = EDGE_ZONE * w
    interior = ((dist > 0.6 * zone) & (B > 6)).astype(np.float32)
    sig = 1.2 * zone
    nA = blur_small(A * interior, sig)
    nB = blur_small(B * interior, sig)
    cnt = blur_small(interior, sig)
    ratio = np.where((cnt > 0.02) & (nB > 1), nA / np.maximum(nB, 1e-3), GLOBAL_RATIO)
    ratio = np.clip(ratio, GLOBAL_RATIO, 0.8).astype(np.float32)
    del nA, nB, cnt, interior
    wz = np.clip((1.0 - dist / zone) * strength, 0, 1) * (m > 0)
    del dist
    tgt = ratio * np.maximum(B, 0)
    A = np.where(A < tgt, A + (tgt - A) * wz * protect, A).astype(np.float32)
    del tgt, ratio, wz, protect

    rgb = cv2.cvtColor(cv2.merge([L, A, B]), cv2.COLOR_Lab2RGB)
    del L, A, B

    # 3) halbtransparente Randpixel: Farbe aus dem sauberen Motiv daneben uebernehmen
    solid = (a >= 0.98).astype(np.float32)
    rad = 6 * s
    num = cv2.GaussianBlur(rgb * solid[..., None], (0, 0), rad)
    den = cv2.GaussianBlur(solid, (0, 0), rad)[..., None]
    prop = num / np.maximum(den, 1e-4)
    t = np.clip((1.0 - a) * 1.6, 0, 1)[..., None] * (den > 0.01)
    rgb = rgb * (1 - t) + prop * t
    del num, den, prop, t, solid

    # 4) Rest-Gruen in Randpixeln begrenzen
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    edge = a < 0.98
    lim = (r + b) / 2
    g[:] = np.where(edge & (g > lim), lim + 0.15 * (g - lim), g)
    return rgb


def process(src, dst, out16, strength):
    raw = cv2.imread(src, cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise RuntimeError("Datei konnte nicht gelesen werden")
    if raw.ndim != 3 or raw.shape[2] != 4:
        raise RuntimeError("keine Transparenz – erst in Photoshop freistellen")
    maxv = 65535.0 if raw.dtype == np.uint16 else 255.0
    a = raw[:, :, 3].astype(np.float32) / maxv
    rgb = cv2.cvtColor(raw[:, :, :3], cv2.COLOR_BGR2RGB).astype(np.float32) / maxv
    del raw

    rgb = remove_spill(rgb, a, strength)

    bgra = np.dstack([rgb[..., 2], rgb[..., 1], rgb[..., 0], a])
    del rgb
    np.clip(bgra, 0, 1, out=bgra)
    out = (bgra * 65535 + 0.5).astype(np.uint16) if out16 else (bgra * 255 + 0.5).astype(np.uint8)
    del bgra
    ok, buf = cv2.imencode(".png", out, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not ok:
        raise RuntimeError("PNG konnte nicht erzeugt werden")
    tmp = dst + ".part"
    with open(tmp, "wb") as f:
        f.write(png_with_icc(buf.tobytes(), read_icc(src)))
    os.replace(tmp, dst)


STABLE_SECONDS = 10   # Dateien, die juenger sind, schreibt Photoshop evtl. noch
WATCH_INTERVAL = 15   # Sekunden zwischen zwei Pruefungen im Modus --beobachten


def collect_jobs(src_dir, dst_dir, only=None, force=False, failed=None):
    """Offene Bilder finden: Ergebnis fehlt oder Quelle ist neuer als das Ergebnis.
    Gibt (jobs, noch_in_arbeit) zurueck."""
    files = sorted(f for f in os.listdir(src_dir)
                   if os.path.splitext(f)[1].lower() in EXT and not f.startswith("."))
    if only:
        files = [f for f in files if f in set(only)]
    now = time.time()
    jobs, busy = [], 0
    for f in files:
        src = os.path.join(src_dir, f)
        dst = os.path.join(dst_dir, os.path.splitext(f)[0] + ".png")
        try:
            s_mtime = os.path.getmtime(src)
        except OSError:
            continue
        if now - s_mtime < STABLE_SECONDS:
            busy += 1
            continue
        if failed is not None and failed.get(src) == s_mtime:
            continue                      # schon fehlgeschlagen und seitdem unveraendert
        if not force and os.path.exists(dst) and os.path.getmtime(dst) >= s_mtime:
            continue
        jobs.append((src, dst))
    return jobs, busy


def _worker_init():
    signal.signal(signal.SIGINT, signal.SIG_IGN)   # Strg+C behandelt nur der Hauptprozess


def run_jobs(ex, jobs, out16, strength, failed):
    t0 = time.time()
    done = errs = 0
    futs = {ex.submit(process, s, d, out16, strength): s for s, d in jobs}
    for fut in as_completed(futs):
        src = futs[fut]
        name = os.path.basename(src)
        try:
            fut.result()
            done += 1
            failed.pop(src, None)
            eta = (time.time() - t0) / (done + errs) * (len(jobs) - done - errs)
            print(f"[{done + errs}/{len(jobs)}] {name}  ok   (Rest ca. {eta / 60:.0f} min)", flush=True)
        except Exception as e:
            errs += 1
            try:
                failed[src] = os.path.getmtime(src)
            except OSError:
                pass
            print(f"[{done + errs}/{len(jobs)}] {name}  FEHLER: {e}", flush=True)
    return done, errs


def main():
    p = argparse.ArgumentParser(description="Gruene Reflexe aus freigestellten Bildern entfernen")
    p.add_argument("ordner")
    p.add_argument("--ziel")
    p.add_argument("--nur", nargs="*")
    p.add_argument("--staerke", type=float, default=1.0)
    p.add_argument("--16bit", dest="out16", action="store_true")
    p.add_argument("--workers", type=int, default=0)
    p.add_argument("--neu", action="store_true")
    p.add_argument("--beobachten", action="store_true",
                   help="laufend auf neue Bilder warten (z. B. waehrend Photoshop noch arbeitet), Strg+C beendet")
    args = p.parse_args()

    src_dir = os.path.abspath(os.path.expanduser(args.ordner))
    dst_dir = os.path.abspath(os.path.expanduser(args.ziel or os.path.join(src_dir, "fertig")))
    os.makedirs(dst_dir, exist_ok=True)
    workers = args.workers or max(1, min(4, (os.cpu_count() or 2) // 2))
    strength = float(np.clip(args.staerke, 0, 1.5))
    failed = {}
    total_ok = total_err = 0
    force = args.neu

    with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init) as ex:
        try:
            first = True
            while True:
                jobs, busy = collect_jobs(src_dir, dst_dir, args.nur, force, failed)
                force = False             # --neu gilt nur fuer den ersten Durchgang
                if jobs:
                    print(f"{len(jobs)} Bilder → {dst_dir}  ({workers} parallel, Staerke {strength})", flush=True)
                    ok, err = run_jobs(ex, jobs, args.out16, strength, failed)
                    total_ok += ok
                    total_err += err
                    first = False
                    continue              # sofort nachsehen, ob inzwischen Neues da ist
                if not args.beobachten:
                    if busy:
                        print(f"{busy} Bild(er) werden gerade noch geschrieben – in ein paar Sekunden erneut starten.")
                    elif first:
                        print("Nichts zu tun – alle Bilder sind aktuell (--neu zum Ueberschreiben).")
                    break
                if first or busy:
                    msg = f"{busy} Bild(er) werden noch geschrieben, " if busy else ""
                    print(f"Warte auf neue Bilder … {msg}(Strg+C beendet)", flush=True)
                first = False
                time.sleep(WATCH_INTERVAL)
        except KeyboardInterrupt:
            print("\nBeende … laufende Bilder werden noch fertig gespeichert.", flush=True)
            ex.shutdown(wait=True, cancel_futures=True)
            print("Beendet.")

    if total_ok or total_err:
        print(f"Insgesamt: {total_ok} ok, {total_err} Fehler")
    if total_err:
        sys.exit(1)


if __name__ == "__main__":
    main()
