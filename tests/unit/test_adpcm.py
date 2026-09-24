import math
import struct

from reolink_camera_control import adpcm

STEP = adpcm._STEP
INDEX_ADJUST = adpcm._INDEX_ADJUST


def decode_block(block: bytes):
    """Reference IMA ADPCM decoder used to verify the encoder round trip."""
    predictor, index, _ = struct.unpack("<hBB", block[:4])
    out = [predictor]
    for byte in block[4:]:
        for code in (byte & 0x0F, byte >> 4):
            step = STEP[index]
            diff = step >> 3
            if code & 4:
                diff += step
            if code & 2:
                diff += step >> 1
            if code & 1:
                diff += step >> 2
            predictor += -diff if code & 8 else diff
            predictor = max(-32768, min(32767, predictor))
            index = max(0, min(88, index + INDEX_ADJUST[code & 7]))
            out.append(predictor)
    return out


def sine_pcm(freq=440, seconds=0.5, rate=16000, amp=0.6):
    n = int(rate * seconds)
    samples = [int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)]
    return samples, struct.pack(f"<{n}h", *samples)


def test_block_layout_for_1024_samples():
    block, _ = adpcm.encode_block(list(range(1025)))
    assert len(block) == 4 + 512   # header + 1024 nibbles


def test_header_stores_first_sample_and_index():
    block, _ = adpcm.encode_block([1234, 1300, 1400], index=7)
    predictor, index, reserved = struct.unpack("<hBB", block[:4])
    assert (predictor, index, reserved) == (1234, 7, 0)


def test_encode_decode_round_trip_is_close():
    samples, pcm = sine_pcm()
    blocks = adpcm.encode_pcm(pcm)
    decoded = []
    for block in blocks:
        decoded.extend(decode_block(block))
    decoded = decoded[:len(samples)]
    err = sum(abs(a - b) for a, b in zip(samples, decoded)) / len(samples)
    assert err < 0.02 * 32767        # under 2 percent mean error


def test_silence_encodes_to_silence():
    blocks = adpcm.encode_pcm(bytes(2 * 3000))
    for block in blocks:
        assert set(decode_block(block)) == {0}


def test_number_of_blocks_and_padding_of_last_block():
    # 2100 samples at 1025 samples per block -> 3 blocks, last one zero padded
    blocks = adpcm.encode_pcm(bytes(2 * 2100))
    assert len(blocks) == 3
    assert all(len(b) == 516 for b in blocks)


def test_empty_input_gives_no_blocks():
    assert adpcm.encode_pcm(b"") == []


def test_frame_block_matches_neolink_format():
    block = bytes(range(256)) * 2 + bytes(4)       # 516 byte block
    framed = adpcm.frame_block(block)
    assert framed[:4] == b"01wb"
    size1, size2, magic, half = struct.unpack("<HHHH", framed[4:12])
    assert (size1, size2) == (520, 520)
    assert magic == 0x0100
    assert half == 256                              # (516 - 4) / 2
    assert framed[12:12 + 516] == block
    assert (len(framed) - 12) % 8 == 0              # data padded like neolink (516 -> 520)
    assert framed[12 + 516:] == bytes(4)
