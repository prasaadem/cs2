"""Minimal reader for Valve VPK (v1/v2) archives, enough to list and extract files."""
import os
import struct


class VPK:
    def __init__(self, path):
        self.path = path
        self.entries = {}
        with open(path, 'rb') as fh:
            sig, ver = struct.unpack('<II', fh.read(8))
            if sig != 0x55AA1234:
                raise ValueError(f'{path}: not a VPK file')
            tree_size = struct.unpack('<I', fh.read(4))[0]
            if ver == 2:
                fh.read(16)  # file data / archive md5 / other md5 / signature section sizes
                header = 28
            else:
                header = 12
            tree = fh.read(tree_size)
        self.data_start = header + tree_size
        self._parse(tree)

    def _parse(self, tree):
        pos = 0

        def cstr():
            nonlocal pos
            end = tree.index(b'\0', pos)
            s = tree[pos:end].decode('utf-8', 'replace')
            pos = end + 1
            return s

        while True:
            ext = cstr()
            if not ext:
                break
            while True:
                folder = cstr()
                if not folder:
                    break
                while True:
                    name = cstr()
                    if not name:
                        break
                    crc, preload, arc, off, length, term = struct.unpack('<IHHIIH', tree[pos:pos + 18])
                    pos += 18
                    pre = tree[pos:pos + preload]
                    pos += preload
                    folder_ = '' if folder == ' ' else folder + '/'
                    self.entries[f'{folder_}{name}.{ext}'.lower()] = (arc, off, length, pre)

    def read(self, name):
        arc, off, length, pre = self.entries[name.lower()]
        if length == 0:
            return pre
        if arc == 0x7FFF:
            src, off = self.path, self.data_start + off
        else:
            src = self.path.replace('_dir.vpk', '_%03d.vpk' % arc)
        with open(src, 'rb') as fh:
            fh.seek(off)
            return pre + fh.read(length)

    def find(self, *needles):
        return [n for n in self.entries if all(x in n for x in needles)]


if __name__ == '__main__':
    import sys
    v = VPK(sys.argv[1])
    for n in (v.find(*sys.argv[2:]) if len(sys.argv) > 2 else list(v.entries)[:50]):
        print(n, v.entries[n][2])
    print(len(v.entries), 'entries', file=sys.stderr)
