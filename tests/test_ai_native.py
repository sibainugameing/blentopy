import unittest

from blentopy.ai_native import GeometryFactory, MaterialFactory


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


if __name__ == "__main__":
    unittest.main()
