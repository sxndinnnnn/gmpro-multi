"""Google encoded polyline helpers (precision 5)."""
from __future__ import annotations


def encode(points: list[tuple[float, float]]) -> str:
    out: list[str] = []
    prev_lat = prev_lng = 0
    for lat, lng in points:
        ilat, ilng = round(lat * 1e5), round(lng * 1e5)
        for delta in (ilat - prev_lat, ilng - prev_lng):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
        prev_lat, prev_lng = ilat, ilng
    return "".join(out)


def decode(encoded: str) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    index = lat = lng = 0
    while index < len(encoded):
        coords = []
        for _ in range(2):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            coords.append(~(result >> 1) if result & 1 else result >> 1)
        lat += coords[0]
        lng += coords[1]
        points.append((lat / 1e5, lng / 1e5))
    return points


def merge(first: str, second: str) -> str:
    a, b = decode(first), decode(second)
    if a and b and a[-1] == b[0]:
        b = b[1:]
    return encode(a + b)
