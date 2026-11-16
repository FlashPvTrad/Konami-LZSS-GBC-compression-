"""
LZSS decompressor for the Konami GB Collection series (Game Boy).

The same stream format is used by Vol. 2 (routine at ROM $01E0), Vol. 3 ($070E)
and Vol. 4 ($0597). See konami_compression_format.md for the full specification.

    from decompress_konami import decompress_konami
    data, end = decompress_konami(rom_bytes, 0xE98B7)

    # command line
    python3 decompress_konami.py rom.gb E98B7 output.bin
"""


def decompress_konami(rom, start):
    """Decompress the stream starting at file offset `start`.

    Returns (data, end): the decompressed bytes and the file offset just past
    the end of the compressed stream.
    """
    pos = start
    c, b, sentinel = rom[pos], rom[pos + 1], rom[pos + 2]
    pos += 3
    total = (b << 8) | c            # output size (the BC register in the original code)
    out = bytearray(total)
    p = 0                           # write pointer
    remaining = total
    while remaining > 0:
        a = rom[pos]; pos += 1
        if a != sentinel:           # literal byte
            out[p] = a; p += 1; remaining -= 1
            continue
        e = rom[pos]; l1 = rom[pos + 1]; pos += 2   # back reference
        n = (l1 & 0x0F) + 4
        if (l1 & 0x0F) == 0x0F:                       # extended length
            n = rom[pos] + 0x13; pos += 1
        src = ((l1 >> 4) << 8) | e                    # ABSOLUTE position in the 4096-byte window
        for _ in range(n):
            if src >= total:                          # outside the output: circular 4096 window
                s2 = src - 0x1000
                if s2 >= 0:
                    val = out[s2]; src = s2
                else:
                    val = 0                           # before the start: zero
            else:
                val = out[src]
            out[p] = val; p += 1; src += 1; remaining -= 1
            if remaining == 0:                        # the stream can end in the middle of a copy
                break
    return bytes(out), pos


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 4:
        print("Usage: python3 decompress_konami.py <rom> <file_offset_hex> <output.bin>")
        sys.exit(1)
    rom = open(sys.argv[1], "rb").read()
    offset = int(sys.argv[2], 16)
    data, end = decompress_konami(rom, offset)
    open(sys.argv[3], "wb").write(data)
    print(f"{len(data)} bytes decompressed, compressed stream of {end - offset} bytes (end ${end:X})")
