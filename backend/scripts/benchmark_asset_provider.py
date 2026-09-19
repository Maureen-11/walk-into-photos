"""Audit image-to-3D candidates without changing the production environment.

This first pass is intentionally dependency-light. It reports whether a
candidate is installed and whether the current GPU can plausibly be used for
an isolated test; it never downloads weights or sends an image anywhere.
Generation is only allowed after a provider has an explicit isolated setup.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Provider:
    name: str
    repo: str
    purpose: str
    import_name: str
    declared_vram_gb: str
    license_note: str


PROVIDERS = (
    Provider("sam2", "https://github.com/facebookresearch/sam2", "主体分离", "sam2", "未统一公布", "Apache-2.0/BSD-3-Clause components"),
    Provider("triposr", "https://github.com/VAST-AI-Research/TripoSR", "单物体形状", "tsr", "README约6GB/单图", "MIT"),
    Provider("hunyuan3d", "https://github.com/Tencent-Hunyuan/Hunyuan3D-2", "物体形状与纹理", "hy3dgen", "形状约6GB；形状+纹理约16GB", "Tencent Hunyuan 3D community license"),
    Provider("liveportrait", "https://github.com/KlingAIResearch/LivePortrait", "主体动作候选", "liveportrait", "待实测", "核对上游仓库与权重许可"),
)


def gpu_info() -> dict[str, str]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,driver_version", "--format=csv,noheader"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        return {"status": "unavailable", "error": type(exc).__name__}
    values = [part.strip() for part in result.stdout.strip().split(",")]
    return {"status": "available", "name": values[0] if values else "unknown", "memory_total": values[1] if len(values) > 1 else "unknown", "memory_used": values[2] if len(values) > 2 else "unknown", "driver": values[3] if len(values) > 3 else "unknown"}


def audit() -> dict:
    return {
        "python": sys.version.split()[0],
        "gpu": gpu_info(),
        "providers": [
            {**asdict(provider), "installed": importlib.util.find_spec(provider.import_name) is not None}
            for provider in PROVIDERS
        ],
        "network_or_download_performed": False,
        "photos_uploaded": False,
        "next_step": "Choose one provider and create an isolated D: environment before generation.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="审计单图主体工具，不下载模型、不上传照片")
    parser.add_argument("--json", type=Path, help="写入审计 JSON 文件")
    args = parser.parse_args()
    payload = audit()
    output = json.dumps(payload, ensure_ascii=False, indent=2)
    print(output)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(output + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
