from __future__ import annotations

import gc
import os
import re
import uuid
from pathlib import Path

from app.config import Settings
from app.models import (
    ActionSpec,
    ActionTrigger,
    CapabilityStatus,
    ExperienceKind,
    PhotoCategory,
    PhotoPlan,
    SceneTemplate,
    SubjectRegion,
)
from app.services.templates import CATEGORY_TEMPLATE, COMPATIBLE, TEMPLATE_LABELS


_ALIASES: dict[str, PhotoCategory] = {
    "natural_landscape": PhotoCategory.natural_landscape,
    "landscape": PhotoCategory.natural_landscape,
    "nature": PhotoCategory.natural_landscape,
    "indoor_space": PhotoCategory.indoor_space,
    "indoor": PhotoCategory.indoor_space,
    "room": PhotoCategory.indoor_space,
    "street_city": PhotoCategory.street_city,
    "street": PhotoCategory.street_city,
    "city": PhotoCategory.street_city,
    "architecture": PhotoCategory.architecture,
    "building": PhotoCategory.architecture,
    "facade": PhotoCategory.architecture,
    "animal_closeup": PhotoCategory.animal_closeup,
    "animal": PhotoCategory.animal_closeup,
    "cat": PhotoCategory.animal_closeup,
    "people": PhotoCategory.people,
    "person": PhotoCategory.people,
    "portrait": PhotoCategory.people,
    "food_tabletop": PhotoCategory.food_tabletop,
    "food": PhotoCategory.food_tabletop,
    "tabletop": PhotoCategory.food_tabletop,
    "art_memory": PhotoCategory.art_memory,
    "art": PhotoCategory.art_memory,
    "old_photo": PhotoCategory.art_memory,
}


def _parse_category(answer: str) -> PhotoCategory:
    normalized = re.sub(r"[^a-z_]", " ", answer.lower()).strip()
    for token in normalized.split():
        if token in _ALIASES:
            return _ALIASES[token]
    for key, category in _ALIASES.items():
        if key in normalized:
            return category
    return PhotoCategory.other


def build_plan(category: PhotoCategory, description: str, backend: str = "local-rules", mock: bool = False, subject_regions: list[SubjectRegion] | None = None) -> PhotoPlan:
    template = CATEGORY_TEMPLATE[category]
    experimental = category is PhotoCategory.other
    warnings = ["照片不可见区域会使用程序化或AI补全，不代表真实空间复原。"]
    subject_categories = {PhotoCategory.animal_closeup, PhotoCategory.people, PhotoCategory.food_tabletop}
    experience_kind = ExperienceKind.interactive_subject if category in subject_categories else ExperienceKind.spatial_scene
    capability_status = CapabilityStatus.unverified
    actions: list[ActionSpec] = []
    capability_notes: list[str] = []
    if category is PhotoCategory.animal_closeup:
        actions.append(ActionSpec(
            action_id="pet_head",
            label="摸摸主体",
            trigger=ActionTrigger.mouse_stroke,
            target_region_id="primary_subject_head",
            status=CapabilityStatus.experimental,
            hint="在识别出的头部区域按住鼠标轻轻拖动。动作素材尚未在当前工程验收。",
        ))
        warnings.insert(0, "主体互动仍处于独立技术试验阶段；生成失败时保留原图，不用整图抖动冒充回应。")
        capability_notes.append("需要局部动作素材和可靠的目标区域；笼中或多主体照片需单独验收。")
    elif category is PhotoCategory.people:
        actions.append(ActionSpec(
            action_id="wave_back",
            label="让人物回应",
            trigger=ActionTrigger.click,
            target_region_id="primary_subject",
            status=CapabilityStatus.experimental,
            hint="点击人物区域触发短回应；当前尚未验证动作素材。",
        ))
        capability_notes.append("人物动作仅支持肖像级短回应候选，不宣称全身或实时动作生成。")
    elif category is PhotoCategory.food_tabletop:
        actions.append(ActionSpec(
            action_id="tabletop_detail",
            label="查看桌面细节",
            trigger=ActionTrigger.click,
            target_region_id="primary_object",
            status=CapabilityStatus.experimental,
            hint="点击主体查看有限桌面动效；当前尚未验证物品动作素材。",
        ))
        capability_notes.append("物品动作必须符合语义；没有合适素材时只提供静态查看。")
    else:
        capability_status = CapabilityStatus.unverified
        capability_notes.append("场景移动需通过实际路线、地面、碰撞和回头录屏验收。")
    if experimental:
        warnings.insert(0, "内容无法准确归入八类模板，将使用通用分层实验模式；仍可继续生成。")
        experience_kind = ExperienceKind.still_fallback
        capability_status = CapabilityStatus.experimental
    return PhotoPlan(
        analysis_id=uuid.uuid4().hex,
        category=category,
        title=TEMPLATE_LABELS[template],
        summary=f"识别为{category.value}。智能体将把可见内容组织成可移动、可环顾的分层场景。",
        recommended_template=template,
        compatible_templates=COMPATIBLE[template],
        rationale=f"根据照片中的主体、透视和空间线索，优先选择“{TEMPLATE_LABELS[template]}”。",
        scene_description=description or "保留原照片投色，照片外区域明确标记为生成内容。",
        warnings=warnings,
        planner_backend=backend,
        experimental=experimental,
        mock=mock,
        experience_kind=experience_kind,
        capability_status=capability_status,
        actions=actions,
        subject_regions=subject_regions or [],
        capability_notes=capability_notes,
    )


def _query_moondream(path: Path, settings: Settings) -> tuple[PhotoCategory, str, list[SubjectRegion]]:
    """Run the pinned local Moondream model and release its memory afterwards."""
    import torch
    from PIL import Image
    from transformers import AutoModelForCausalLM

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = None
    try:
        tokenizer_dir = settings.local_planner_cache.parent / "starmie-v1"
        if tokenizer_dir.is_dir():
            os.environ.setdefault("MOONDREAM_TOKENIZER_PATH", str(tokenizer_dir))
        model = AutoModelForCausalLM.from_pretrained(
            settings.local_planner_model,
            revision=settings.local_planner_revision,
            trust_remote_code=True,
            local_files_only=settings.local_files_only,
            cache_dir=str(settings.local_planner_cache),
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        ).to(device)
        with Image.open(path) as image:
            image = image.convert("RGB")
            prompt = (
                "Classify this image into exactly one label: natural_landscape, indoor_space, "
                "street_city, architecture, animal_closeup, people, food_tabletop, art_memory, other. "
                "Reply with only the label."
            )
            answer = model.query(image, prompt)["answer"]
            category = _parse_category(answer)
            if category is PhotoCategory.other:
                answer = model.query(image, prompt + " Prefer a specific label when visible.")["answer"]
                category = _parse_category(answer)
            caption = model.caption(image, length="short")["caption"]
            regions: list[SubjectRegion] = []
            detection_label = {
                PhotoCategory.animal_closeup: "cat",
                PhotoCategory.people: "person",
                PhotoCategory.food_tabletop: "food",
            }.get(category)
            # The detector is opt-in until its timeout and memory budget are
            # measured on the 6GB laptop. Category planning must remain fast
            # and bounded even when a subject region is not available.
            if settings.local_planner_detect_regions and detection_label and hasattr(model, "detect"):
                detections = model.detect(image, detection_label).get("objects", [])
                for index, item in enumerate(detections[:4]):
                    try:
                        x_min = max(0.0, min(1.0, float(item["x_min"])))
                        y_min = max(0.0, min(1.0, float(item["y_min"])))
                        x_max = max(x_min, min(1.0, float(item["x_max"])))
                        y_max = max(y_min, min(1.0, float(item["y_max"])))
                    except (KeyError, TypeError, ValueError):
                        continue
                    if index == 0 and category is PhotoCategory.animal_closeup:
                        region_id = "primary_subject_head"
                    elif index == 0 and category is PhotoCategory.people:
                        region_id = "primary_subject"
                    elif index == 0 and category is PhotoCategory.food_tabletop:
                        region_id = "primary_object"
                    else:
                        region_id = f"primary_subject_{index + 1}"
                    regions.append(SubjectRegion(
                        region_id=region_id,
                        label=detection_label,
                        x=x_min,
                        y=y_min,
                        width=x_max - x_min,
                        height=y_max - y_min,
                        confidence=None,
                    ))
            return category, caption, regions
    finally:
        if model is not None:
            del model
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def analyze_photo(path: Path, settings: Settings) -> PhotoPlan:
    if settings.local_planner_enabled:
        try:
            category, description, regions = _query_moondream(path, settings)
            return build_plan(category, description, backend="moondream2-local", mock=False, subject_regions=regions)
        except Exception:
            # Local rules keep ordinary photos usable while the model is being
            # downloaded, unavailable offline, or unable to parse its answer.
            pass
    return build_plan(PhotoCategory.other, "本地视觉模型不可用，已切换到通用分层兜底。", backend="local-rules-fallback", mock=settings.mock_mode)


def demo_plan() -> PhotoPlan:
    return build_plan(PhotoCategory.other, "演示模式规划结果。", backend="demo", mock=True)
