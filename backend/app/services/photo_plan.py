from __future__ import annotations

import base64
import json
import uuid
from pathlib import Path

import httpx

from app.config import Settings
from app.models import ExperiencePreset, PhotoPlan, SceneType, Suitability


def demo_plan() -> PhotoPlan:
    return PhotoPlan(
        analysis_id=str(uuid.uuid4()),
        suitability=Suitability.conditional,
        scene_type=SceneType.corridor,
        title="保守的近距离走廊体验",
        summary="演示模式已生成建议。真实模式将由视觉模型根据照片判断透视线索、主体和遮挡区域。",
        experience_preset=ExperiencePreset.conservative,
        warnings=["当前为演示模式；照片之外的区域只是AI估计补全，不是真实空间重建。"],
        estimated_seconds=90,
        mock=True,
    )


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned)


async def analyze_photo(path: Path, settings: Settings) -> PhotoPlan:
    """Analyze a photo with DeepSeek Vision, with an explicit demo fallback."""
    if settings.mock_mode or not settings.deepseek_api_key:
        return demo_plan()

    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower(), "image/jpeg")
    data_uri = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    schema_hint = {
        "suitability": "suitable|conditional|reject",
        "scene_type": "corridor|room|other",
        "title": "string",
        "summary": "string",
        "experience_preset": "corridor_forward|room_explore|conservative",
        "warnings": ["string"],
        "estimated_seconds": 90,
    }
    prompt = (
        "你是走进照片项目的照片规划器。只输出合法JSON，不要Markdown。"
        "判断横向走廊或房间照片是否适合有限范围的浏览器场景。"
        "不要承诺真实重建；不可见区域必须写入warnings。"
        f"字段格式参考：{json.dumps(schema_hint, ensure_ascii=False)}"
    )
    payload = {
        "model": settings.deepseek_vision_model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ]}],
        "temperature": 0,
    }
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
            json=payload,
        )
        response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    raw = _extract_json(content)
    return PhotoPlan(
        analysis_id=str(uuid.uuid4()),
        suitability=raw["suitability"],
        scene_type=raw["scene_type"],
        title=raw["title"],
        summary=raw["summary"],
        experience_preset=raw["experience_preset"],
        warnings=raw.get("warnings", []),
        estimated_seconds=int(raw.get("estimated_seconds", 90)),
        mock=False,
    )
