import unittest

from blentopy.ai_native import GeometryFactory, MaterialFactory
from blentopy.scene_features import SceneFeatureMixin, build_geometry_mesh
from blentopy.validation import ScriptValidationError, validate_script


class ExtendedGeometryTests(unittest.TestCase):
    def test_additional_geometry_specs_are_bounded(self):
        ico = GeometryFactory.ico_sphere(radius=0.75, subdivisions=3)
        self.assertEqual(ico.kind, "ico_sphere")
        self.assertEqual(ico.options()["subdivisions"], 3)

        circle = GeometryFactory.circle(radius=2, vertices=48, fill=False)
        self.assertEqual(circle.options()["fill"], False)

        ring = GeometryFactory.ring(inner_radius=0.5, outer_radius=1.0)
        self.assertEqual(ring.kind, "ring")

        capsule = GeometryFactory.capsule(radius=0.25, height=1.5)
        self.assertEqual(capsule.options()["height"], 1.5)

        knot = GeometryFactory.torus_knot(p=2, q=3)
        self.assertEqual(knot.options()["p"], 2)

    def test_parametric_mesh_builders_create_valid_closed_meshes(self):
        vertices, faces = build_geometry_mesh("ring", {
            "segments": 24, "inner_radius": 0.5, "outer_radius": 1.0,
        })
        self.assertEqual(len(vertices), 48)
        self.assertEqual(len(faces), 24)
        first = faces[0]
        a, b, c = (vertices[first[index]] for index in range(3))
        cross_z = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        self.assertGreater(cross_z, 0)

        capsule_vertices, capsule_faces = build_geometry_mesh("capsule", {
            "radius": 0.5, "height": 2.0, "radial_segments": 16, "cap_segments": 4,
        })
        self.assertTrue(capsule_vertices)
        self.assertTrue(capsule_faces)
        self.assertTrue(all(0 <= index < len(capsule_vertices) for face in capsule_faces for index in face))

        knot_vertices, knot_faces = build_geometry_mesh("torus_knot", {
            "radius": 1.0, "tube": 0.1, "tubular_segments": 32,
            "radial_segments": 8, "p": 2, "q": 3,
        })
        self.assertEqual(len(knot_vertices), 32 * 8)
        self.assertEqual(len(knot_faces), 32 * 8)
        self.assertTrue(all(0 <= index < len(knot_vertices) for face in knot_faces for index in face))

    def test_workspace_paths_reject_escape_and_existing_export_targets(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder) / "workspace"
            workspace.mkdir()
            owner = SimpleNamespace(_backend=SimpleNamespace(_workspace=workspace))
            mixin = object.__new__(SceneFeatureMixin)
            mixin._backend = owner._backend
            valid = mixin._workspace_path(
                "assets/model.glb", must_exist=False,
                allowed_suffixes={".glb"}, label="Model export",
            )
            self.assertEqual(valid, (workspace / "assets" / "model.glb").resolve())
            with self.assertRaisesRegex(ValueError, "inside the blentopy workspace"):
                mixin._workspace_path(
                    "../outside.glb", must_exist=False,
                    allowed_suffixes={".glb"}, label="Model export",
                )

    def test_geometry_and_material_factories_reject_implicit_numeric_coercion(self):
        with self.assertRaises(TypeError):
            GeometryFactory.sphere(radius="1")
        with self.assertRaises(TypeError):
            GeometryFactory.sphere(segments=16.5)
        with self.assertRaises(TypeError):
            GeometryFactory.cylinder(height=True)
        with self.assertRaises(TypeError):
            MaterialFactory.pbr(roughness="0.5")

    def test_export_uses_staging_and_publishes_sidecar_files_together(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder) / "workspace"
            workspace.mkdir()
            mixin = object.__new__(SceneFeatureMixin)
            mixin._backend = SimpleNamespace(
                _workspace=workspace,
                _bpy=SimpleNamespace(context=SimpleNamespace(selected_objects=[])),
            )

            def export(_operators, staged_path):
                staged_path.write_text("model data", encoding="utf-8")
                staged_path.with_suffix(".mtl").write_text("material data", encoding="utf-8")

            mixin._run_file_operator = export
            result = Path(mixin.export_model("exports/model.obj"))
            self.assertEqual(result, workspace / "exports" / "model.obj")
            self.assertTrue(result.is_file())
            self.assertTrue(result.with_suffix(".mtl").is_file())
            self.assertFalse(any(".blentopy-" in item.name for item in result.parent.iterdir()))

    def test_failed_export_removes_partial_staging_output(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder) / "workspace"
            workspace.mkdir()
            mixin = object.__new__(SceneFeatureMixin)
            mixin._backend = SimpleNamespace(
                _workspace=workspace,
                _bpy=SimpleNamespace(context=SimpleNamespace(selected_objects=[])),
            )

            def fail(_operators, staged_path):
                staged_path.write_text("partial", encoding="utf-8")
                raise RuntimeError("export failed")

            mixin._run_file_operator = fail
            with self.assertRaisesRegex(RuntimeError, "export failed"):
                mixin.export_model("exports/model.glb")
            export_folder = workspace / "exports"
            self.assertFalse(export_folder.exists() and list(export_folder.iterdir()))

    def test_additional_geometry_rejects_invalid_parameters(self):
        with self.assertRaisesRegex(ValueError, "height"):
            GeometryFactory.capsule(radius=1, height=1.5)
        with self.assertRaisesRegex(ValueError, "inner_radius"):
            GeometryFactory.ring(inner_radius=1, outer_radius=1)
        with self.assertRaisesRegex(ValueError, "p and q"):
            GeometryFactory.torus_knot(p=0)

    def test_physical_glass_and_toon_materials(self):
        glass = MaterialFactory.glass(color="#EAF6FF", ior=1.52)
        self.assertEqual(glass.model, "physical")
        self.assertEqual(glass.options()["transmission"], 1.0)
        self.assertEqual(glass.options()["ior"], 1.52)

        toon = MaterialFactory.toon(color="#FF5533", size=0.4, smooth=0.2)
        self.assertEqual(toon.model, "toon")
        self.assertEqual(toon.options()["smooth"], 0.2)

    def test_physical_material_values_are_validated(self):
        with self.assertRaisesRegex(ValueError, "ior"):
            MaterialFactory.physical(ior=4)
        with self.assertRaisesRegex(ValueError, "transmission"):
            MaterialFactory.physical(transmission=1.5)

    def test_linked_instances_are_valid_python_scene_calls(self):
        validate_script(
            'scene = studio.scene\n'
            'source = scene.find(id="source")\n'
            'copy = scene.instance(source, offset=(1, 0, 0))\n'
        )

    def test_scene_feature_methods_are_valid_python_scene_calls(self):
        validate_script(
            'scene = studio.scene\n'
            'scene.configure_render(engine="eevee", samples=64)\n'
            'scene.post_process(bloom=0.25, contrast=1.1, saturation=0.9)\n'
            'scene.environment("assets/studio.exr", strength=0.8)\n'
        )

    def test_unknown_scene_feature_arguments_reach_runtime(self):
        # Syntax preflight must not duplicate facade API validation. The facade
        # raises an actionable TypeError/ValueError when this call is executed.
        validate_script(
            'scene = studio.scene\n'
            'scene.configure_render(unknown_option=True)\n'
        )


if __name__ == "__main__":
    unittest.main()
