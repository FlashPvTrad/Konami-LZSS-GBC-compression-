# Konami GB Collection: compression format specification

An escape-byte LZSS, shared by the *Konami GB Collection* compilations (Game Boy).
Volumes 2, 3 and 4 have been verified. The format was recovered by reverse engineering the
decompression routine and validated byte for byte against a real VRAM dump (Vol. 2, boot
screen stream at `$E98B7`), then tested on every stream found in the three ROMs.

It is an **LZSS / LZ77**: literal bytes plus back references into the output already produced.
Instead of one flag bit per group, an **escape byte (the "sentinel")** announces a reference.

## The routine in each volume

| | Vol. 2 | Vol. 3 | Vol. 4 |
|---|---|---|---|
| Address (bank 0, fixed) | `$01E0` | `$070E` | `$0597` |
| Source bank | passed in `C`; the routine switches bank itself (write to `$2100`) and restores it | the caller's bank | passed in `C`; same as Vol. 2 |
| Output writes | plain copy to `HL` | safe VRAM writes (waits through `$02D1`) | plain copy to `HL` |
| High-RAM variables | `$FFAC`-`$FFB5` | `$FF9D`-`$FFA6` | `$FFAC`-`$FFB5` |

The Vol. 4 routine is byte-identical to the Vol. 2 one except for the target of the final `JP`.
The stream format itself is the same in all three.

## Stream layout

```
[C] [B] [S]  sequence of codes...
```

| Byte | Role |
|---|---|
| `C`, `B` | **output** size: `total = (B << 8) \| C`. The stream ends when `total` bytes have been written, even in the middle of a copy |
| `S` | escape byte (`$02` in the reference stream; any value is possible) |

There is no terminator: only the byte counter matters.

## Codes

| Byte read | Meaning |
|---|---|
| `!= S` | **literal**: written as is |
| `= S` | **back reference**: `S  E  L1  [X]` |

A reference is decoded as follows:

- **offset** (12 bits) = `((L1 >> 4) << 8) | E`: an **absolute** position in the output buffer (0 = first byte written), not a relative distance
- **length** = `(L1 & 0x0F) + 4`, so 4 to 18; if `(L1 & 0x0F) == 0x0F`, one more byte `X` follows and the length is `X + 0x13`, so 19 to 274
- the copy is made **byte by byte**, so overlap is allowed: offset 0 on an initial `FF` fills a run of `FF`

### Circular 4096-byte window

For every byte copied, the source address `src` (relative to the start of the buffer) is handled like this:

- `src < total`: read `output[src]`
- `src >= total`: `src -= 4096`; if the result is `>= 0`, read `output[src]`, **otherwise write `$00`**

In practice, with `total = 2048`, any offset from 2048 to 4095 produces **zeros**. This is the way to
encode an empty run in 3 or 4 bytes.

## Example (start of the stream at `$E98B7`, Vol. 2)

```
00 08 02 | FF | 02 00 0F 07 | C3 FF DB FF DB | 02 00 07 | 8C FF B1 FF B3 ...
 total=$800 S=02  lit FF   ref off=0 len=7+19=26   lit x5      ref off=0 len=11   lit x5
```

The literal `FF` is copied 26 times (offset 0, overlapping), giving 27 `FF`; then 5 literals
(`C3 FF DB FF DB`) land at position 27; then 11 `FF` are copied back from position 0, and so on.
The result is 2048 bytes from a 527-byte stream.

## How the streams are referenced

- **Vol. 2 and Vol. 4:** the caller loads `DE` (pointer), `C` (bank) and `HL` (destination) and calls the
  routine, either with immediate values or through tables of 3-byte entries
  (`low address, high address, bank`). The Vol. 2 boot screen is loaded twice (to `$8000` and `$8800`) by
  bank `$1A` code through the tables at `$472B` and `$474C`.
- **Vol. 3:** the caller loads `DE` and `HL` immediately before the call, and the stream is in the caller's
  bank. A bank-0 loader (`$0980`) also goes through two-level tables to load level data into WRAM (`$C800`).

Streams are packed **back to back**: each one ends exactly where the next begins (for example, in Vol. 2
bank `$3A`, `E894E` ends at `E8BA9`, `E8BA9` ends at `E8D00`, and so on). The boot screen stream is
`E98B7`-`E9AC6` (527 bytes, 2048 decompressed).

## Reinserting a modified stream

A recompressed stream must **fit in the original space** (up to the start of the next stream): there is no
slack between streams. `compress_konami.py` produces the optimal stream for a given sentinel; across the
221 streams of the three volumes it fits in the original space in 214 cases (the others overflow by 1 or 2
bytes).

Measure the available space on the **original** ROM, and pad the rest of the range with zeros. The game
always writes `total` bytes, so do not shorten a stream's decompressed size even if its end is empty.
