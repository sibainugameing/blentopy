# blentopy

**A Python-first local bridge for creating Blender scenes, inspecting them in the Blender GUI, and rendering MP4 videos.**

blentopy is not an AI model and does not call a hosted AI API. An MCP-capable chat client (or a person writing a scene script) supplies Python code. blentopy validates that code, launches the local Blender executable, builds the scene, and can export an editable Blender project and an MP4 video. No AI API key is required by blentopy.

> blentopy is an early-stage prototype. GUI preview and video rendering should be tested on your own operating system and Blender version before relying on them.

## Contents

- [What it can do](#what-it-can-do)
- [Requirements](#requirements)
- [Installation](#installation)
- [Updating](#updating)
- [Checking the Blender installation](#checking-the-blender-installation)
- [Previewing a scene in the Blender GUI](#previewing-a-scene-in-the-blender-gui)
- [Rendering an MP4](#rendering-an-mp4)
- [Writing scene scripts](#writing-scene-scripts)
- [Studio API reference](#studio-api-reference)
- [Using audio](#using-audio)
- [Connecting an MCP chat client](#connecting-an-mcp-chat-client)
- [Output files](#output-files)
- [Troubleshooting](#troubleshooting)
- [Tests](#tests)
- [Security model](#security-model)
- [Current limitations](#current-limitations)
- [License](#license)

## What it can do

### Supported workflows

- Launch Blender's desktop application and build a scene from a Python script.
- Preview the generated scene in Blender, then inspect and edit the project manually.
- Create basic objects such as planes, cubes, UV spheres, cylinders, and text.
- Configure materials, cameras, lights, and the world background.
- Animate object location, rotation, and scale with keyframes.
- Add existing audio files to the Video Sequence Editor (VSE).
- Render an MP4 video using H.264 video and AAC audio.
- Save an editable .blend project alongside a rendered video.
- Expose local Blender operations as tools to an MCP-compatible chat client.

### Not supported yet

- Automatically generating detailed 3D models or characters.
- Character rigging, walk cycles, or motion capture.
- Generating narration, sound effects, or music.
- Free-form image understanding and image-to-model generation.
- Automatic AI diagnosis, repair, and retry after a scene-generation error.
- Continuous real-time AI manipulation of objects in an already-open Blender session. The current workflow executes a scene script as a unit.

## Requirements

- macOS, Windows, or Linux.
- Python 3.11 or newer for the blentopy controller.
- Blender 4.2 or newer is recommended. The VSE API is version-sensitive.
- A desktop session for GUI preview.
- MCP Python SDK 2.x only if you want to use the MCP server.

The controller's Python environment and Blender's bundled Python environment are separate. blentopy starts the Blender executable and runs its worker script inside Blender.

## Installation

Open a terminal and move to the repository directory:

~~~bash
cd blentopy
~~~

Create and activate a virtual environment:

~~~bash
python3 -m venv .venv
source .venv/bin/activate
~~~

On Windows PowerShell, activate it with:

~~~powershell
.venv\Scripts\Activate.ps1
~~~

Install blentopy in editable mode:

~~~bash
python -m pip install --upgrade pip
python -m pip install -e .
~~~

To enable the MCP server as well, install the optional MCP dependency:

~~~bash
python -m pip install -e '.[mcp]'
~~~

Keep the virtual environment activated when running the commands below.

## Updating

Pull the latest code from the repository's main branch, then refresh the editable installation:

~~~bash
git switch main
git pull --ff-only origin main
source .venv/bin/activate
python -m pip install -e . --force-reinstall
~~~

On Windows PowerShell, activate the environment with:

~~~powershell
.venv\Scripts\Activate.ps1
~~~

Check that the command-line interface is available:

~~~bash
blentopy --help
~~~

The help output should list the available commands: **doctor**, **demo**, **render**, and **preview**.

If the CLI reports that **preview** is an invalid choice, the shell may be using an old entry point or a different Python environment. Reinstall from the repository root, then inspect the executable and installed package:

~~~bash
which blentopy
python -m pip show blentopy
blentopy --help
~~~

On Windows, use **where.exe blentopy** instead of **which blentopy**.

## Checking the Blender installation

Ask blentopy to locate Blender:

~~~bash
blentopy doctor
~~~

If Blender is not on your PATH, pass the executable path explicitly.

### macOS

~~~bash
blentopy doctor --blender /Applications/Blender.app/Contents/MacOS/Blender
~~~

You can also set the **BLENTOPY_BLENDER** environment variable:

~~~bash
export BLENTOPY_BLENDER="/Applications/Blender.app/Contents/MacOS/Blender"
~~~

This setting applies to commands launched from the same terminal session. On Windows PowerShell, use:

~~~powershell
$env:BLENTOPY_BLENDER = "C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"
~~~

Use the actual path for your Blender installation.

## Previewing a scene in the Blender GUI

The **preview** command opens Blender as a desktop application, runs a scene script, saves an editable .blend file, and leaves Blender open for inspection and manual editing. It does **not** render an MP4.

### Basic command

Run this from the repository root:

~~~bash
blentopy preview examples/demo_scene.py
~~~

On macOS, if Blender is not discoverable automatically:

~~~bash
blentopy preview examples/demo_scene.py \
  --blender /Applications/Blender.app/Contents/MacOS/Blender
~~~

### What happens during preview

1. blentopy launches Blender in GUI mode.
2. Blender loads the blentopy worker and the scene script.
3. The worker runs the supported Studio API calls to create the scene.
4. The .blend project is saved.
5. blentopy waits for confirmation that the project was saved successfully.
6. The Blender GUI remains open so you can inspect and edit the scene.
7. The CLI prints the saved project path, Blender process ID, and preview log path.

The CLI does not report preview success merely because the Blender window appeared. It waits for the save confirmation.

### Preview options

~~~bash
blentopy preview examples/demo_scene.py \
  --blender /Applications/Blender.app/Contents/MacOS/Blender \
  --blend-output renders/my_preview.blend \
  --workspace blentopy-workspace \
  --width 720 \
  --height 1280 \
  --fps 30 \
  --duration 8 \
  --startup-timeout 120
~~~

| Option | Description | Default |
|---|---|---|
| **script** | Python scene script to execute | Required |
| **--blender** | Path to the Blender executable | Automatic discovery |
| **--blend-output** | Destination for the .blend project | renders/&lt;script-name&gt;.blend |
| **--workspace** | Workspace directory, including audio assets | blentopy-workspace |
| **--width** | Scene render width in pixels | 720 |
| **--height** | Scene render height in pixels | 1280 |
| **--fps** | Frame rate | 30 |
| **--duration** | Scene duration in seconds | 8 |
| **--startup-timeout** | Maximum time to wait for the preview scene to be saved | 120 seconds |

The startup timeout must be between 1 and 600 seconds. If Blender fails to start, exits early, or does not save the scene before the deadline, the command reports an error and includes the log path.

### Inspecting and editing the project

After preview succeeds, you can use Blender normally:

- Inspect objects, cameras, and lights in the 3D Viewport.
- Select objects in the Outliner.
- Adjust transforms and materials.
- Inspect keyframes in the Timeline.
- Save manual changes using Blender's normal save commands.

The generated .blend file is a standard Blender project, not a proprietary blentopy format.

## Rendering an MP4

Use **render** or **demo** when you want a video file rather than an interactive GUI preview.

### Render the built-in demo

~~~bash
blentopy demo
~~~

On macOS, specify the Blender executable and output path explicitly:

~~~bash
blentopy demo \
  --blender /Applications/Blender.app/Contents/MacOS/Blender \
  --output renders/demo.mp4
~~~

### Render your own scene script

~~~bash
blentopy render examples/demo_scene.py \
  --output renders/custom.mp4
~~~

### Render options

The **render** and **demo** commands share these options:

| Option | Description | Default |
|---|---|---|
| **--blender** | Path to the Blender executable | Automatic discovery |
| **--output** | Destination for the MP4 video | renders/&lt;script-name&gt;.mp4 |
| **--blend-output** | Destination for the editable Blender project | Same base name as the MP4 |
| **--workspace** | Workspace directory for assets such as audio | blentopy-workspace |
| **--width** | Video width in pixels | 720 |
| **--height** | Video height in pixels | 1280 |
| **--fps** | Frame rate | 30 |
| **--duration** | Video duration in seconds | 8 |
| **--timeout** | Maximum render time in seconds | 3600 |

The current render settings are constrained:

- Width and height must each be between 256 and 1920 pixels.
- Total resolution must not exceed 4,194,304 pixels.
- FPS must be between 1 and 60.
- Duration must be between 1 and 120 seconds.
- Total frame count must not exceed 3,600 frames.

The renderer saves both the MP4 and the editable .blend project.

## Writing scene scripts

Whether code is written by a person or generated by an AI, it must use only the Studio API and Python constructs accepted by blentopy's validator.

Unlike a normal Blender script, a blentopy scene script cannot access **bpy** directly. Scene operations are performed through the injected **studio** object. The **math** module is also provided; you do not need to import it.

### Minimal scene example

~~~python
studio.set_timeline(duration_seconds=6, fps=30)
studio.set_world_color((0.02, 0.03, 0.06))

studio.add_cube(
    "Cube",
    location=(0, 0, 1),
    scale=(1, 1, 1),
    color=(0.1, 0.4, 0.9),
)

studio.add_camera(
    "Camera",
    location=(0, -12, 3),
    target=(0, 0, 1),
    orthographic_scale=7,
)

studio.add_area_light(
    "KeyLight",
    location=(-4, -5, 6),
    target=(0, 0, 1),
    energy=1400,
)
~~~

### Scene-script rules

- The names **studio** and **math** are provided automatically.
- Prefer keyword arguments. They make scripts easier to read and revise.
- Give objects unique names. Names used in animation calls must match the names used when the objects were created.
- Locations and scales use Blender world units.
- Colors use RGB or RGBA values, with each channel between 0 and 1.
- Rotation values passed to **animate_rotation** are in degrees.
- The text object's **rotation** argument is in radians.
- Scene duration is measured in seconds; FPS means frames per second.
- Creating an object does not guarantee that it will appear in the camera view. Set the camera position, target, and framing deliberately.
- The default text rotation is intended to make text face forward; adjust it to match your camera.
- Imports, loops, conditional statements, function definitions, file operations, and direct Blender API access are not supported.

### Prompting an AI to create a scene

When you are not using MCP, you can ask an AI to generate a script with a prompt such as:

> Create an animated 3D scene for an 8-second vertical video using only the blentopy Studio API. Include continuous object motion, a camera, lighting, and materials. Do not use imports, bpy, loops, conditional statements, or function definitions. Return only the scene script.

Save the generated code to **examples/my_scene.py**, then preview it:

~~~bash
blentopy preview examples/my_scene.py
~~~

## Studio API reference

### Common values

| Value | Meaning | Example |
|---|---|---|
| **location** | X/Y/Z position | (0, 0, 2) |
| **scale** | X/Y/Z scale | (1, 2, 1) |
| **target** | Point a camera or light should face | (0, 0, 0) |
| **color** | RGB or RGBA color, channels from 0 to 1 | (0.2, 0.5, 1.0) |
| **size** | Object size or light size; meaning depends on the method | Method-specific |
| **start_frame / end_frame** | Animation start and end frames | 1, 120 |
| **start_seconds** | Audio start time in seconds | 2.5 |

### Timeline and world

~~~python
studio.set_timeline(duration_seconds=8, fps=30)
studio.set_world_color((0.025, 0.03, 0.05))
~~~

- **set_timeline(duration_seconds, fps=None)** sets the content scene duration and frame rate.
- **set_world_color(color)** sets the world/background color.

### Primitive objects

~~~python
studio.add_plane(
    "Ground",
    location=(0, 0, 0),
    scale=(5, 5, 1),
    color=(0.08, 0.10, 0.14),
)

studio.add_cube(
    "Cube",
    location=(0, 0, 1),
    scale=(1, 1, 1),
    color=(0.15, 0.45, 0.9),
    metallic=0.15,
    roughness=0.35,
)

studio.add_uv_sphere(
    "Sphere",
    location=(2, 0, 1),
    scale=(1, 1, 1),
    color=(0.1, 0.65, 0.85),
)

studio.add_cylinder(
    "Cylinder",
    location=(-2, 0, 1),
    scale=(1, 1, 1),
    color=(0.12, 0.16, 0.23),
    vertices=64,
)
~~~

| Method | Arguments |
|---|---|
| **add_plane** | name, location=(0, 0, 0), scale=(5, 5, 1), color=(0.08, 0.10, 0.14) |
| **add_cube** | name, location=(0, 0, 0), scale=(1, 1, 1), color=(0.15, 0.45, 0.9), metallic=0.15, roughness=0.35 |
| **add_uv_sphere** | name, location=(0, 0, 0), scale=(1, 1, 1), color=(0.1, 0.65, 0.85) |
| **add_cylinder** | name, location=(0, 0, 0), scale=(1, 1, 1), color=(0.12, 0.16, 0.23), vertices=64 |

Each method returns the created object's name. UV spheres use smooth shading. Cylinders also use smooth shading; their vertex count is clamped to the range 12–128.

### Text

~~~python
studio.add_text(
    "Title",
    "HELLO BLENDER",
    location=(0, -0.1, 2.5),
    size=0.5,
    color=(0.95, 0.97, 1),
    rotation=(1.5708, 0, 0),
    align="CENTER",
    extrude=0,
)
~~~

**add_text(name, body, location=(0, 0, 0), size=0.5, color=(0.95, 0.97, 1), rotation=(1.57079632679, 0, 0), align="CENTER", extrude=0)**

- **body**: Text to display.
- **size**: Text size.
- **rotation**: X/Y/Z rotation in radians.
- **align**: LEFT, CENTER, or RIGHT. Unsupported values fall back to CENTER.
- **extrude**: Text extrusion depth; values below zero are clamped to zero.

### Camera

~~~python
studio.add_camera(
    "Camera",
    location=(0, -12, 4),
    target=(0, 0, 1),
    lens=50,
    orthographic_scale=7,
)
~~~

**add_camera(name, location=(0, -12, 4), target=(0, 0, 0), lens=50, orthographic_scale=None)**

- **location**: Camera position.
- **target**: Point the camera should face. It must differ from the camera location.
- **lens**: Focal length, clamped to the range 10–300.
- **orthographic_scale**: When provided, switches the camera to orthographic projection. When omitted, perspective projection is used.
- **set_active_camera(name)** sets an existing camera object as the active camera.

### Area light

~~~python
studio.add_area_light(
    "KeyLight",
    location=(-4, -5, 6),
    target=(0, 0, 1),
    energy=1400,
    size=5,
    color=(1, 1, 1),
)
~~~

**add_area_light(name, location=(4, -5, 7), target=(0, 0, 0), energy=1200, size=5, color=(1, 1, 1))**

Creates an Area Light at the specified location and points it toward **target**. Energy is clamped to a non-negative value, and light size is clamped to at least 0.1.

### Animation

~~~python
studio.animate_location(
    "Cube",
    start_location=(0, 0, 1),
    end_location=(0, 0, 3),
    start_frame=1,
    end_frame=120,
)

studio.animate_rotation(
    "Cube",
    start_degrees=(0, 0, 0),
    end_degrees=(0, 360, 0),
    start_frame=1,
    end_frame=120,
)

studio.animate_scale(
    "Cube",
    start_scale=(1, 1, 1),
    end_scale=(1.5, 1.5, 1.5),
    start_frame=1,
    end_frame=120,
)
~~~

- **animate_location(name, start_location, end_location, start_frame=1, end_frame=None)**
- **animate_rotation(name, start_degrees, end_degrees, start_frame=1, end_frame=None)**
- **animate_scale(name, start_scale, end_scale, start_frame=1, end_frame=None)**

If **end_frame** is omitted, the final frame of the content scene is used. Rotation arguments are specified in degrees and converted to radians internally. The target object must already exist.

### Math helpers

The following constants and functions are exposed through **math**:

- Constants: **math.pi**, **math.tau**, **math.e**
- Functions: **math.sin**, **math.cos**, **math.tan**, **math.radians**, **math.degrees**, **math.sqrt**

The validator currently does not allow loops, conditional statements, or arithmetic operators. Math helpers can be called with supported literal or variable arguments, but they do not turn the script language into general-purpose Python.

## Using audio

blentopy does not generate narration, sound effects, or music. It can place an existing audio file into the output scene's Video Sequence Editor.

### 1. Put the audio file inside the workspace

For example:

~~~text
blentopy-workspace/
└── assets/
    └── narration.wav
~~~

The workspace is the directory supplied with **--workspace**. Its default is **blentopy-workspace** in the current working directory.

### 2. Add the audio from your scene script

~~~python
studio.add_audio(
    "Narration",
    "assets/narration.wav",
    channel=2,
    start_seconds=0,
    volume=1,
)
~~~

Relative file paths are resolved inside the workspace. Absolute paths are also accepted only when the resolved file is inside the workspace. Files outside the workspace are rejected.

**add_audio(name, filepath, channel=2, start_seconds=0, volume=1)**

- **name**: Name of the audio strip.
- **filepath**: Path to an existing audio file inside the workspace.
- **channel**: VSE channel. Values are clamped to at least 2.
- **start_seconds**: Audio start time in seconds.
- **volume**: Initial volume, clamped to the range 0–1.

### 3. Animate audio volume

~~~python
studio.fade_audio("Narration", 0, 1, 1, 20)
~~~

**fade_audio(name, start_volume, end_volume, start_frame, end_frame)** inserts volume keyframes at the specified frames. In the example, the volume changes from 0 to 1 between frames 1 and 20.

The rendered output scene combines the 3D content scene strip with audio strips. The 3D content scene and the output/compositing scene are separate Blender scenes.

## Connecting an MCP chat client

The Model Context Protocol (MCP) lets an MCP-compatible chat application call the local blentopy server. Your chat application must support launching a local stdio MCP server.

### 1. Install the optional MCP dependency

~~~bash
source .venv/bin/activate
python -m pip install -e '.[mcp]'
~~~

### 2. Verify the MCP command

~~~bash
blentopy-mcp
~~~

The server communicates over standard input/output (stdio). Normally, you register this command in the MCP client's configuration and let the client launch it. Running it directly in a terminal may appear to wait for input; that is expected for a stdio server.

### 3. Configure your MCP client

Add a server entry to the configuration file used by your MCP-compatible application. Replace the example paths with the real paths on your machine.

~~~json
{
  "mcpServers": {
    "blentopy": {
      "command": "/ABSOLUTE/PATH/blentopy/.venv/bin/blentopy-mcp",
      "args": [],
      "env": {
        "BLENTOPY_WORKSPACE": "/ABSOLUTE/PATH/blentopy-workspace",
        "BLENTOPY_BLENDER": "/Applications/Blender.app/Contents/MacOS/Blender"
      }
    }
  }
}
~~~

- **command**: Absolute path to the blentopy-mcp executable inside the virtual environment.
- **BLENTOPY_WORKSPACE**: Workspace for source assets and generated files.
- **BLENTOPY_BLENDER**: Path to the Blender executable.

Absolute paths are recommended. Relative paths and home-directory shortcuts may be interpreted differently by different MCP clients.

### 4. Available MCP tools

| Tool | Description |
|---|---|
| **blentopy_environment** | Detects Blender and reports its version, executable path, and workspace. |
| **blentopy_preview_scene** | Opens Blender GUI, runs a scene script, saves a .blend project, and leaves Blender open. Does not render an MP4. |
| **blentopy_render_scene** | Runs a scene script and exports an MP4 and .blend project. |
| **blentopy_list_outputs** | Lists recent files in the workspace's renders directory. |

The render and preview tools accept Python source code as a string. The MCP server validates it with the same restricted scene-script validator used by the CLI.

### 5. Example requests to the connected AI

Once the MCP server is connected, you can ask the chat client to:

- "Run a Blender GUI preview so I can inspect the scene."
- "Create an eight-second scene with a blue sphere moving up and down."
- "Move the camera back slightly so the entire object is visible."
- "Preview the scene and leave the generated Blender project open."
- "Render this scene to an MP4."

Whether a tool runs automatically depends on the MCP client's configuration and the AI's tool-use decisions. Registering the server does not guarantee that every request will execute without user approval.

## Output files

### CLI preview

By default, a preview creates files similar to:

~~~text
renders/
├── demo_scene.blend
└── demo_scene-<unique-id>.preview.log
~~~

The exact log filename contains a generated identifier.

### CLI render

~~~text
renders/
├── demo.mp4
└── demo.blend
~~~

### MCP-generated files

MCP scripts and output files are stored in the configured workspace:

~~~text
blentopy-workspace/
├── scripts/
│   └── <scene-name>-<timestamp>.py
└── renders/
    ├── <scene-name>-<timestamp>.blend
    └── <scene-name>-<timestamp>.mp4
~~~

A GUI preview does not create an MP4. The preview log captures Blender's standard output and standard error. When something goes wrong, inspect the end of that log.

## Troubleshooting

### blentopy command not found

The virtual environment may not be active, or the package may not have been installed successfully.

~~~bash
source .venv/bin/activate
python -m pip install -e . --force-reinstall
~~~

On Windows PowerShell:

~~~powershell
.venv\Scripts\Activate.ps1
python -m pip install -e . --force-reinstall
~~~

### preview is an invalid choice

The shell may be using an outdated CLI entry point.

~~~bash
source .venv/bin/activate
git pull --ff-only origin main
python -m pip install -e . --force-reinstall
which blentopy
blentopy --help
~~~

On Windows, use **where.exe blentopy** instead of **which blentopy**.

### Blender cannot be found

Pass the executable path to the doctor command:

~~~bash
blentopy doctor --blender "/Applications/Blender.app/Contents/MacOS/Blender"
~~~

If Blender is installed elsewhere, use its actual executable path. You can also configure **BLENTOPY_BLENDER**.

### GUI preview does not start or exits early

1. Check the Blender executable path with **blentopy doctor**.
2. Confirm that Blender can start normally as a desktop application.
3. Increase **--startup-timeout** if Blender needs more time to start.
4. Open the .preview.log file printed by the CLI and inspect the final error messages.
5. Confirm that the blentopy package in the active virtual environment is up to date.

Example:

~~~bash
blentopy preview examples/demo_scene.py \
  --blender "/Applications/Blender.app/Contents/MacOS/Blender" \
  --startup-timeout 180
~~~

GUI preview requires a desktop session. It may not work in a headless environment such as an SSH session without a display.

### Unknown Studio API method or unsupported Python syntax

The script uses an API method or Python construct that is not currently allowed. Refer to the Studio API reference and rewrite the script using supported calls.

For example, the following is not allowed:

~~~python
import bpy

for index in range(10):
    ...
~~~

Instead, write the required Studio API calls explicitly.

### Objects do not appear in the camera view

- Check the camera's location.
- Check that the camera target points toward the objects.
- Check object locations and scales.
- Adjust the camera lens or orthographic scale.
- Switch to Camera View in the Blender GUI to inspect the framing.

### Rendering takes too long

- Reduce the number of objects.
- Lower the output resolution.
- Shorten the video duration.
- Reduce the frame rate.
- Use GUI preview to check composition before starting a full render.

## Tests

The Python unit tests and syntax compilation can be run without Blender:

~~~bash
source .venv/bin/activate
PYTHONPATH=src python -m unittest discover -s tests -v
python -m compileall -q src tests examples
~~~

Actual GUI preview and MP4 rendering require an installed Blender executable. GUI preview also requires a usable desktop session.

## Security model

Scene scripts are restricted to a deliberately small subset of Python. The validator currently accepts:

- Calls to documented studio API methods.
- Supported math constants and functions.
- Simple variable assignments.
- String, numeric, boolean, and None literals.
- Lists, tuples, and dictionaries.
- Unary plus and minus.

The validator rejects:

- Imports.
- Direct access to bpy.
- Filesystem operations.
- Shell commands.
- Network access.
- Loops and conditional statements.
- Function and class definitions.
- Attribute chaining and calls on arbitrary variables.
- Unsupported Python syntax and unknown Studio API methods.

**These restrictions are not an operating-system sandbox.** Blender and its dependencies still run with the permissions of the local user. Do not treat untrusted .blend files, scripts, or source assets as safe.

## Current limitations

- The current API focuses on basic primitives and simple scene assembly.
- No AI model is bundled with blentopy.
- Text-to-speech, music generation, and image generation require separate tools.
- Advanced modeling, rigging, and character workflows are not implemented.
- Automatic AI retries and error repair are not implemented.
- Blender's VSE API can differ between Blender versions and requires compatibility testing.
- GUI preview and rendering still need to be verified on the target machine and Blender installation.

## License

MIT. See [LICENSE](LICENSE).
