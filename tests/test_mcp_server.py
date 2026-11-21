import asyncio
import threading
import unittest
from importlib.resources import files
from pathlib import Path

from blentopy.mcp_server import _make_render_progress_callback, load_ai_system_prompt
from blentopy.runner import RenderProgress


class _ProgressContext:
    def __init__(self):
        self.events = []

    async def report_progress(self, progress, total=None, message=None):
        self.events.append((progress, total, message))


class MCPProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_render_progress_is_forwarded_monotonically(self):
        context = _ProgressContext()
        callback = _make_render_progress_callback(context, asyncio.get_running_loop())
        events = [
            RenderProgress(stage="building_scene"),
            RenderProgress(stage="validating_scene"),
            RenderProgress(stage="saving_project"),
            RenderProgress(stage="rendering"),
            RenderProgress(stage="rendering", frame=0, total_frames=8),
            RenderProgress(stage="rendering", frame=4, total_frames=8),
            RenderProgress(stage="rendering", frame=8, total_frames=8),
            RenderProgress(stage="completed"),
        ]

        def report_from_worker_thread():
            for event in events:
                callback(event)

        worker = threading.Thread(target=report_from_worker_thread)
        worker.start()
        await asyncio.to_thread(worker.join)

        values = [event[0] for event in context.events]
        self.assertEqual(values, sorted(set(values)))
        self.assertEqual(values[-1], 1.0)
        self.assertEqual(context.events[-1][1], 1.0)
        self.assertIn("Rendering frames: 4/8", [event[2] for event in context.events])


class PackagedPromptTests(unittest.TestCase):
    def test_packaged_prompt_matches_repository_authoring_contract(self):
        packaged = files("blentopy").joinpath("AI_SYSTEM_PROMPT.md").read_text(encoding="utf-8")
        repository_copy = (
            Path(__file__).resolve().parents[1] / "docs" / "AI_SYSTEM_PROMPT.md"
        ).read_text(encoding="utf-8")
        self.assertEqual(packaged, repository_copy)
        self.assertEqual(load_ai_system_prompt(), packaged.strip())


if __name__ == "__main__":
    unittest.main()
