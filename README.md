# blentopy

**An AI-native Python scene framework for building, inspecting, animating, and rendering Blender scenes.**

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
- [AI-native scene API](#ai-native-scene-api-02)
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
- Create planes, beveled cubes, UV/icosphere meshes, cylinders, cones, tori, and 3D text.
- Configure metallic, rough, coated, and emissive materials; cameras with depth of field; area and sun lights.
- Build repeated scene details with bounded loops and arithmetic.
- Use an AI-native scene graph with reusable geometry/material specs, object handles, groups, semantic placement, camera framing, custom meshes, and second-based animation tracks.
- Animate object transforms and camera moves with selectable interpolation.
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
| **--width** | Scene render width in pixels | 1080 |
| **--height** | Scene render height in pixels | 1920 |
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
| **--width** | Video width in pixels | 1080 |
| **--height** | Video height in pixels | 1920 |
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

### Live render progress

The CLI streams render status while Blender is running. It reports scene construction, scene validation, project saving, and video rendering. During video rendering, the frame counter and percentage are updated as Blender finishes writing each frame.

The percentage is based on completed output frames, not elapsed time or GPU tile/sample progress. A complex frame can therefore take longer without the counter moving. If rendering fails, blentopy includes the Blender log and the last available diagnostic details.

## Writing scene scripts

New scripts should use the AI-native scene API. The legacy Studio API remains supported for existing scripts.

The script receives:
- studio.scene: scene graph, Object3D handles, spatial helpers, camera, lighting, motion, and inspection.
- studio.geo: reusable geometry specifications.
- studio.mat: reusable PBR and emissive material specifications.
- math and a statically bounded range() iterator.

New scripts do not access bpy directly. The full authoring contract, including all methods and accepted Python syntax, is documented in [docs/AI_SYSTEM_PROMPT.md](docs/AI_SYSTEM_PROMPT.md).

### Scene-script rules (0.2)

- Use stable, descriptive IDs for important objects such as "robot.head" and "camera.main". Omit IDs for repeated incidental meshes; blentopy assigns deterministic IDs automatically.
- Define geometry with studio.geo and materials with studio.mat, then create objects through studio.scene.
- Use Object3D handles and their position, rotation, scale, and visible properties instead of looking objects up by display name.
- Prefer semantic placement with scene.place(), scene.attach(), scene.look_at(), and scene.frame() over manual coordinate calculations.
- Create a controller with motion = scene.motion(object), then use motion.track("position" | "rotation" | "scale") and keyframes measured in seconds.
- Rotation values use radians in the new API. Legacy animate_rotation() continues to accept degrees.
- Scene scripts support assignments, if/elif/else, comparisons, boolean expressions, and bounded nested range() loops.
- Each loop is limited to 128 iterations; nesting is limited to three levels; total expanded loop iterations are limited to 4,096.
- Imports, raw bpy, arbitrary builtins, filesystem access, shell commands, network access, while loops, function definitions, and private attribute access are not supported.

### Prompting an AI to create a scene

When you are not using MCP, you can ask an AI to generate a script with a prompt such as:

> Create a polished 8-second vertical 3D scene using blentopy 0.2. Use studio.scene, studio.geo, and studio.mat. Build an object hierarchy with stable IDs, use semantic placement and camera framing, create distinct PBR materials and key/fill/rim lighting, and animate with second-based motion tracks. Use if/else and bounded nested range() loops where useful. Do not use imports, bpy, functions, or unsupported Python. Return only a complete scene script.

Save the generated code to **examples/my_scene.py**, then preview it. The repository also includes a ready-made AI-native example:

~~~bash
blentopy preview examples/ai_native_scene.py
~~~

## AI-native scene API (0.2)

New scene scripts use a composable, Three.js-inspired object model designed for AI authoring:

~~~python
scene = studio.scene
geo = studio.geo
mat = studio.mat

ground = scene.surface(
    id="stage.floor",
    size=(24, 24),
    material=mat.pbr(color="#121A2A", roughness=0.75),
)

hero = scene.mesh(
    id="subject.hero",
    geometry=geo.rounded_box(size=(1.5, 1.5, 1.5), bevel=0.08),
    material=mat.pbr(color="#2878FF", metallic=0.4, roughness=0.25),
    role="hero",
)
scene.place(hero, on=ground, anchor="top")

camera = scene.camera(id="camera.main", position=(0, -9, 4))
scene.frame(camera, targets=[hero], margin=1.3)

motion = scene.motion(hero)
rise = motion.track("position")
rise.key(at=0, value=(0, 0, 1))
rise.key(at=2, value=(0, 0, 3), ease="smooth")
~~~

The first implementation includes reusable geometry/material specifications, mesh and group handles, transforms, parent-child relationships, semantic placement/alignment, camera framing, four light types, second-based transform tracks, custom meshes, and basic scene inspection. Incidental repeated objects can omit IDs and receive deterministic per-run identifiers, avoiding generated string counters inside loops.

The API is deliberately layered: use scene-level intent helpers for ordinary composition, Object3D handles for precise edits, and custom geometry only when the built-in shapes are insufficient. Use scene.update(target, ...) and scene.set_material(target, material) for targeted edits within the current script. Each separate render or preview invocation still starts a fresh scene; loading a previous .blend and applying diffs across separate AI turns is not implemented yet. This is not a complete physics solver or a replacement for all Blender modeling tools.

See [docs/AI_SYSTEM_PROMPT.md](docs/AI_SYSTEM_PROMPT.md) for the authoritative API reference and scripting contract.

## Legacy Studio API reference

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
- **set_world_color(color, strength=0.35)** sets the world/background color and illumination strength.

### Primitive objects

The Studio API includes planes, beveled cubes, smooth UV spheres, faceted ico spheres, cylinders, cones, and tori. Object creation methods accept RGB/RGBA material colors; selected methods also expose metallic, roughness, coat, bevel, and emission controls.

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
| **add_cube** | name, location=(0, 0, 0), scale=(1, 1, 1), color=(0.15, 0.45, 0.9), metallic=0.15, roughness=0.35, bevel=0.04, bevel_segments=3, emission_color=None, emission_strength=0, coat=0 |
| **add_uv_sphere** | name, location=(0, 0, 0), scale=(1, 1, 1), color=(0.1, 0.65, 0.85) |
| **add_cylinder** | name, location=(0, 0, 0), scale=(1, 1, 1), color=(0.12, 0.16, 0.23), vertices=64, metallic=0.1, roughness=0.35, bevel=0.025 |
| **add_ico_sphere** | name, location, scale, color, subdivisions=3, metallic=0, roughness=0.4 |
| **add_cone** | name, location, scale, color, radius1=1, radius2=0, depth=2, vertices=48, bevel=0.015 |
| **add_torus** | name, location, rotation, scale, color, major_radius=1, minor_radius=0.2, major_segments=64, minor_segments=16 |

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

**add_camera(name, location=(0, -12, 4), target=(0, 0, 0), lens=50, orthographic_scale=None, focus_object_name=None, dof_fstop=2.8)**

- **location**: Camera position.
- **target**: Point the camera should face. It must differ from the camera location.
- **lens**: Focal length, clamped to the range 10–300.
- **orthographic_scale**: When provided, switches the camera to orthographic projection. When omitted, perspective projection is used.
- **focus_object_name**: Optional existing object to focus on; enables depth of field for perspective cameras.
- **dof_fstop**: Depth-of-field aperture setting. Lower values create a shallower focus range.
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

Creates an Area Light at the specified location and points it toward **target**. Energy is clamped to a non-negative value, and light size is clamped to at least 0.1. Supported shape values are DISK, SQUARE, RECTANGLE, and ELLIPSE. The API also supports **add_sun_light(name, rotation=(0.5, -0.5, -0.5), energy=2, color=(1, 0.92, 0.78), angle=0.08)**.

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

- **animate_location(name, start_location, end_location, start_frame=1, end_frame=None, interpolation="BEZIER")**
- **animate_rotation(name, start_degrees, end_degrees, start_frame=1, end_frame=None, interpolation="BEZIER")**
- **animate_scale(name, start_scale, end_scale, start_frame=1, end_frame=None, interpolation="BEZIER")**
- **animate_camera(name, start_location, end_location, start_target, end_target, start_frame=1, end_frame=None, interpolation="BEZIER")**

All transform animation methods accept **BEZIER**, **LINEAR**, or **CONSTANT** interpolation. If **end_frame** is omitted, the final frame of the content scene is used. Rotation arguments are specified in degrees and converted to radians internally. The target object or camera must already exist.

### Math helpers

The following constants and functions are exposed through **math**:

- Constants: **math.pi**, **math.tau**, **math.e**
- Functions: **math.sin**, **math.cos**, **math.tan**, **math.radians**, **math.degrees**, **math.sqrt**

The validator allows assignments, conditionals, comparisons, boolean expressions, basic arithmetic, and bounded nested range() loops. Nested loops are limited to three levels and 4,096 expanded iterations in total. Function definitions, unbounded loops, imports, and arbitrary builtins remain unsupported. The only builtin exposed to scripts is validated range(), used directly as a for-loop iterator.

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

At startup, the MCP server loads **docs/AI_SYSTEM_PROMPT.md** and sends it as server instructions to the connected AI client. This gives the model the scene language, API reference, and cinematic quality rules without requiring you to paste the entire document into every request. Keep this file available in the repository checkout when using the editable installation.

### 4. Available MCP tools

| Tool | Description |
|---|---|
| **blentopy_environment** | Detects Blender and reports its version, executable path, and workspace. |
| **blentopy_preview_scene** | Opens Blender GUI, runs a scene script, saves a .blend project, and leaves Blender open. Does not render an MP4. |
| **blentopy_render_scene** | Runs a scene script and exports an MP4 and .blend project. |
| **blentopy_list_outputs** | Lists recent files in the workspace's renders directory. |

The render and preview tools accept Python source code as a string. The scene language provides **studio**, **math**, and bounded **range()** loops; the MCP server validates scripts with the same restrictions as the CLI. Default output is 1080×1920 at 30 FPS for 8 seconds.

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

### Script validation error

Validation errors identify the source file, line, code, and a suggested correction when possible. Read the exact diagnostic before changing the script.

The scene language is deliberately smaller than general Python. It does not expose built-ins such as `max()`, `min()`, `len()`, or `round()`. The only built-in call is `range()` directly in a bounded `for` loop. Use the API methods documented in [docs/AI_SYSTEM_PROMPT.md](docs/AI_SYSTEM_PROMPT.md).

Both animation forms below are supported:

```python
motion = scene.motion(hero)
track = motion.track("rotation")
```

```python
track = scene.motion(hero).track("rotation")
```

Store the returned track in a variable before calling `track.key(...)`. Other method-call chains are not supported.

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

Scene scripts run in a restricted Python language and receive only the blentopy API, a limited math namespace, and bounded range(). The validator allows documented API calls, simple variables, approved object property assignments, lists, tuples, dictionaries, arithmetic, comparisons, boolean expressions, conditionals, and statically bounded nested loops.

The validator rejects imports, raw bpy access, private/dunder attributes, arbitrary builtins, filesystem/process/network operations, while loops, function and class definitions, comprehensions, dynamic loop bounds, and undocumented API calls. Loops are limited to 128 iterations each, three nested levels, and 4,096 total expanded iterations.

**These restrictions are not an operating-system sandbox.** Blender and its dependencies still run with the permissions of the local user. Do not treat untrusted .blend files, scripts, or source assets as safe.

## Current limitations

- The AI-native API supports geometry/material specs, Object3D handles, groups, custom meshes, spatial helpers, camera/light creation, second-based transform tracks, and targeted in-script edits. Sculpting, rigging, and complex character animation are not implemented.
- No AI model is bundled with blentopy.
- Text-to-speech, music generation, and image generation require separate tools.
- Advanced modeling, rigging, and character workflows are not implemented.
- Automatic AI retries and error repair are not implemented.
- Persistent incremental editing across separate render/preview invocations is not implemented; each invocation starts from a fresh scene.
- Blender's VSE API can differ between Blender versions and requires compatibility testing.
- GUI preview and rendering still need to be verified on the target machine and Blender installation.

## License

MIT. See [LICENSE](LICENSE).
