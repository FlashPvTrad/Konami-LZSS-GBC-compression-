"""
Optimal LZSS compressor (dynamic programming) for the Konami GB Collection series.

Produces the shortest possible stream for a given sentinel (escape byte).
The output is not byte-identical to the original developers' tool (several valid
encodings exist) but always decompresses to the same data.
See konami_compression_format.md for the format specification.

    from compress_konami import compress_konami
    packed = compress_konami(data)          # data: bytes (e.g. 2048 bytes of tiles)

    # command line
    python3 compress_konami.py input.bin output.bin
"""
import numpy as np

MAXLEN = 0x13 + 0xFF        # 274: longest possible reference
WINDOW = 4096               # 12-bit offsets (absolute positions)


def _encode(data, sentinel):
    n = len(data)
    arr = np.frombuffer(data, dtype=np.uint8)
    INF = 10 ** 9

    # longest match (overlap allowed) for each position
    lmax = [0] * n
    sbest = [0] * n
    prev = np.zeros(n + 2, dtype=np.int32)
    for i in range(n - 1, -1, -1):
        row = np.zeros(n + 2, dtype=np.int32)
        if i > 0:
            eq = arr[:i] == arr[i]
            row[:i] = eq * (prev[1:i + 1] + 1)
            lim = min(i, WINDOW)
            k = int(row[:lim].argmax())
            lmax[i] = min(int(row[k]), MAXLEN)
            sbest[i] = k
        prev = row

    # a reference to "before the start" (offset >= size) produces zeros
    zrun = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        zrun[i] = zrun[i + 1] + 1 if data[i] == 0 else 0
    zmax = min(MAXLEN, WINDOW - n) if n < WINDOW else 0

    best = [INF] * (n + 1)
    choice = [None] * (n + 1)
    best[n] = 0
    for i in range(n - 1, -1, -1):
        if data[i] != sentinel:                     # a literal cannot equal the sentinel
            best[i], choice[i] = 1 + best[i + 1], ("lit",)
        lm, zm = lmax[i], min(zrun[i], zmax)
        for L in range(4, max(lm, zm, 3) + 1):
            if i + L > n:
                break
            cost = (3 if L <= 18 else 4) + best[i + L]
            if cost < best[i]:
                best[i] = cost
                choice[i] = ("m", L, sbest[i] if L <= lm else n)
    if best[0] >= INF:
        return None
    out = bytearray([n & 0xFF, n >> 8, sentinel])
    i = 0
    while i < n:
        ch = choice[i]
        if ch[0] == "lit":
            out.append(data[i]); i += 1
        else:
            _, L, s = ch
            out += bytes([sentinel, s & 0xFF])
            if L <= 18:
                out.append(((s >> 8) << 4) | (L - 4))
            else:
                out += bytes([((s >> 8) << 4) | 0x0F, L - 19])
            i += L
    return bytes(out)


def compress_konami(data, sentinel=None):
    """Compress `data` (bytes). If `sentinel` is None, the best of the four least
    frequent byte values is used."""
    if len(data) > 0xFFFF:
        raise ValueError("maximum size is 65535 bytes")
    if sentinel is not None:
        r = _encode(data, sentinel)
        if r is None:
            raise ValueError("this sentinel cannot be used with this data")
        return r
    freq = [0] * 256
    for b in data:
        freq[b] += 1
    results = [r for r in (_encode(data, s) for s in sorted(range(256), key=lambda v: freq[v])[:4]) if r]
    return min(results, key=len)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python3 compress_konami.py <input.bin> <output.bin>")
        sys.exit(1)
    data = open(sys.argv[1], "rb").read()
    out = compress_konami(data)
    open(sys.argv[2], "wb").write(out)
    print(f"{len(data)} -> {len(out)} bytes")
