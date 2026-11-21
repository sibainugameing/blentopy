import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from blentopy.studio import Studio


class StudioInputValidationTests(unittest.TestCase):
    def test_animation_frames_require_integer_frame_numbers(self):
        studio = SimpleNamespace(scene=SimpleNamespace(frame_start=1, frame_end=120))
        self.assertEqual(Studio._animation_frames(studio, 1, 120), (1, 120))
        with self.assertRaises(TypeError):
            Studio._animation_frames(studio, 1.5, 120)
        with self.assertRaises(ValueError):
            Studio._animation_frames(studio, 0, 120)
        with self.assertRaises(ValueError):
            Studio._animation_frames(studio, 1, 121)

    def test_existing_audio_strips_are_restored_by_name(self):
        sound = SimpleNamespace(type="SOUND", name="music", sound=object())
        scene_strip = SimpleNamespace(type="SCENE", name="3D Scene", sound=None)
        studio = SimpleNamespace(
            _sequence_editor=SimpleNamespace(strips=[sound, scene_strip]),
            _audio_strips={},
        )
        Studio._restore_audio_strips(studio)
        self.assertEqual(studio._audio_strips, {"music": sound})

    def test_add_audio_rejects_invalid_channel_and_out_of_timeline_start(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sound_file = root / "music.wav"
            sound_file.write_bytes(b"placeholder")
            studio = SimpleNamespace(
                _workspace=root,
                _audio_strips={},
                _duration=8.0,
                _fps=24,
                _finite_scalar=Studio._finite_scalar,
                _clamp=Studio._clamp,
                scene=SimpleNamespace(frame_start=1),
                _sequence_editor=SimpleNamespace(strips=SimpleNamespace(new_sound=Mock())),
            )
            with self.assertRaisesRegex(ValueError, "channel"):
                Studio.add_audio(studio, "music", str(sound_file), channel=129)
            with self.assertRaisesRegex(ValueError, "start_seconds"):
                Studio.add_audio(studio, "music", str(sound_file), start_seconds=8)

    def test_add_audio_requires_file_inside_workspace(self):
        with tempfile.TemporaryDirectory() as workspace, tempfile.TemporaryDirectory() as outside:
            sound_file = Path(outside) / "music.wav"
            sound_file.write_bytes(b"placeholder")
            studio = SimpleNamespace(
                _workspace=Path(workspace),
                _audio_strips={},
                _duration=8.0,
                _fps=24,
                _finite_scalar=Studio._finite_scalar,
                _clamp=Studio._clamp,
                scene=SimpleNamespace(frame_start=1),
                _sequence_editor=SimpleNamespace(strips=SimpleNamespace(new_sound=Mock())),
            )
            with self.assertRaisesRegex(ValueError, "inside the blentopy workspace"):
                Studio.add_audio(studio, "music", str(sound_file))

    def test_fade_audio_rejects_frames_outside_the_output_timeline(self):
        strip = SimpleNamespace(keyframe_insert=Mock())
        studio = SimpleNamespace(
            _audio_strips={"music": strip},
            output_scene=SimpleNamespace(frame_start=1, frame_end=120),
            _finite_scalar=Studio._finite_scalar,
        )
        with self.assertRaisesRegex(ValueError, "fade frames"):
            Studio.fade_audio(studio, "music", 0, 1, 0, 120)
        with self.assertRaisesRegex(TypeError, "integers"):
            Studio.fade_audio(studio, "music", 0, 1, 1.5, 120)


if __name__ == "__main__":
    unittest.main()
