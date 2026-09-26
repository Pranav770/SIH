import struct
import json
import socket
import numpy as np

MAP_PORT = 5556
VIDEO_PORT = 5555

HEADER_MAGIC = b"NIDAR"
HEADER_FORMAT = "!5sII"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)


def encode_frame(frame: np.ndarray) -> bytes:
    import cv2

    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
    data = buf.tobytes()
    header = struct.pack(HEADER_FORMAT, HEADER_MAGIC, len(data), 0)
    return header + data


def decode_frame(data: bytes) -> np.ndarray | None:
    import cv2

    if len(data) < HEADER_SIZE:
        return None
    magic, size, _ = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    if magic != HEADER_MAGIC:
        return None
    jpg_data = data[HEADER_SIZE : HEADER_SIZE + size]
    if len(jpg_data) != size:
        return None
    arr = np.frombuffer(jpg_data, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def encode_map_packet(
    grid: np.ndarray,
    survivors: list[dict],
    drone_pos: tuple[int, int],
    hazards: list[dict],
    mission: dict,
    extra: dict | None = None,
) -> bytes:
    payload = {
        "grid_shape": list(grid.shape),
        "grid_dtype": str(grid.dtype),
        "survivors": survivors,
        "drone_pos": list(drone_pos),
        "hazards": hazards,
        "mission": mission,
    }
    if extra:
        payload.update(extra)
    meta_json = json.dumps(payload).encode("utf-8")
    grid_bytes = grid.tobytes()
    header = struct.pack(
        HEADER_FORMAT, HEADER_MAGIC, len(meta_json), len(grid_bytes)
    )
    return header + meta_json + grid_bytes


#: packet keys consumed by the decoder itself; everything else in the JSON
#: meta block is passed through as ``extra`` (detections, ai, comms, nav,
#: origin, source, …) so older senders keep working unchanged.
_KNOWN_KEYS = {
    "grid_shape", "grid_dtype", "survivors", "drone_pos", "hazards", "mission",
}


def decode_map_packet(
    data: bytes,
) -> tuple[np.ndarray, list, tuple[int, int], list, dict, dict] | None:
    """Returns (grid, survivors, drone_pos, hazards, mission, extra).

    ``extra`` carries optional extension fields; missing keys simply mean
    *not reported* by the sender.
    """
    if len(data) < HEADER_SIZE:
        return None
    magic, meta_len, grid_len = struct.unpack(
        HEADER_FORMAT, data[:HEADER_SIZE]
    )
    if magic != HEADER_MAGIC:
        return None
    offset = HEADER_SIZE
    meta_bytes = data[offset : offset + meta_len]
    offset += meta_len
    grid_bytes = data[offset : offset + grid_len]

    meta = json.loads(meta_bytes.decode("utf-8"))
    grid = np.frombuffer(grid_bytes, dtype=meta["grid_dtype"]).reshape(
        meta["grid_shape"]
    )
    extra = {k: v for k, v in meta.items() if k not in _KNOWN_KEYS}
    return (
        grid,
        meta["survivors"],
        tuple(meta["drone_pos"]),
        meta["hazards"],
        meta["mission"],
        extra,
    )
