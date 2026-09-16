from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
import zipfile

from app.main import _build_offline_archive
from app.models import SceneManifest, SceneTemplate
from app.services.geometry import write_demo_glb
from app.services.templates import movement_profile


def test_offline_archive_contains_local_viewer_and_no_cdn(tmp_path: Path):
    scene_dir = tmp_path / "scene-001"
    scene_dir.mkdir()
    write_demo_glb(scene_dir / "scene.glb")
    (scene_dir / "source.jpg").write_bytes(b"private-source-placeholder")
    (scene_dir / "collision.json").write_text('{"boxes": []}', encoding="utf-8")
    manifest = SceneManifest(
        scene_id="scene-001",
        scene_url="/api/scenes/scene-001/scene.glb",
        download_url="/api/scenes/scene-001/scene.glb",
        export_url="/api/scenes/scene-001/export",
        version="quick",
        template=SceneTemplate.landscape_journey,
        movement=movement_profile(SceneTemplate.landscape_journey),
        generated_region_note="test",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        resource_manifest=["scene.glb", "source.jpg", "collision.json"],
        collision_resource="collision.json",
    )
    (scene_dir / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")

    archive = _build_offline_archive(scene_dir)
    with zipfile.ZipFile(BytesIO(archive)) as package:
        names = set(package.namelist())
        assert {"index.html", "scene.glb", "manifest.json", "three.module.js", "GLTFLoader.js", "BufferGeometryUtils.js", "README.txt"} <= names
        assert "source.jpg" not in names
        assert "collision.json" in names
        html = package.read("index.html").decode("utf-8")
        assert "import * as THREE from './three.module.js'" not in html
        assert "new GLTFLoader().load('./scene.glb'" not in html
        assert "fetch('./manifest.json')" not in html
        assert "new GLTFLoader().parse(glbBytes.buffer" in html
        assert "atob(\"" in html
        assert "F飞行" in html
        assert "movement.bounds" in html
        assert "不包含原始照片" in package.read("README.txt").decode("utf-8")
