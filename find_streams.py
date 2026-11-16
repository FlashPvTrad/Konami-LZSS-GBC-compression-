"""
find_streams.py: find the compressed streams (Konami GB Collection LZSS) in a ROM.

Method: locate the CALLs to the decompression routine, read the registers loaded
just before them (DE = pointer, C = bank, HL = destination) or the 3-byte pointer
tables (low address, high address, bank), validate every stream with a strict
decoder, then extend the list by chaining (a stream ends exactly where the next
one begins).

Usage:
    python3 find_streams.py rom.gb  01E0 catalog.csv                 # Vol. 2
    python3 find_streams.py rom.gbc 070E catalog.csv --same-bank     # Vol. 3
    python3 find_streams.py rom.gbc 0597 catalog.csv                 # Vol. 4

The address is that of the decompression routine: $01E0 (Vol. 2), $070E (Vol. 3),
$0597 (Vol. 4). Vol. 3 uses a variant that receives no bank register: the stream
is in the caller's bank, hence --same-bank.
"""
import re, sys


def strict_decode(rom, start, maxtotal=0x4000):
    """Decode while checking consistency. Returns (total, end, data, refs) or None.

    A stream is rejected if a reference reads a byte that has not been written yet,
    which almost never happens in a genuine stream but very often in random data.
    """
    if start + 4 > len(rom):
        return None
    c, b, s = rom[start], rom[start + 1], rom[start + 2]
    total = (b << 8) | c
    if total < 16 or total > maxtotal:
        return None
    pos = start + 3
    out = bytearray(total)
    p = 0
    rem = total
    refs = 0
    try:
        while rem > 0:
            a = rom[pos]; pos += 1
            if a != s:
                out[p] = a; p += 1; rem -= 1
                continue
            e = rom[pos]; l1 = rom[pos + 1]; pos += 2
            n = (l1 & 0x0F) + 4
            if (l1 & 0x0F) == 0x0F:
                n = rom[pos] + 0x13; pos += 1
            src = ((l1 >> 4) << 8) | e
            refs += 1
            for _ in range(n):
                if src >= total:
                    s2 = src - 0x1000
                    if s2 >= 0:
                        if s2 >= p:
                            return None
                        val = out[s2]; src = s2
                    else:
                        val = 0
                else:
                    if src >= p:
                        return None
                    val = out[src]
                out[p] = val; p += 1; src += 1; rem -= 1
                if rem == 0:
                    break
    except IndexError:
        return None
    return total, pos, bytes(out), refs


def fo(bank, ptr):
    """(bank, CPU address in $4000-$7FFF) -> file offset."""
    return bank * 0x4000 + (ptr - 0x4000) if ptr >= 0x4000 else ptr


def find_refs(rom, entry, same_bank=False):
    sig = bytes([0xCD, entry & 0xFF, entry >> 8])           # CALL entry
    sites = [i for i in range(len(rom) - 2) if rom[i:i + 3] == sig]
    refs = []          # (stream_offset, kind, where, destination, detail)
    tables = {}        # (code_bank, table_base_address) -> destination
    skipped = []       # calls whose registers could not be read
    for s in sites:
        ctx = rom[max(0, s - 60):s]
        hl = None
        for k in range(len(ctx) - 3, len(ctx) - 14, -1):    # destination: last "LD HL,nn"
            if k >= 0 and ctx[k] == 0x21:
                hl = ctx[k + 1] | (ctx[k + 2] << 8)
                break
        code_bank = s // 0x4000
        if same_bank:
            # Vol. 3: "LD DE,nn / LD HL,nn / CALL" (or the reverse), stream in the caller's bank
            t6 = rom[s - 6:s]
            de2 = hl2 = None
            if len(t6) == 6 and t6[0] == 0x11 and t6[3] == 0x21:
                de2, hl2 = t6[1] | (t6[2] << 8), t6[4] | (t6[5] << 8)
            elif len(t6) == 6 and t6[0] == 0x21 and t6[3] == 0x11:
                hl2, de2 = t6[1] | (t6[2] << 8), t6[4] | (t6[5] << 8)
            if de2 is not None and 0x4000 <= de2 < 0x8000:
                refs.append((fo(code_bank, de2), 'direct', s, hl2, f'DE={de2:04X} bank={code_bank:02X}'))
                continue
        de = c = None
        for k in range(len(ctx) - 2, max(len(ctx) - 26, -1), -1):
            if ctx[k] == 0x11 and de is None:               # LD DE,nn
                de = ctx[k + 1] | (ctx[k + 2] << 8)
            if ctx[k] == 0x0E and c is None and k + 1 < len(ctx):   # LD C,n (bank)
                c = ctx[k + 1]
        tail = bytes(ctx[-24:])
        if b'\x19\x5e\x23\x56\x23\x4e' in tail and de is not None:
            tables[(code_bank, de)] = hl                   # indexed table: ADD HL,DE / LD E,(HL) ...
        elif b'\x2a\x5f\x2a\x57\x4e' in tail:              # table read with LD A,(HL+)
            mm = [i for i in range(len(ctx) - 30, len(ctx) - 5)
                  if i >= 0 and ctx[i] == 0x21 and ctx[i + 3:i + 5] == b'\x85\x6f']
            if mm:
                i = mm[-1]
                tables[(code_bank, ctx[i + 1] | (ctx[i + 2] << 8))] = hl
            else:
                skipped.append(s)
        elif de is not None and c is not None and 0x4000 <= de < 0x8000 and c < 0x40:
            refs.append((fo(c, de), 'direct', s, hl, f'DE={de:04X} bank={c:02X}'))
        else:
            skipped.append(s)
    # read each table sequentially until an entry stops being a valid stream
    for (bank, base), dest in sorted(tables.items()):
        off = bank * 0x4000 + (base - 0x4000)
        for i in range(64):
            e = off + i * 3
            ptr = rom[e] | (rom[e + 1] << 8)
            bk = rom[e + 2]
            if not (0x4000 <= ptr < 0x8000 and bk < 0x40):
                break
            st = fo(bk, ptr)
            if strict_decode(rom, st) is None:
                break
            refs.append((st, 'table', e, dest, f'table {base:04X}@bank{bank:02X} [{i}]'))
    return sites, refs, tables, skipped


def build(rom, refs):
    """Validate the referenced streams, then extend by chaining (forward and backward)."""
    streams = {}
    for st, kind, where, dest, detail in refs:
        r = strict_decode(rom, st)
        if r is None:
            continue
        d = streams.setdefault(st, dict(end=r[1], total=r[0], dests=set(), src=[]))
        d['dests'].add(dest)
        d['src'].append(detail)
    changed = True
    while changed:                                  # forward: a stream right after a known one
        changed = False
        for st in list(streams):
            e = streams[st]['end']
            if e not in streams:
                r = strict_decode(rom, e)
                if r and r[3] >= 1 and (r[1] - e) < r[0]:
                    streams[e] = dict(end=r[1], total=r[0], dests=set(), src=[f'chained after {st:X}'])
                    changed = True
    for st in sorted(list(streams)):                # backward: a stream ending exactly at a known start
        for o in range(max(0, st - 0x1300), st):
            r = strict_decode(rom, o)
            if r and r[1] == st and r[3] >= 1 and o not in streams and (r[1] - o) < r[0]:
                streams[o] = dict(end=r[1], total=r[0], dests=set(), src=[f'chained before {st:X}'])
    return streams


def _dest_name(d):
    if d in (0x8000, 0x8800, 0x9000, 0x9700):
        return f"${d:04X} tiles"
    if d in (0x9800, 0x9C00):
        return f"${d:04X} BG map"
    if d is not None and d >= 0xC000:
        return f"${d:04X} WRAM"
    return ""


def main():
    import csv
    from decompress_konami import decompress_konami
    same_bank = '--same-bank' in sys.argv
    args = [a for a in sys.argv if a != '--same-bank']
    if len(args) != 4:
        print(__doc__)
        sys.exit(1)
    rom = open(args[1], "rb").read()
    entry = int(args[2], 16)
    sites, refs, tables, skipped = find_refs(rom, entry, same_bank)
    streams = build(rom, refs)
    referenced = {r[0] for r in refs}
    spans = {s: v["end"] for s, v in streams.items()}
    rows = []
    for st in sorted(streams):
        v = streams[st]
        data, end = decompress_konami(rom, st)
        if st in referenced:
            conf = "certain (referenced by the code)"
        else:
            clash = [t for t in referenced if t != st and t in spans and spans[t] > st and t < end]
            conf = ("doubtful (overlaps a certain stream)" if clash or v["total"] * 0.97 < end - st
                    else "probable (chained to a certain stream)")
        dests = " / ".join(x for x in (_dest_name(d) for d in sorted(d for d in v["dests"] if d)) if x)
        rows.append(dict(start=f"{st:06X}", end=f"{end:06X}", bank=f"{st // 0x4000:02X}",
                         compressed=end - st, decompressed=len(data), tiles=f"{len(data) / 16:g}",
                         destination=dests or "unknown", confidence=conf))
    with open(args[3], "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(sites)} calls, {len(rows)} streams ({sum(r['compressed'] for r in rows)} -> "
          f"{sum(r['decompressed'] for r in rows)} bytes) -> {args[3]}")
    if skipped:
        print("unresolved calls (registers loaded too far from the CALL): "
              + ", ".join(f"${x:X}" for x in skipped))


if __name__ == "__main__":
    main()
