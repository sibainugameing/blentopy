import unittest
from unittest.mock import patch

from blentopy.ai_native import AIStudio, GeometryFactory, MaterialFactory, SceneAPI


class GeometryFactoryTests(unittest.TestCase):
    def test_creates_reusable_box_and_custom_geometry_specs(self):
        box = GeometryFactory.rounded_box(size=(2, 1, 3), bevel=0.1)
        self.assertEqual(box.kind, "box")
        self.assertEqual(box.options()["size"], (2.0, 1.0, 3.0))
        self.assertEqual(box.options()["bevel"], 0.1)

        custom = GeometryFactory.mesh(
            vertices=((0, 0, 0), (1, 0, 0), (0, 1, 0)),
            faces=((0, 1, 2),),
        )
        self.assertEqual(custom.kind, "custom")
        self.assertEqual(custom.options()["faces"], ((0, 1, 2),))

    def test_rejects_invalid_geometry(self):
        with self.assertRaises(ValueError):
            GeometryFactory.box(size=(1, 0, 1))
        with self.assertRaises(ValueError):
            GeometryFactory.sphere(radius=-1)
        with self.assertRaises(ValueError):
            GeometryFactory.mesh(
                vertices=((0, 0, 0), (1, 0, 0), (0, 1, 0)),
                faces=((0, 1, 9),),
            )


class MaterialFactoryTests(unittest.TestCase):
    def test_accepts_hex_and_numeric_colors(self):
        blue = MaterialFactory.pbr(color="#2878FF", roughness=0.3, metallic=0.5)
        self.assertEqual(blue.model, "pbr")
        self.assertEqual(blue.options()["color"], (40 / 255, 120 / 255, 1.0, 1.0))
        self.assertEqual(blue.options()["roughness"], 0.3)

        glow = MaterialFactory.emissive(color=(1, 0.5, 0), strength=3)
        self.assertEqual(glow.model, "emissive")
        self.assertEqual(glow.options()["emission_strength"], 3.0)

    def test_rejects_invalid_material_values(self):
        with self.assertRaises(ValueError):
            MaterialFactory.pbr(color="#XYZ")
        with self.assertRaises(ValueError):
            MaterialFactory.pbr(roughness=1.5)
        with self.assertRaises(ValueError):
            MaterialFactory.emissive(strength=-1)


class SceneTimebaseTests(unittest.TestCase):
    def test_configure_inherits_render_job_timebase_when_omitted(self):
        class Backend:
            def __init__(self):
                self.timeline = None

            def set_timeline(self, duration, fps):
                self.timeline = (duration, fps)

            def set_world_color(self, color, strength):
                pass

        backend = Backend()
        owner = type("Owner", (), {"_backend": backend})()
        scene = SceneAPI(owner, duration=12, fps=24)

        scene.configure(background="#102030")
        self.assertEqual((scene._duration, scene._fps), (12.0, 24))
        self.assertEqual(backend.timeline, (12.0, 24))

        scene.configure(duration=5, fps=25)
        self.assertEqual((scene._duration, scene._fps), (5.0, 25))
        self.assertEqual(backend.timeline, (5.0, 25))

    def test_ai_studio_passes_render_job_timebase_to_scene_api(self):
        with patch("blentopy.studio.Studio"):
            studio = AIStudio(
                workspace="/tmp/blentopy-test",
                output_path="/tmp/blentopy-test/output.mp4",
                blend_path="/tmp/blentopy-test/output.blend",
                width=720,
                height=1280,
                fps=24,
                duration_seconds=12,
            )
        self.assertEqual(studio.scene._duration, 12.0)
        self.assertEqual(studio.scene._fps, 24)




    def test_vector3_rejects_boolean_and_numeric_string_components(self):
        from blentopy.ai_native import _vector3

        with self.assertRaises(TypeError):
            _vector3((True, 0, 1), "position")
        with self.assertRaises(TypeError):
            _vector3(("1", 0, 1), "position")

    def test_color_rejects_boolean_and_numeric_string_channels(self):
        from blentopy.ai_native import _color

        with self.assertRaises(TypeError):
            _color((True, 0, 1))
        with self.assertRaises(TypeError):
            _color(("1", 0, 1))


class SceneRenderValidationTests(unittest.TestCase):
    @staticmethod
    def make_scene(camera, *, width=1080, height=1920):
        class Polygons:
            def __len__(self):
                return 12

        mesh = type(
            "MeshObject",
            (),
            {
                "type": "MESH",
                "hide_render": False,
                "data": type("MeshData", (), {"polygons": Polygons()})(),
                "modifiers": [],
            },
        )()
        render = type(
            "Render",
            (),
            {
                "resolution_x": width,
                "resolution_y": height,
                "resolution_percentage": 100,
                "fps": 24,
                "fps_base": 1.0,
            },
        )()
        return type(
            "Scene",
            (),
            {
                "objects": [mesh] + ([camera] if camera is not None else []),
                "render": render,
                "frame_start": 1,
                "frame_end": 24,
                "camera": camera,
            },
        )()

    def test_validate_rejects_invalid_active_camera_clip_range(self):
        camera = type(
            "CameraObject",
            (),
            {
                "type": "CAMERA",
                "hide_render": False,
                "name": "Camera",
                "data": type(
                    "CameraData",
                    (),
                    {
                        "clip_start": 0.0,
                        "clip_end": 100.0,
                        "type": "PERSP",
                        "lens": 50.0,
                    },
                )(),
            },
        )()
        scene = self.make_scene(camera)
        studio = type(
            "SceneHandle",
            (),
            {
                "_backend": type("Backend", (), {"scene": scene})(),
                "_objects": {},
            },
        )()
        report = SceneAPI.validate(studio)
        self.assertFalse(report["ok"])
        self.assertTrue(any("clipping range is invalid" in error for error in report["errors"]))
        self.assertEqual(report["visible_light_count"], 0)
        self.assertTrue(any("No visible lights" in warning for warning in report["warnings"]))

    def test_validate_rejects_invalid_render_resolution_and_missing_camera(self):
        scene = self.make_scene(None, width=8, height=8)
        studio = type(
            "SceneHandle",
            (),
            {
                "_backend": type("Backend", (), {"scene": scene})(),
                "_objects": {},
            },
        )()
        report = SceneAPI.validate(studio)
        self.assertFalse(report["ok"])
        self.assertTrue(any("resolution" in error.lower() for error in report["errors"]))
        self.assertIn("No active camera is configured.", report["errors"])

class ResourceLimitTests(unittest.TestCase):
    def test_scene_resource_usage_includes_objects_polygons_and_modifiers(self):
        from blentopy.resource_limits import scene_resource_usage

        class Polygons:
            def __len__(self):
                return 20

        class Modifier:
            type = "SUBSURF"
            levels = 2
            render_levels = 2

        class Data:
            polygons = Polygons()

        class MeshObject:
            type = "MESH"
            data = Data()
            modifiers = [Modifier()]

        class EmptyObject:
            type = "EMPTY"
            data = None
            modifiers = []

        usage = scene_resource_usage(type("Scene", (), {"objects": [MeshObject(), EmptyObject()]})())
        self.assertEqual(usage, {"objects": 2, "polygons": 320, "modifiers": 1})

    def test_scene_resource_budget_rejects_modifier_expansion(self):
        from blentopy.resource_limits import ResourceLimitError, ensure_scene_capacity

        class Polygons:
            def __len__(self):
                return 2_000

        class Modifier:
            type = "SUBSURF"
            levels = 6
            render_levels = 6

        class Data:
            polygons = Polygons()

        class MeshObject:
            type = "MESH"
            data = Data()
            modifiers = [Modifier()]

        scene = type("Scene", (), {"objects": [MeshObject()]})()
        with self.assertRaises(ResourceLimitError):
            ensure_scene_capacity(scene)

class SceneIdTests(unittest.TestCase):
    def test_auto_ids_are_deterministic_and_skip_explicit_collisions(self):
        scene = SceneAPI(owner=None)
        self.assertEqual(scene._allocate_id("mesh"), "mesh.0001")
        scene._objects["mesh.0002"] = object()
        self.assertEqual(scene._allocate_id("mesh"), "mesh.0003")
        self.assertEqual(scene._allocate_id("group"), "group.0001")


if __name__ == "__main__":
    unittest.main()
