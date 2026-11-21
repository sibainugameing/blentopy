import unittest

from blentopy.runner import validate_render_settings


class RenderSettingsTests(unittest.TestCase):
    def test_accepts_portrait_defaults(self):
        validate_render_settings(720, 1280, 30, 8)

    def test_rejects_large_dimensions(self):
        with self.assertRaises(ValueError):
            validate_render_settings(2048, 1080, 30, 10)

    def test_rejects_too_many_frames(self):
        with self.assertRaises(ValueError):
            validate_render_settings(720, 1280, 60, 61)

    def test_rejects_invalid_fps(self):
        with self.assertRaises(ValueError):
            validate_render_settings(720, 1280, 0, 8)


if __name__ == "__main__":
    unittest.main()
