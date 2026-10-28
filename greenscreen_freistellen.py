#!/usr/bin/env python3
"""
Greenscreen freistellen + gruene Reflexe entfernen + Belichtung angleichen.

Zwei Betriebsarten (automatisch erkannt):
  * Bilder MIT Transparenz (z. B. PNG aus Photoshop "Motiv auswaehlen"):
    Die Photoshop-Maske wird uebernommen, das Script entfernt nur noch
    gruene Reflexe/Saeume und gleicht die Belichtung an.
  * Bilder OHNE Transparenz (TIFF/JPEG direkt aus Lightroom):
    Das Script stellt selbst per Greenscreen-Key frei.

Liest alle TIFF/JPEG/PNG-Dateien aus einem Ordner, macht den gruenen
Hintergrund transparent, entfernt den gruenen Farbstich (Spill) auf
Haaren, Haut, Schmuck und Kleidung, gleicht die Helligkeit aller Bilder
an und speichert PNGs mit Transparenz. Das eingebettete Farbprofil
(z. B. sRGB) wird in die PNGs uebernommen.

Einrichtung (einmalig):
    python3 -m venv ~/.venvs/greenscreen
    ~/.venvs/greenscreen/bin/pip install numpy opencv-python pillow

Aufruf:
    ~/.venvs/greenscreen/bin/python greenscreen_freistellen.py ORDNER [Optionen]

Optionen:
    --nur DATEI [DATEI ...]   nur diese Bilder verarbeiten (zum Testen)
    --referenz DATEI          Helligkeit aller Bilder an dieses Bild angleichen
                              (ohne Angabe: Mittelwert aus Stichprobe der Serie)
    --ohne-belichtung         keine Belichtungsangleichung
    --belichtung EV           zusaetzliche Belichtung fuer alle Bilder, z. B. 0.3 oder -0.2
    --16bit                   16-Bit-PNGs (doppelt so gross)
    --workers N               parallele Bilder (weniger = weniger RAM, ca. 2,5 GB pro Bild)
    --neu                     vorhandene Ergebnisse ueberschreiben
    --ohne-gruenfilter        bei Photoshop-Masken keine Leinwand-Gruen-Reste entfernen
                              (nur noetig, wenn Kleidung leuchtend gruen ist)

Ausgabe landet in ORDNER/freigestellt/. Fertige Dateien werden beim
erneuten Start uebersprungen. Die angewandte Belichtungskorrektur pro
Bild steht in ORDNER/freigestellt/belichtung.csv.
"""
import argparse
import os
import struct
import sys
import time
import zlib
from concurrent.futures import ProcessPoolExecutor, as_completed

import cv2
import numpy as np

EXT = {".tif", ".tiff", ".jpg", ".jpeg", ".png"}

KEY_LO, KEY_HI = 0.18, 0.40   # relativer Gruen-Ueberschuss: ab LO wird es transparent
GLOBAL_RATIO = 0.18           # globaler Spill: a* mindestens 0,18 * b* (neutral bis leicht warm)
EDGE_ZONE = 0.03              # Breite der Kantenzone (Anteil der Bildbreite) fuer starken Spill
EXPO_PCT = 90                 # Helligkeits-Messpunkt: 90. Perzentil der Motiv-Luminanz
EXPO_MAX_EV = 1.5             # maximale automatische Korrektur in Blendenstufen


def odd(n):
    n = max(1, int(round(n)))
    return n if n % 2 else n + 1


def srgb_to_lin(x):
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4).astype(np.float32)


def lin_to_srgb(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055).astype(np.float32)


def read_rgba(path):
    """RGB (float 0..1) und, falls vorhanden, Alpha aus der Datei (z. B. Photoshop-Maske)."""
    raw = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise RuntimeError("Datei konnte nicht gelesen werden")
    if raw.ndim == 2:
        raw = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
    maxv = 65535.0 if raw.dtype == np.uint16 else 255.0
    alpha = None
    if raw.shape[2] == 4:
        alpha = raw[:, :, 3].astype(np.float32) / maxv
        raw = raw[:, :, :3]
    return cv2.cvtColor(raw, cv2.COLOR_BGR2RGB).astype(np.float32) / maxv, alpha


def alpha_from_file(rgb, alpha, green_filter=True):
    """Maske aus Photoshop uebernehmen; optional eindeutige Greenscreen-Reste entfernen."""
    a = alpha.copy()
    if green_filter:
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        d = g - np.maximum(r, b)
        rel = d / np.maximum(g, 1 / 255)
        screen = 1.0 - np.clip((rel - 0.35) / 0.15, 0, 1)   # nur klar leinwand-gruene Pixel
        screen[d < 25 / 255] = 1.0
        a = np.minimum(a, screen).astype(np.float32)
        del d, rel, screen
    m = (a > 0.5).astype(np.uint8)
    return a, m


def get_alpha(rgb, alpha, green_filter=True):
    if alpha is not None and float(alpha.min()) < 0.99:
        return alpha_from_file(rgb, alpha, green_filter)
    return key(rgb)


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


# ---------------------------------------------------------------------------
def key(rgb):
    """Liefert weiches Alpha (float32) und harte Motivmaske (uint8)."""
    h, w = rgb.shape[:2]
    s = w / 2576.0
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    d = g - np.maximum(r, b)
    rel = d / np.maximum(g, 1 / 255)
    a = 1.0 - np.clip((rel - KEY_LO) / (KEY_HI - KEY_LO), 0, 1)
    a[d < 12 / 255] = 1.0
    del d

    m = (a > 0.5).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((odd(5 * s),) * 2, np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] > 20000 * s * s
    m = keep[lab].astype(np.uint8)
    inv = (1 - m).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    small = np.zeros(n, bool)
    small[1:] = stats[1:, cv2.CC_STAT_AREA] < 3000 * s * s
    m[small[lab]] = 1
    del lab, inv

    region = cv2.dilate(m, np.ones((odd(9 * s),) * 2, np.uint8)).astype(bool)
    core = cv2.erode(m, np.ones((odd(7 * s),) * 2, np.uint8)).astype(bool)
    a = np.where(region, a, 0)
    a = np.where(core & (rel < 0.35), 1.0, a).astype(np.float32)
    del rel, region, core
    a = cv2.GaussianBlur(a, (odd(3 * s),) * 2, 0.8 * s)
    return a, m


def blur_small(x, sigma_px, factor=8):
    """Grosser Gauss-Blur, guenstig ueber verkleinertes Bild."""
    h, w = x.shape[:2]
    sm = cv2.resize(x, (max(1, w // factor), max(1, h // factor)), interpolation=cv2.INTER_AREA)
    sm = cv2.GaussianBlur(sm, (0, 0), max(0.5, sigma_px / factor))
    return cv2.resize(sm, (w, h), interpolation=cv2.INTER_LINEAR)


def despill(rgb, a, m):
    h, w = rgb.shape[:2]
    s = w / 2576.0
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2Lab)
    L, A, B = cv2.split(lab)
    del lab
    protect = np.clip((B + 8) / 8, 0, 1)     # echte Blau/Cyan-Toene (Ball, Logos) schuetzen

    # 1) globaler Spill: Gruen raus, Richtung neutral/warm
    tgt = GLOBAL_RATIO * np.maximum(B, 0)
    A = np.where(A < tgt, A + (tgt - A) * protect, A).astype(np.float32)

    # 2) Kantenzone: Farbton aus dem Inneren des Motivs in die Randbereiche uebertragen
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
    wz = np.clip(1.0 - dist / zone, 0, 1) * (m > 0)
    del dist
    tgt = ratio * np.maximum(B, 0)
    A = np.where(A < tgt, A + (tgt - A) * wz * protect, A).astype(np.float32)
    del tgt, ratio, wz, protect

    rgb = cv2.cvtColor(cv2.merge([L, A, B]), cv2.COLOR_Lab2RGB)
    del L, A, B

    # 3) halbtransparente Kantenpixel: Farbe aus dem sauberen Motiv-Inneren uebernehmen
    solid = (a >= 0.98).astype(np.float32)
    rad = 6 * s
    num = cv2.GaussianBlur(rgb * solid[..., None], (0, 0), rad)
    den = cv2.GaussianBlur(solid, (0, 0), rad)[..., None]
    prop = num / np.maximum(den, 1e-4)
    t = np.clip((1.0 - a) * 1.6, 0, 1)[..., None] * (den > 0.01)
    rgb = rgb * (1 - t) + prop * t
    del num, den, prop, t, solid

    # 4) Rest-Gruen in Kantenpixeln begrenzen
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    edge = a < 0.98
    lim = (r + b) / 2
    g[:] = np.where(edge & (g > lim), lim + 0.15 * (g - lim), g)
    return rgb


def luminance_stat(rgb, a):
    """Helligkeits-Messwert des Motivs (lineares Licht)."""
    step = 4
    lin = srgb_to_lin(rgb[::step, ::step])
    Y = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
    msk = a[::step, ::step] >= 0.98
    if msk.sum() < 1000:
        return None
    return float(np.percentile(Y[msk], EXPO_PCT))


def measure(path, green_filter=True):
    rgb, alpha = read_rgba(path)
    a, m = get_alpha(rgb, alpha, green_filter)
    return luminance_stat(rgb, a)


def apply_exposure(rgb, gain):
    lin = srgb_to_lin(rgb)
    lin *= gain
    if gain > 1:
        # weiche Schulter, damit Lichter nicht hart ausbrennen
        k = 0.85
        over = lin > k
        lin[over] = k + (1 - k) * np.tanh((lin[over] - k) / (1 - k))
    return lin_to_srgb(lin)


def process(src, dst, out16, target, extra_ev, green_filter=True):
    rgb, alpha = read_rgba(src)
    a, m = get_alpha(rgb, alpha, green_filter)
    del alpha
    ev = 0.0
    if target is not None:
        stat = luminance_stat(rgb, a)
        if stat:
            ev = float(np.clip(np.log2(target / stat), -EXPO_MAX_EV, EXPO_MAX_EV))
    ev += extra_ev
    rgb = despill(rgb, a, m)
    del m
    if abs(ev) > 0.01:
        rgb = apply_exposure(rgb, 2.0 ** ev)

    rgba = np.dstack([rgb[..., 2], rgb[..., 1], rgb[..., 0], a])  # BGRA
    del rgb, a
    np.clip(rgba, 0, 1, out=rgba)
    out = (rgba * 65535 + 0.5).astype(np.uint16) if out16 else (rgba * 255 + 0.5).astype(np.uint8)
    del rgba
    ok, buf = cv2.imencode(".png", out, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    if not ok:
        raise RuntimeError("PNG konnte nicht erzeugt werden")
    tmp = dst + ".part"
    with open(tmp, "wb") as f:
        f.write(png_with_icc(buf.tobytes(), read_icc(src)))
    os.replace(tmp, dst)
    return ev


def main():
    p = argparse.ArgumentParser(description="Greenscreen freistellen (Stapel)")
    p.add_argument("ordner")
    p.add_argument("--ziel")
    p.add_argument("--16bit", dest="out16", action="store_true")
    p.add_argument("--workers", type=int, default=0)
    p.add_argument("--nur", nargs="*")
    p.add_argument("--neu", action="store_true")
    p.add_argument("--referenz")
    p.add_argument("--ohne-belichtung", dest="no_expo", action="store_true")
    p.add_argument("--belichtung", type=float, default=0.0)
    p.add_argument("--ohne-gruenfilter", dest="no_gf", action="store_true")
    args = p.parse_args()

    src_dir = os.path.abspath(os.path.expanduser(args.ordner))
    dst_dir = os.path.abspath(os.path.expanduser(args.ziel or os.path.join(src_dir, "freigestellt")))
    os.makedirs(dst_dir, exist_ok=True)
    all_files = sorted(f for f in os.listdir(src_dir)
                       if os.path.splitext(f)[1].lower() in EXT and not f.startswith("."))
    files = [f for f in all_files if f in set(args.nur)] if args.nur else all_files
    jobs = []
    for f in files:
        dst = os.path.join(dst_dir, os.path.splitext(f)[0] + ".png")
        if os.path.exists(dst) and not args.neu:
            continue
        jobs.append((os.path.join(src_dir, f), dst))
    if not jobs:
        print("Nichts zu tun – alle Bilder sind schon verarbeitet (--neu zum Ueberschreiben).")
        return
    workers = args.workers or max(1, min(4, (os.cpu_count() or 2) // 2))

    # --- Belichtungs-Ziel bestimmen -----------------------------------------
    target = None
    if not args.no_expo:
        target_file = os.path.join(dst_dir, ".belichtung_ziel")
        if args.referenz:
            ref = os.path.join(src_dir, args.referenz) if not os.path.isabs(args.referenz) else args.referenz
            print(f"Messe Referenz {os.path.basename(ref)} …", flush=True)
            target = measure(ref, not args.no_gf)
        elif os.path.exists(target_file) and not args.neu:
            target = float(open(target_file).read().strip())
            print("Belichtungs-Ziel aus vorherigem Lauf uebernommen.")
        else:
            n = min(15, len(all_files))
            sample = [all_files[int(i * (len(all_files) - 1) / max(1, n - 1))] for i in range(n)]
            print(f"Messe Helligkeit an {n} Stichproben-Bildern …", flush=True)
            with ProcessPoolExecutor(max_workers=workers) as ex:
                vals = [v for v in ex.map(measure, [os.path.join(src_dir, f) for f in sample],
                                         [not args.no_gf] * len(sample)) if v]
            target = float(np.median(vals)) if vals else None
        if target:
            with open(target_file, "w") as f:
                f.write(str(target))

    print(f"{len(jobs)} Bilder → {dst_dir}  ({workers} parallel, {'16' if args.out16 else '8'} Bit, "
          f"Belichtung {'aus' if target is None else 'angleichen'})", flush=True)

    t0 = time.time()
    done = failed = 0
    log = open(os.path.join(dst_dir, "belichtung.csv"), "a")
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(process, s, d, args.out16, target, args.belichtung, not args.no_gf): s for s, d in jobs}
        for fut in as_completed(futs):
            name = os.path.basename(futs[fut])
            try:
                ev = fut.result()
                done += 1
                log.write(f"{name};{ev:+.2f}\n")
                log.flush()
                eta = (time.time() - t0) / (done + failed) * (len(jobs) - done - failed)
                print(f"[{done + failed}/{len(jobs)}] {name}  ok  {ev:+.2f} EV   (Rest ca. {eta / 60:.0f} min)",
                      flush=True)
            except Exception as e:
                failed += 1
                print(f"[{done + failed}/{len(jobs)}] {name}  FEHLER: {e}", flush=True)
    log.close()
    print(f"Fertig: {done} ok, {failed} Fehler, {(time.time() - t0) / 60:.1f} min")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
