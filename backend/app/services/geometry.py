from __future__ import annotations

import struct
from pathlib import Path


def _chunk(kind: bytes, payload: bytes) -> bytes:
    padded = payload + b" " * ((4 - len(payload) % 4) % 4)
    return struct.pack("<I4s", len(padded), kind) + padded


def write_demo_glb(path: Path) -> None:
    """Write a tiny valid GLB plane for viewer smoke tests.

    This is deliberately labeled demo geometry. It is not the MoGe output.
    """
    positions = struct.pack(
        "<9f", -1.5, -1.0, 0.0, 1.5, -1.0, 0.0, 0.0, 1.2, 0.0
    )
    indices = struct.pack("<3H", 0, 1, 2) + b"\x00\x00"
    binary = positions + indices
    gltf = {
        "asset": {"version": "2.0", "generator": "walk-into-photos demo"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions), "target": 34962},
            {"buffer": 0, "byteOffset": len(positions), "byteLength": 6, "target": 34963},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [-1.5, -1.0, 0.0], "max": [1.5, 1.2, 0.0]},
            {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
    }
    json_bytes = __import__("json").dumps(gltf, separators=(",", ":")).encode("utf-8")
    blob = b"glTF" + struct.pack("<II", 2, 12 + 8 + ((len(json_bytes) + 3) // 4) * 4 + 8 + len(binary))
    blob += _chunk(b"JSON", json_bytes) + _chunk(b"BIN\x00", binary)
    path.write_bytes(blob)


def generate_scene(image_path: Path, scene_path: Path, mock: bool = True) -> dict:
    if not mock:
        raise NotImplementedError("MoGe adapter is the next model-backed implementation stage")
    scene_path.parent.mkdir(parents=True, exist_ok=True)
    write_demo_glb(scene_path)
    return {
        "coverage": 1.0,
        "movement_radius": 0.55,
        "generated_region_note": "演示几何；真实模式将标注照片不可见区域的AI估计补全。",
        "mock": True,
    }
