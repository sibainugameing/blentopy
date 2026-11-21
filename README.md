# blentopy

Python-first Blender automation for AI-directed video production.

blentopy is a local execution bridge, not an AI model and not an application that calls a hosted AI API. An MCP-capable chat client supplies the reasoning and sends scene code to the local Python server. blentopy starts Blender, builds a 3D scene, combines the scene and audio in the Video Sequence Editor, then writes an MP4 and an editable .blend project.

## Prototype scope

- Python controller + Blender's bundled Python runtime.
- Blender control through a narrow Studio API backed by bpy.
- Objects, materials, text, cameras, lights, transform keyframes.
- Existing audio files added to VSE, with volume keyframes.
- Separate content and output scenes, so a VSE scene strip can combine the 3D render with audio.
- H.264 video in an MP4 container.
- Optional local stdio MCP server; no AI API key is required.
- Interactive GUI preview: open Blender, build the scene, save the .blend, and leave the GUI open.

This is an early prototype. It does not yet generate 3D assets, characters/rigs, narration, music, or automatic scene repairs. Audio files must be supplied by the user.

## Requirements

- Blender 4.2+ recommended (the target VSE API is version-sensitive).
- Python 3.11+ for the controller.
- Optional MCP Python SDK 2.x for chat-tool integration.

The controller Python and Blender's bundled Python are separate. blentopy starts the Blender executable and loads its worker script inside Blender.

## Install

From the repository root:

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install -e .

For MCP support:

    python -m pip install -e '.[mcp]'

## Check Blender

    blentopy doctor

If Blender is not on PATH:

    blentopy doctor --blender /Applications/Blender.app/Contents/MacOS/Blender

You can also set BLENTOPY_BLENDER to the executable path.

## Preview in Blender GUI

To open a scene script in the interactive Blender application without starting a video render:

    blentopy preview examples/demo_scene.py

This launches Blender in GUI mode, executes the validated scene script, saves an editable .blend file, and leaves Blender open so you can inspect and edit the result. The default project path is renders/demo_scene.blend.

You can override the Blender executable and output paths:

    blentopy preview examples/demo_scene.py \
        --blender /Applications/Blender.app/Contents/MacOS/Blender \
        --blend-output renders/preview.blend \
        --workspace blentopy-workspace

The preview command does not render an MP4. Use the render command when you want final video output.

## Render the sample

    blentopy demo --blender /Applications/Blender.app/Contents/MacOS/Blender --output renders/demo.mp4

Default output is 720×1280, 30 FPS, 8 seconds. The render command creates:
- renders/demo.mp4 — final video
- renders/demo.blend — editable Blender project
- blentopy-workspace/ — workspace for source audio assets

Run a custom scene:

    blentopy render examples/demo_scene.py --output renders/custom.mp4

## Scene scripts

The worker injects two names: studio and math. The AI-generated Python script calls only the documented Studio API. Rendering and project saving happen automatically after the script completes.

Example:

    studio.set_timeline(duration_seconds=6, fps=30)
    studio.set_world_color((0.02, 0.03, 0.06))
    studio.add_cube("MainCube", location=(0, 0, 1), scale=(1.5, 1.5, 1.5), color=(0.1, 0.4, 0.9))
    studio.add_text("Title", "HELLO BLENDER", location=(0, -0.1, 2.5), size=0.5)
    studio.add_camera("Camera", location=(0, -12, 3), target=(0, 0, 1), orthographic_scale=7)
    studio.add_area_light("Key", location=(-4, -5, 6), energy=1400)
    studio.animate_rotation("MainCube", (0, 0, 0), (0, 360, 0))

Available methods:
- set_timeline, set_world_color
- add_plane, add_cube, add_uv_sphere, add_cylinder
- add_text, add_camera, add_area_light, set_active_camera
- animate_location, animate_rotation, animate_scale
- add_audio, fade_audio

Rotation vectors passed to animate_rotation are in degrees. Location and scale use Blender world units. Colors use RGB/RGBA values between 0 and 1.

### Audio

Place audio files inside the workspace, for example:

    blentopy-workspace/assets/narration.wav

Then call:

    studio.add_audio("Narration", "assets/narration.wav", channel=2, start_seconds=0, volume=1)
    studio.fade_audio("Narration", 0, 1, 1, 20)

blentopy creates a separate output scene containing the 3D scene strip and the audio strips. That output scene is rendered to MP4. Blender does not synthesize speech or music.

## MCP chat integration

Run the local stdio server:

    blentopy-mcp

It exposes:
- blentopy_environment — detect Blender and report its path/version.
- blentopy_render_scene — receive a Python Studio API script and render MP4 + .blend.
- blentopy_preview_scene — launch Blender GUI, execute a scene script, save .blend, and leave Blender open.
- blentopy_list_outputs — list recent output files.

A generic MCP host entry:

    {
      "mcpServers": {
        "blentopy": {
          "command": "/absolute/path/to/blentopy/.venv/bin/blentopy-mcp",
          "args": [],
          "env": {
            "BLENTOPY_WORKSPACE": "/absolute/path/to/blentopy-workspace",
            "BLENTOPY_BLENDER": "/Applications/Blender.app/Contents/MacOS/Blender"
          }
        }
      }
    }

The server uses stdio and does not open a network port. Whether a particular chat application can launch local MCP servers depends on that application's integration support. Installing blentopy does not automatically connect it to every chat interface.

## Execution boundary

AI-generated source code is executable code. To reduce risk, the MCP tool rejects arbitrary Python and raw bpy access. It accepts only:
- calls to documented studio methods;
- variable assignments and literal values;
- simple lists, tuples, dictionaries, and unary numeric signs;
- a small set of math.* constants and numeric functions.

Imports, filesystem access, shell commands, network access, loops, function definitions, raw bpy, and attribute chaining are rejected. Audio files must resolve inside the workspace.

This validator is a restricted language surface, not an operating-system sandbox. Blender and its dependencies still run with the local user's permissions. Do not treat untrusted .blend files or assets as safe. A future expert mode for raw bpy would require explicit opt-in and a separate isolation design.

## Tests

    PYTHONPATH=src python -m unittest discover -s tests -v
    python -m compileall -q src tests examples

Tests cover the script validator and render-setting limits without requiring Blender. A real render and GUI preview require a locally installed Blender executable and a desktop session.

## Current limitations

- No AI model is bundled and no AI provider API is called.
- Basic primitive-based scene creation only; no character rigging or automatic asset generation.
- No TTS generation, music generation, timeline UI, retry planner, or render farm.
- No automatic correction after a failed render.
- Blender API compatibility and actual MP4 rendering still need to be verified on the target machine.

## License

MIT. See LICENSE.
