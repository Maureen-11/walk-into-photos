from __future__ import annotations

from app.models import MovementProfile, PhotoCategory, SceneEngine, SceneTemplate


CATEGORY_TEMPLATE: dict[PhotoCategory, SceneTemplate] = {
    PhotoCategory.natural_landscape: SceneTemplate.landscape_journey,
    PhotoCategory.indoor_space: SceneTemplate.indoor_walk,
    PhotoCategory.street_city: SceneTemplate.street_descent,
    PhotoCategory.architecture: SceneTemplate.facade_flight,
    PhotoCategory.animal_closeup: SceneTemplate.animal_diorama,
    PhotoCategory.people: SceneTemplate.memory_stage,
    PhotoCategory.food_tabletop: SceneTemplate.tabletop_world,
    PhotoCategory.art_memory: SceneTemplate.layered_canvas,
    PhotoCategory.other: SceneTemplate.generic_layers,
}

TEMPLATE_LABELS: dict[SceneTemplate, str] = {
    SceneTemplate.landscape_journey: "地形旅程：走入山谷／草原／海岸",
    SceneTemplate.indoor_walk: "空间漫游：沿安全地面探索",
    SceneTemplate.street_descent: "街区下降：从高处进入街道",
    SceneTemplate.facade_flight: "立面飞行：沿建筑和窗户上下移动",
    SceneTemplate.animal_diorama: "主体微缩：围绕动物和前后景探索",
    SceneTemplate.memory_stage: "记忆舞台：围绕人物的叙事空间",
    SceneTemplate.tabletop_world: "桌面微缩：从桌面高度观察食物",
    SceneTemplate.layered_canvas: "分层画布：穿行于前景、中景和背景",
    SceneTemplate.generic_layers: "通用分层：实验性入画体验",
}

ENGINE_BY_TEMPLATE: dict[SceneTemplate, SceneEngine] = {
    SceneTemplate.landscape_journey: SceneEngine.terrain,
    SceneTemplate.indoor_walk: SceneEngine.space,
    SceneTemplate.street_descent: SceneEngine.street,
    SceneTemplate.facade_flight: SceneEngine.facade,
    SceneTemplate.animal_diorama: SceneEngine.diorama,
    SceneTemplate.memory_stage: SceneEngine.portrait_stage,
    SceneTemplate.tabletop_world: SceneEngine.tabletop,
    SceneTemplate.layered_canvas: SceneEngine.layered_canvas,
    SceneTemplate.generic_layers: SceneEngine.generic_layers,
}

COMPATIBLE: dict[SceneTemplate, list[SceneTemplate]] = {
    SceneTemplate.landscape_journey: [SceneTemplate.landscape_journey, SceneTemplate.layered_canvas],
    SceneTemplate.indoor_walk: [SceneTemplate.indoor_walk, SceneTemplate.layered_canvas],
    SceneTemplate.street_descent: [SceneTemplate.street_descent, SceneTemplate.facade_flight, SceneTemplate.layered_canvas],
    SceneTemplate.facade_flight: [SceneTemplate.facade_flight, SceneTemplate.street_descent, SceneTemplate.layered_canvas],
    SceneTemplate.animal_diorama: [SceneTemplate.animal_diorama, SceneTemplate.memory_stage, SceneTemplate.layered_canvas],
    SceneTemplate.memory_stage: [SceneTemplate.memory_stage, SceneTemplate.animal_diorama, SceneTemplate.layered_canvas],
    SceneTemplate.tabletop_world: [SceneTemplate.tabletop_world, SceneTemplate.layered_canvas],
    SceneTemplate.layered_canvas: [SceneTemplate.layered_canvas, SceneTemplate.generic_layers],
    SceneTemplate.generic_layers: [SceneTemplate.generic_layers, SceneTemplate.layered_canvas],
}


def movement_profile(template: SceneTemplate) -> MovementProfile:
    profiles = {
        # kind, start, bounds, walk speed, fly speed, flight, ground follow,
        # ground y, collision radius, route checkpoints
        SceneTemplate.landscape_journey: ("terrain", [0.0, 0.1, -0.3], {"x": [-4.0, 4.0], "y": [-1.0, 8.0], "z": [-12.0, 1.0]}, 2.2, 4.2, True, True, 0.1, 0.35, [[0.0, 0.1, -3.0], [0.0, 0.1, -7.0], [2.0, 0.1, -10.0]]),
        SceneTemplate.indoor_walk: ("floor_walk", [0.0, 1.55, 0.0], {"x": [-3.0, 3.0], "y": [0.9, 2.2], "z": [-8.0, 1.0]}, 1.7, 2.0, False, True, 1.55, 0.3, [[0.0, 1.55, -2.0], [1.2, 1.55, -4.0], [-1.0, 1.55, -6.5]]),
        SceneTemplate.street_descent: ("street_descent", [0.0, 4.0, 0.5], {"x": [-5.0, 5.0], "y": [-2.0, 8.0], "z": [-12.0, 2.0]}, 2.6, 4.0, True, False, None, 0.35, [[0.0, 2.0, -3.0], [2.0, 1.0, -6.0], [0.0, 0.4, -9.0]]),
        SceneTemplate.facade_flight: ("facade_flight", [0.0, 1.5, 0.8], {"x": [-6.0, 6.0], "y": [-5.0, 8.0], "z": [-8.0, 3.0]}, 2.0, 4.8, True, False, None, 0.25, [[-3.0, 2.5, 0.8], [3.0, 4.0, 0.8], [0.0, 6.0, 0.8]]),
        SceneTemplate.animal_diorama: ("diorama", [0.0, 0.4, 2.0], {"x": [-4.0, 4.0], "y": [-3.0, 4.0], "z": [-6.0, 4.0]}, 1.5, 2.8, True, False, None, 0.2, []),
        SceneTemplate.memory_stage: ("memory_stage", [0.0, 1.4, 2.2], {"x": [-4.0, 4.0], "y": [-2.0, 4.0], "z": [-7.0, 4.0]}, 1.6, 3.0, True, False, None, 0.2, []),
        SceneTemplate.tabletop_world: ("tabletop", [0.0, 1.2, 2.0], {"x": [-4.0, 4.0], "y": [-1.0, 5.0], "z": [-6.0, 4.0]}, 1.4, 2.6, True, False, None, 0.2, []),
        SceneTemplate.layered_canvas: ("layered_flight", [0.0, 0.8, 2.4], {"x": [-5.0, 5.0], "y": [-4.0, 6.0], "z": [-8.0, 4.0]}, 1.8, 3.8, True, False, None, 0.2, []),
        SceneTemplate.generic_layers: ("generic_layers", [0.0, 0.8, 2.8], {"x": [-3.5, 3.5], "y": [-3.0, 5.0], "z": [-7.0, 3.0]}, 1.6, 3.0, True, False, None, 0.2, []),
    }
    kind, start, bounds, walk_speed, fly_speed, allow_flight, ground_follow, ground_y, collision_radius, route_checkpoints = profiles[template]
    return MovementProfile(kind=kind, start=start, bounds=bounds, walk_speed=walk_speed, fly_speed=fly_speed, allow_flight=allow_flight, ground_follow=ground_follow, ground_y=ground_y, collision_radius=collision_radius, route_checkpoints=route_checkpoints)
