**LZSS decompressor and compressor for the *Konami GB Collection* series (Game Boy)**

![Format](https://img.shields.io/badge/format-LZSS-blue)
![Language](https://img.shields.io/badge/language-Python-green)
![Platform](https://img.shields.io/badge/platform-Game%20Boy-lightgrey)
![Volumes](https://img.shields.io/badge/volumes%20verified-2%2C%203%20and%204-orange)
![Streams](https://img.shields.io/badge/streams%20cataloged-221-informational)

</div>

The **Konami GB Collection** compilations store their tiles, background maps and some level data in a **shared compression format**: an escape-byte LZSS with a 4096-byte window and absolute-position references.

This repository documents that format, which was recovered by reverse engineering, and provides a **decompressor**, an **optimal compressor** and a **stream finder** in Python, so you can extract, edit and reinsert the graphics.

| Volume | Decompression routine | Validation | Streams cataloged |
|---|---|---|---|
| **Vol. 2** | `$01E0` | ✅ byte for byte against a real VRAM dump | 82 |
| **Vol. 3** | `$070E` (variant, same rules) | ✅ every referenced stream decodes cleanly and the streams run back to back | 29 |
| **Vol. 4** | `$0597` (byte-identical to Vol. 2 except the final `JP` target) | ✅ same | 110 |
| Vol. 1 and later | — | ⏳ not verified | — |

---

## Contents

- [At a glance](#at-a-glance)
- [The format](#the-format)
- [Installation and usage](#installation-and-usage)
- [Editing graphics: the workflow](#editing-graphics-the-workflow)
- [Finding the streams in a ROM](#finding-the-streams-in-a-rom)
- [Results and validation](#results-and-validation)
- [Where the data lives](#where-the-data-lives)
- [Known limitations](#known-limitations)
- [Repository layout](#repository-layout)
- [Legal notice](#legal-notice)

---

## At a glance

| | |
|---|---|
| **Family** | LZSS / LZ77 with an **escape byte** (no flag bits) |
| **Window** | 4096 bytes, 12-bit offsets as **absolute positions** in the output |
| **Match length** | 4 to 274 bytes |
| **Output size** | stored in the header (16 bits), no terminator |
| **Decompression routine** | `$01E0` (Vol. 2), `$070E` (Vol. 3), `$0597` (Vol. 4), always in bank 0 |
| **Contents** | 2 bpp tiles, background maps, some level data copied to work RAM |

The format departs from classic LZSS in two ways. References are **absolute positions** in the output buffer, not distances, and the part of the window "before the start" reads as **zeros**, which lets an empty run be encoded in 3 or 4 bytes.

### The three routines

| | Vol. 2 | Vol. 3 | Vol. 4 |
|---|---|---|---|
| Address | `$01E0` | `$070E` | `$0597` |
| Source bank | passed in `C`, the routine switches banks itself (`$2100`) | the caller's bank (the bank-0 loader switches banks itself) | passed in `C`, the routine switches banks itself |
| Output writes | plain copy | **safe VRAM writes** (waits through `$02D1`) | plain copy |
| High-RAM variables | `$FFAC`–`$FFB5` | `$FF9D`–`$FFA6` | `$FFAC`–`$FFB5` |
| Data format | identical | identical | identical |

---

## The format

### Header

```
┌────┬────┬─────┬───────────────────────────────┐
│ C  │ B  │  S  │  codes ...                     │
└────┴────┴─────┴───────────────────────────────┘
```

| Byte | Role |
|---|---|
| `C`, `B` | **output** size, little-endian: `total = (B << 8) \| C` |
| `S` | escape byte ("sentinel"). Any value is allowed; `$02` in the reference stream |

The stream ends once `total` bytes have been written, **even in the middle of a copy**. There is no end marker.

### Codes

| Byte read | Meaning |
|---|---|
| `≠ S` | **literal**: written as is |
| `= S` | **back reference**: `S  E  L1  [X]` |

```
reference:    S   E   L1  [X]
                  │   │    └─ present only if (L1 & 0x0F) == 0x0F
                  │   └────── high nibble: offset bits 11..8
                  │           low nibble:  length - 4   (0..14), or 0xF = extended mode
                  └────────── offset bits 7..0
```

- **offset** = `((L1 >> 4) << 8) | E`: an **absolute** position in the output buffer (0 = first byte written)
- **length** = `(L1 & 0x0F) + 4`, so 4 to 18; if the low nibble is `0xF`, the length is `X + 0x13`, so 19 to 274
- copies are made **byte by byte**, so overlap is allowed (offset 0 on an initial `FF` fills a run of `FF`)

### 4096-byte circular window

For every byte copied, the source address `src` (relative to the start of the buffer) is handled like this:

| Condition | Effect |
|---|---|
| `src < total` | read `output[src]` |
| `src >= total` | `src -= 4096`; if `src >= 0` read `output[src]`, **otherwise write `$00`** |

With `total = 2048`, any offset from 2048 to 4095 therefore produces zeros. This is the native way to encode an empty area.

### Reference decoder

```python
def decompress_konami(rom, start):
    pos = start
    c, b, sentinel = rom[pos], rom[pos + 1], rom[pos + 2]
    pos += 3
    total = (b << 8) | c
    out = bytearray(total)
    p, remaining = 0, total
    while remaining > 0:
        a = rom[pos]; pos += 1
        if a != sentinel:                       # literal
            out[p] = a; p += 1; remaining -= 1
            continue
        e, l1 = rom[pos], rom[pos + 1]; pos += 2
        n = (l1 & 0x0F) + 4
        if (l1 & 0x0F) == 0x0F:                 # extended length
            n = rom[pos] + 0x13; pos += 1
        src = ((l1 >> 4) << 8) | e              # absolute position
        for _ in range(n):
            if src >= total:                    # circular window
                s2 = src - 0x1000
                if s2 >= 0:
                    val = out[s2]; src = s2
                else:
                    val = 0                     # before the start: zero
            else:
                val = out[src]
            out[p] = val; p += 1; src += 1; remaining -= 1
            if remaining == 0:
                break
    return bytes(out), pos
```

### Worked example

Start of the Vol. 2 boot screen stream (file offset `$E98B7`):

```
00 08 02 | FF | 02 00 0F 07 | C3 FF DB FF DB | 02 00 07 | 8C FF B1 FF B3 ...
total=$0800 S=02  literal     ref off=0         5 literals   ref off=0       5 literals
                  FF          len=7+19=26       at pos 27    len=(7)+4=11
```

The initial `FF` is copied 26 times from position 0 (overlapping copy), giving 27 `FF` in a row. The next five literals land at position 27, then 11 `FF` are copied back from the start, and so on. The result is 2048 bytes from a 527-byte stream.

---

## Installation and usage

The decompressor and the stream finder have no dependencies. The compressor uses `numpy`.

```bash
git clone https://github.com/<you>/konami-gb-lzss.git
cd konami-gb-lzss
pip install numpy
```

### Decompress a stream from a ROM

```bash
python3 decompress_konami.py rom.gb E98B7 output.bin
# 2048 bytes decompressed, compressed stream of 527 bytes (end $E9AC6)
```

The offset is a **file offset** in hexadecimal. The output is raw binary, ready to open in a tile editor (Game Boy 2 bpp). The same decoder works for Vol. 2, 3 and 4.

### Compress a file

```bash
python3 compress_konami.py output.bin recompressed.bin
# 2048 -> 493 bytes
```

### From Python

```python
from decompress_konami import decompress_konami
from compress_konami import compress_konami

rom = open("rom.gb", "rb").read()
data, end = decompress_konami(rom, 0xE98B7)
packed = compress_konami(data)

assert decompress_konami(packed, 0)[0] == data        # round trip guaranteed
print(len(packed), "bytes, space available:", end - 0xE98B7)
```

### The compressor

`compress_konami.py` computes the **optimal parse** with dynamic programming:

- longest match at each position, using a longest-common-prefix table (`numpy`), overlap included;
- a "zeros" option: a reference outside the output produces zeros, used for empty runs;
- automatic choice of the sentinel among the least frequent byte values in the data (a value that never occurs avoids any forbidden literal).

The result is the **shortest possible** stream for a given sentinel. It is not byte-identical to what the original developers' tool produced (several valid encodings exist), but it always decompresses to identical data.

---

## Editing graphics: the workflow

1. **Decompress** the stream you want (`decompress_konami.py`).
2. **Edit** the `.bin` in a tile editor (for example Tile Molester, Game Boy 2 bpp format). Do not change the file size.
3. **Recompress** (`compress_konami.py`) and compare with the available space.
4. **Reinsert** at the original offset, filling the rest of the range with zeros.
5. **Verify**: decompress the modified ROM and compare with your file, then check that no byte changed outside the range.

```python
rom = bytearray(open("rom.gb", "rb").read())
S = 0xE98B7
_, end = decompress_konami(bytes(rom), S)
space = end - S

packed = compress_konami(open("modified.bin", "rb").read())
assert len(packed) <= space, f"too big by {len(packed) - space} bytes"

rom[S:S + len(packed)] = packed
rom[S + len(packed):end] = bytes(space - len(packed))
open("modified_rom.gb", "wb").write(rom)
```

**Important.** Streams are packed **back to back**, with no slack: a stream that grows would overwrite its neighbor. Always measure the available space on the original ROM, not on an already modified one (a shortened stream reports less space than is really there).

**If the stream does not fit**, there is still one way out: place it in a free block of the ROM and update whatever points to it. In Vol. 2 and Vol. 4, the code loads its streams through 3-byte pointer tables (`low address, high address, bank`) or through registers loaded right before the call. In Vol. 3 the pointer is a 16-bit `LD DE` in the caller's bank, so relocation is more constrained there.

**If you only edit tiles and not their count**, remember that the game always writes `total` bytes into VRAM: do not shorten the file even if its end is empty. Pad with zeros to keep the original behavior.

---

## Finding the streams in a ROM

`find_streams.py` locates the calls to the decompression routine, reads the registers or pointer tables that precede them, validates every stream with a strict decoder, then extends the list by chaining (a stream ends exactly where the next one begins).

```bash
python3 find_streams.py rom_vol2.gb  01E0 catalog_vol2.csv
python3 find_streams.py rom_vol3.gbc 070E catalog_vol3.csv --same-bank   # Vol. 3: no bank register
python3 find_streams.py rom_vol4.gbc 0597 catalog_vol4.csv
# 60 calls, 110 streams (56826 -> 118757 bytes) -> catalog_vol4.csv
```

To find the routine address in another ROM, search for the header sequence `1A 4F 13 1A 47 13 1A E0` (reading `C`, then `B`, then the sentinel from `(DE)`): the routine starts just before it.

The CSV gives, for each stream, its `start`, `end`, `bank`, `compressed` and `decompressed` sizes, `tiles`, `destination` (`$8000`–`$97FF` tiles, `$9800`/`$9C00` background maps, `$C800` WRAM) and a `confidence` level:

- **certain**: referenced by the code;
- **probable**: directly adjacent to a certain stream;
- **doubtful**: overlaps a certain stream, probably a false positive.

The catalogs in this repository also include the columns `zeros_pct`, `recompressed` (size after recompression), `fits` (does the recompressed stream fit in the original space) and `roundtrip` (decompression of the recompressed stream equals the original).

---

## Results and validation

| | Vol. 2 | Vol. 3 | Vol. 4 | Total |
|---|---|---|---|---|
| Calls to the routine | 25 | 25 | 60 | |
| Streams cataloged | 82 | 29 | 110 | **221** |
| Compressed bytes | 37,567 | 21,611 | 56,826 | 116,004 |
| Decompressed bytes | 91,104 | 37,928 | 118,757 | 247,789 |
| Certain / probable / doubtful | 71 / 4 / 7 | 25 / 2 / 2 | 80 / 21 / 9 | |
| Compressor round trip | 82 / 82 | 29 / 29 | 110 / 110 | **221 / 221** |
| Fit in the original space | 80 / 82 | 26 / 29 | 108 / 110 | **214 / 221** |

- **Vol. 2: reference validation.** The decoder reproduces a real VRAM dump of the boot screen byte for byte (2048 of 2048 bytes, including the second copy at `$8800`). The `$E98B7` stream goes from 527 to 493 bytes.
- **Vol. 3 and Vol. 4:** no VRAM dump, but every referenced stream decodes with the **strict** decoder (no read of a byte that has not been written yet) and the streams follow each other back to back. The Vol. 4 routine is identical to the Vol. 2 one; the Vol. 3 routine applies the same rules with a safe VRAM write.
- **Streams that do not fit** overflow by 1 to 2 bytes: `$77300` and `$E9B27` (Vol. 2); `$32CBA`, `$32FB9` and `$35F4A` (Vol. 3); `$E5570` and `$E5641` (Vol. 4). Since the compressor is optimal for a given sentinel, you have to relocate the stream or reduce your edits.

---

## Where the data lives

The streams were found from the calls to the routine, then by chaining. Offsets are **file offsets**, specific to the dumps studied.

| Volume | Banks | Contents |
|---|---|---|
| **Vol. 2** | `$3A` (33 contiguous streams), `$1F` (38), `$16`/`$17` (4), `$1A`, `$1C`, `$1D` | tiles (`$8000`, `$8800`, `$9000`), background maps, 8 streams going to WRAM |
| **Vol. 3** | `$0B` (11 streams), `$0C` (5), `$0D` (13) | tiles, background maps, 7 streams going to WRAM (`$C800`, level data) |
| **Vol. 4** | `$19` (4), `$1D` (17), `$1F` (32), `$39` (31), `$3D` (13), `$3E` (13) | mostly tiles and background maps, a few streams going to WRAM |

Full catalogs: [`konami_vol2_streams_catalog.csv`](konami_vol2_streams_catalog.csv), [`konami_vol3_streams_catalog.csv`](konami_vol3_streams_catalog.csv) and [`konami_vol4_streams_catalog.csv`](konami_vol4_streams_catalog.csv).

---

## Known limitations

- **Verified volumes: 2, 3 and 4.** Vol. 1 and any later volumes have not been checked. The routine is probably the same there, or a variant, but this is not proven.
- **Only Vol. 2 is validated against a VRAM dump.** For Vol. 3 and 4 the evidence is indirect (strict decoding, chaining, and, for Vol. 4, an identical routine).
- **Unresolved calls.** Some calls load their registers too far from the `CALL` to be read automatically: 3 of 25 (Vol. 2), 2 of 25 (Vol. 3, including `$12C59`, which is probably data rather than code), 6 of 60 (Vol. 4). The streams involved are largely recovered through chaining, but not necessarily all of them. In Vol. 3, a bank-0 loader (`$0980`) goes through two-level tables that were only followed for bank `$0D`.
- **Vol. 3 table-referenced streams.** `find_streams.py` does not read the header table of bank `$0D` used by the bank-0 loader, so the 5 streams it references (`$342CC`, `$346C5`, `$34AC5`, `$34EB2`, `$35287`) show up as *probable*. The Vol. 3 catalog in this repository marks them *certain* (`bank 0D table`).
- **False positives are possible.** A blind scan of a whole ROM produces many bogus streams (data tables that happen to "decode cleanly"). Only streams referenced by the code, or chained to a certain stream, are cataloged.
- **Dumps differ.** Two dumps of the same compilation can differ by about 1 KB (this is the case for Vol. 2). Recheck the offsets with `find_streams.py` on your own dump.
- **Not a clone of the original tool.** The streams the compressor produces are valid and usually shorter, but they are not identical to the developers' streams.
- **Relocation outside the range is untested on real hardware.** Moving a stream assumes the destination bank is readable by the cartridge.
- The catalog does not say which game of the compilation each stream belongs to.

---

## Repository layout

```
.
├── README.md                           this file
├── decompress_konami.py                decompressor (no dependencies)
├── compress_konami.py                  optimal compressor (numpy)
├── find_streams.py                     stream finder for a ROM (no dependencies)
├── konami_compression_format.md        detailed format specification
├── konami_vol2_streams_catalog.csv     Vol. 2 catalog (82 streams)
├── konami_vol3_streams_catalog.csv     Vol. 3 catalog (29 streams)
├── konami_vol4_streams_catalog.csv     Vol. 4 catalog (110 streams)
└── LICENSE                             to be added (MIT suggested for the code)
```

---

## Legal notice

This repository **contains no ROM and no data extracted from a ROM**. It only provides a description of the format and tools that apply to a copy of the cartridge that you own legitimately.

*Game Boy* and *Nintendo* are trademarks of Nintendo Co., Ltd.; *Konami* is a trademark of Konami Group Corporation. This project is not affiliated with either company. It is published for research, preservation and interoperability purposes.
