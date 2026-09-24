"""IMA/DVI-4 ADPCM encoder and Baichuan talk packet framing.

The camera speaker is fed with ADPCM blocks. Each block starts with a
4 byte header (first sample as int16, step index, one reserved byte)
followed by two 4-bit codes per byte. The packet format follows the open
source neolink project (talk.rs, bcmedia serializer).
"""

from __future__ import annotations

import struct
from typing import List

_STEP = [
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41,
    45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190,
    209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796,
    876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499,
    2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845,
    8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350,
    22385, 24623, 27086, 29794, 32767,
]
_INDEX_ADJUST = [-1, -1, -1, -1, 2, 4, 6, 8]

PACKET_MAGIC = b"01wb"
PACKET_DATA_MAGIC = 0x0100
PACKET_PAD = 8          # media packets are padded to a multiple of 8 bytes
BLOCK_HEADER_SIZE = 4


def encode_block(samples: List[int], index: int = 0) -> tuple[bytes, int]:
    """Encode one ADPCM block.

    ``samples[0]`` is stored verbatim in the block header, every following
    sample becomes a 4-bit code. Returns the block and the final step index.
    """
    predictor = samples[0]
    out = bytearray(struct.pack("<hBB", predictor, index, 0))
    codes = []
    for sample in samples[1:]:
        step = _STEP[index]
        diff = sample - predictor
        code = 0
        if diff < 0:
            code = 8
            diff = -diff
        delta = step >> 3
        if diff >= step:
            code |= 4
            diff -= step
            delta += step
        step >>= 1
        if diff >= step:
            code |= 2
            diff -= step
            delta += step
        step >>= 1
        if diff >= step:
            code |= 1
            delta += step
        predictor += -delta if code & 8 else delta
        predictor = max(-32768, min(32767, predictor))
        index = max(0, min(88, index + _INDEX_ADJUST[code & 7]))
        codes.append(code)
    if len(codes) % 2:
        codes.append(0)
    for i in range(0, len(codes), 2):
        out.append(codes[i] | (codes[i + 1] << 4))
    return bytes(out), index


def pcm_to_samples(pcm: bytes) -> List[int]:
    """Convert 16-bit little endian PCM bytes to a list of ints."""
    usable = len(pcm) - len(pcm) % 2
    return list(struct.unpack(f"<{usable // 2}h", pcm[:usable]))


def encode_pcm(pcm: bytes, length_per_encoder: int = 1024) -> List[bytes]:
    """Encode PCM into ADPCM blocks of ``length_per_encoder`` samples.

    Every block carries one extra sample in its header, so a block covers
    ``length_per_encoder + 1`` input samples. The last block is zero padded.
    """
    samples = pcm_to_samples(pcm)
    per_block = length_per_encoder + 1
    blocks: List[bytes] = []
    index = 0
    for offset in range(0, len(samples), per_block):
        chunk = samples[offset:offset + per_block]
        chunk += [0] * (per_block - len(chunk))
        block, index = encode_block(chunk, index)
        blocks.append(block)
    return blocks


def frame_block(block: bytes) -> bytes:
    """Wrap an ADPCM block in the camera's media packet format."""
    header = PACKET_MAGIC + struct.pack(
        "<HHHH",
        len(block) + 4,
        len(block) + 4,
        PACKET_DATA_MAGIC,
        (len(block) - BLOCK_HEADER_SIZE) // 2,
    )
    return header + block + bytes((-len(block)) % PACKET_PAD)
