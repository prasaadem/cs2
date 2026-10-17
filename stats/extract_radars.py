#!/usr/bin/env python3
"""Copy radar images and overview files for the maps you've played from a local CS2 install.

Usage:
    python stats/extract_radars.py [--cs2 "C:/Program Files (x86)/Steam"] [--out docs/radar] [--force]

Finds Steam (or use --cs2 with the Steam folder), reads Valve's .vpk archives
(pak01 for official maps, the workshop folder for community maps) and writes
docs/radar/<map>.png and docs/radar/<map>.txt for every map in data/games.
Then run build_site.py so the heatmaps pick them up. Nothing in the CS2 install is modified.
"""
import argparse
import glob
import json
import os
import re
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from vpk import VPK  # noqa: E402

STEAM_GUESSES = [r'C:\Program Files (x86)\Steam', r'C:\Program Files\Steam',
                 os.path.expanduser('~/.steam/steam'), os.path.expanduser('~/Library/Application Support/Steam')]


def steam_libraries(steam):
    libs = [steam]
    vdf = os.path.join(steam, 'steamapps', 'libraryfolders.vdf')
    if os.path.exists(vdf):
        with open(vdf, encoding='utf-8', errors='replace') as fh:
            libs += [p.replace('\\\\', '\\') for p in re.findall(r'"path"\s+"([^"]+)"', fh.read())]
    return list(dict.fromkeys(libs))


# ---------- texture decoding ----------

def lz4_block(src, size):
    out = bytearray()
    i, n = 0, len(src)
    while i < n and len(out) < size:
        tok = src[i]
        i += 1
        lit = tok >> 4
        if lit == 15:
            while True:
                x = src[i]
                i += 1
                lit += x
                if x != 255:
                    break
        out += src[i:i + lit]
        i += lit
        if i >= n or len(out) >= size:
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        ml = (tok & 15) + 4
        if (tok & 15) == 15:
            while True:
                x = src[i]
                i += 1
                ml += x
                if x != 255:
                    break
        st = len(out) - off
        if off >= ml:
            out += out[st:st + ml]
        else:  # overlapping copy (runs)
            for k in range(ml):
                out.append(out[st + k])
    return bytes(out)


def _rgb565(c):
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return [(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)]


def decode_dxt(data, w, h, dxt5):
    out = bytearray(w * h * 4)
    bs = 16 if dxt5 else 8
    p = 0
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            alpha = None
            if dxt5:
                a0, a1 = data[p], data[p + 1]
                bits = int.from_bytes(data[p + 2:p + 8], 'little')
                pal = [a0, a1] + ([((6 - k) * a0 + (k + 1) * a1) // 7 for k in range(6)] if a0 > a1
                                  else [((4 - k) * a0 + (k + 1) * a1) // 5 for k in range(4)] + [0, 255])
                alpha = [pal[(bits >> (3 * k)) & 7] for k in range(16)]
                q = p + 8
            else:
                q = p
            c0, c1 = struct.unpack('<HH', data[q:q + 4])
            idx = struct.unpack('<I', data[q + 4:q + 8])[0]
            e0, e1 = _rgb565(c0), _rgb565(c1)
            if c0 > c1 or dxt5:
                cols = [e0 + [255], e1 + [255], [(2 * a + b) // 3 for a, b in zip(e0, e1)] + [255],
                        [(a + 2 * b) // 3 for a, b in zip(e0, e1)] + [255]]
            else:
                cols = [e0 + [255], e1 + [255], [(a + b) // 2 for a, b in zip(e0, e1)] + [255], [0, 0, 0, 0]]
            for k in range(16):
                x, y = bx + (k & 3), by + (k >> 2)
                if x < w and y < h:
                    c = cols[(idx >> (2 * k)) & 3]
                    o = (y * w + x) * 4
                    out[o:o + 4] = bytes(c[:3] + [alpha[k] if alpha else c[3]])
            p += bs
    return bytes(out)


FORMATS = {1: 'DXT1', 2: 'DXT5', 4: 'RGBA8888', 28: 'BGRA8888'}


def decode_vtex(b):
    """Decode a compiled Source 2 texture (.vtex_c) to (width, height, RGBA bytes)."""
    _, _, _, boff, count = struct.unpack('<IHHII', b[:16])
    fsize = struct.unpack('<I', b[:4])[0]
    for i in range(count):
        p = 8 + boff + i * 12
        if b[p:p + 4] != b'DATA':
            continue
        d = p + 4 + struct.unpack('<I', b[p + 4:p + 8])[0]
        w, h = struct.unpack('<HH', b[d + 20:d + 24])
        fmt = b[d + 26]
        _, eoff, ecount = struct.unpack('<III', b[d + 28:d + 40])
        sizes = None
        for j in range(ecount):
            q = d + 32 + eoff + j * 12
            typ, off, _ = struct.unpack('<III', b[q:q + 12])
            if typ == 4:  # compressed mip sizes (LZ4), largest mip first in the list
                e = q + 4 + off
                _, o2, cnt = struct.unpack('<III', b[e:e + 12])
                sizes = struct.unpack('<%dI' % cnt, b[e + 4 + o2:e + 4 + o2 + 4 * cnt])
        if fmt not in FORMATS:
            raise ValueError(f'unsupported texture format {fmt}')
        full = w * h * 4 if fmt in (4, 28) else ((w + 3) // 4) * ((h + 3) // 4) * (16 if fmt == 2 else 8)
        data = b[fsize:]
        # mips are stored smallest first, so the full-size image is the last chunk
        raw = lz4_block(data[len(data) - sizes[0]:], full) if sizes else data[len(data) - full:]
        if fmt in (1, 2):
            return w, h, decode_dxt(raw, w, h, fmt == 2)
        if fmt == 28:
            px = bytearray(raw)
            px[0::4], px[2::4] = px[2::4], px[0::4]
            raw = bytes(px)
        return w, h, raw
    raise ValueError('no DATA block')


def write_png(path, w, h, rgba):
    rows = b''.join(b'\0' + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    with open(path, 'wb') as fh:
        fh.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
                 + chunk(b'IDAT', zlib.compress(rows, 9)) + chunk(b'IEND', b''))


# ---------- finding the files ----------

def radar_names(v, m):
    exact = [f'panorama/images/overheadmaps/{m}_radar_psd.vtex_c', f'panorama/images/overheadmaps/{m}_radar.vtex_c',
             f'panorama/images/overheadmaps/{m}_radar_tga.vtex_c']
    found = [n for n in exact if n in v.entries]
    if found:
        return found
    # workshop maps sometimes name or place it differently; skip lower/vanity layers
    return sorted((n for n in v.entries if n.endswith('.vtex_c') and f'{m}_radar' in n
                   and not any(x in n for x in ('_lower', '_vanity', '_preview', '_spectate'))), key=len)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--cs2', help='Steam folder (default: look in the usual places)')
    ap.add_argument('--out', default=os.path.join(HERE, '..', 'docs', 'radar'))
    ap.add_argument('--data', default=os.path.join(HERE, '..', 'data', 'games'))
    ap.add_argument('--force', action='store_true', help='overwrite radars already extracted')
    args = ap.parse_args()

    steam = args.cs2 or next((s for s in STEAM_GUESSES if os.path.isdir(s)), None)
    if not steam:
        sys.exit('error: Steam not found; pass --cs2 "<Steam folder>"')
    archives = []
    for lib in steam_libraries(steam):
        csgo = os.path.join(lib, 'steamapps', 'common', 'Counter-Strike Global Offensive', 'game', 'csgo')
        archives += [p for p in [os.path.join(csgo, 'pak01_dir.vpk')] if os.path.exists(p)]
        archives += sorted(glob.glob(os.path.join(csgo, 'maps', '*.vpk')))
        archives += sorted(glob.glob(os.path.join(lib, 'steamapps', 'workshop', 'content', '730', '*', '*.vpk')))
    if not archives:
        sys.exit(f'error: no CS2 files found under {steam}')

    maps = set()
    for f in glob.glob(os.path.join(args.data, '*.json')):
        with open(f, encoding='utf-8') as fh:
            maps.add(json.load(fh)['map'])
    os.makedirs(args.out, exist_ok=True)

    todo = {m for m in maps if args.force or not os.path.exists(os.path.join(args.out, m + '.png'))}
    print(f'{len(maps)} maps played, {len(todo)} to look for in {len(archives)} CS2 archives')
    found_txt, found_img = {}, {}
    for path in archives:
        if not todo - (set(found_txt) & set(found_img)):
            break
        name = os.path.basename(path).lower()
        # map packs are named after their map; skip unrelated per-map archives quickly
        if '/maps/' in path.replace('\\', '/') and not any(name.startswith(m) for m in todo):
            continue
        try:
            v = VPK(path)
        except (ValueError, OSError, struct.error):
            continue
        for m in todo:
            if m not in found_txt and f'resource/overviews/{m}.txt' in v.entries:
                found_txt[m] = v.read(f'resource/overviews/{m}.txt')
            if m not in found_img:
                for n in radar_names(v, m):
                    try:
                        found_img[m] = decode_vtex(v.read(n))
                        break
                    except ValueError as e:
                        print(f'  {m}: {n}: {e}')

    for m in sorted(maps):
        if m not in todo:
            print(f'  = {m} (already extracted)')
        elif m in found_txt and m in found_img:
            w, h, rgba = found_img[m]
            write_png(os.path.join(args.out, m + '.png'), w, h, rgba)
            with open(os.path.join(args.out, m + '.txt'), 'wb') as fh:
                fh.write(found_txt[m])
            print(f'  + {m} ({w}x{h})')
        else:
            missing = ' and '.join(x for x, ok in (('radar image', m in found_img), ('overview', m in found_txt)) if not ok)
            print(f'  - {m}: no {missing} in your CS2 install')


if __name__ == '__main__':
    main()
