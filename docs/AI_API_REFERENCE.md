> Detailed method and workflow reference. Start with [AI_SYSTEM_PROMPT.md](AI_SYSTEM_PROMPT.md) for the compact runtime contract and interface-selection rules.

# blentopy — Detailed AI API Reference

You are the scene director, 3D modeler, layout artist, and cinematographer for **blentopy**. Create intentional, detailed, animated scenes rather than generic primitive turntables.

This document is the detailed API reference. The compact generation contract lives in [AI_SYSTEM_PROMPT.md](AI_SYSTEM_PROMPT.md). Scene scripts are ordinary Python executed inside Blender's own Python runtime. The blentopy scene API is a convenience layer, not a whitelist or a replacement for Blender. Use the complete bpy/mathutils/Python capabilities needed to fulfil the request. Do not claim a render succeeded unless the tool reports success.

## 1. Core design principles

- **Intent over coordinates:** express relationships such as placing an object on a surface or framing a subject, rather than calculating every coordinate manually.
- **Composable scene graph:** keep geometry, materials, objects, groups, cameras, lights, and motion separate.
- **Stable identity:** assign meaningful, unique IDs to objects and refer to handles instead of string names.
- **Inspectability:** create a scene that can be inspected and validated after construction.
- **Incremental editing:** prefer changing an existing object or its properties over rebuilding an entire scene.
- **Blender-native output:** the result is an ordinary editable .blend project.

## 2. Execution contract

The script receives these names automatically:

- studio: the blentopy convenience API.
- bpy: Blender's complete Python API module.
- math: Python's standard math module.
- mathutils: Blender's mathutils module.

Scripts run with normal Python built-ins and normal import support. Use imports, helper functions, classes, comprehensions, generators, context managers, exception handling, while/for loops, standard-library modules, mathutils, bpy.data, bpy.context, bpy.ops, modifiers, node trees, constraints, drivers, and other Blender APIs whenever useful. There is no AST method whitelist, custom scene-script grammar, per-loop iteration cap, or disabled-builtins namespace.

The syntax preflight catches Python syntax errors and grossly oversized input; it does not decide which Blender functions are allowed. The Blender render/preview/edit process has an operation timeout and staged output publication, and blentopy performs post-execution scene diagnostics. These are operational safeguards, not a Python security sandbox. A script has the capabilities of the Blender process, including filesystem and import access. Only execute scene scripts you trust, and do not overwrite source files or unrelated projects.

The new API is exposed through:
- studio.scene: scene graph, object creation, spatial operations, camera, lights, animation, and inspection.
- studio.geo: reusable geometry descriptions.
- studio.mat: reusable material descriptions.

The legacy studio.add_cube(), studio.add_camera(), studio.animate_location(), and related Studio methods remain available for older scripts. Prefer the new API for new work. Do not mix legacy string-based object references with new Object3D handles unless there is a specific reason.

## 3. Minimal scene

~~~python
scene = studio.scene
geo = studio.geo
mat = studio.mat

scene.configure(
    duration=8,
    fps=30,
    background="#07101F",
)

ground_material = mat.pbr(color="#101827", roughness=0.72)
ground = scene.surface(
    id="environment.ground",
    size=(30, 30),
    material=ground_material,
)

hero_geometry = geo.rounded_box(
    size=(1.6, 1.6, 1.6),
    bevel=0.08,
)
hero_material = mat.pbr(
    color="#2878FF",
    metallic=0.45,
    roughness=0.24,
)
hero = scene.mesh(
    id="subject.hero",
    geometry=hero_geometry,
    material=hero_material,
    role="hero",
)
scene.place(hero, on=ground, anchor="top")

camera = scene.camera(
    id="camera.main",
    projection="perspective",
    lens=50,
    position=(0, -9, 4),
)
scene.frame(camera, targets=[hero], margin=1.35)

key_light = scene.light(
    id="light.key",
    type="area",
    target=hero,
    position=(-4, -5, 6),
    color="#FFF0DB",
    energy=1500,
    size=5,
)
rim_light = scene.light(
    id="light.rim",
    type="area",
    target=hero,
    position=(3, 2, 4),
    color="#4A8DFF",
    energy=1100,
    size=3,
)

motion = scene.motion(hero)
rise = motion.track("position")
rise.key(at=0, value=(0, 0, 0.8), ease="smooth")
rise.key(at=2, value=(0, 0, 2.4), ease="smooth")

# The documented direct form is also valid:
spin = scene.motion(hero).track("rotation")
spin.key(at=0, value=(0, 0, 0))
spin.key(at=2, value=(0, 0, math.tau), ease="linear")
rise.key(at=4, value=(0, 0, 1.4), ease="smooth")
~~~

The code above uses only documented methods. The timeline is measured in seconds. Rotation vectors use radians.

## 4. Scene configuration

~~~python
scene.configure(duration=8, fps=30, background="#07101F")
~~~

- duration: optional scene duration in seconds; when supplied, it must be greater than 0 and at most 120. When omitted, keep the duration requested by the render or preview job.
- fps: optional frame rate; when supplied, it must be an integer from 1 through 60. When omitted, keep the frame rate requested by the render or preview job.
- background: RGB/RGBA numeric channels from 0 to 1, or #RRGGBB / #RRGGBBAA.

The render or preview job's duration and FPS are the initial timeline settings. Call configure() near the beginning only when you need to override them; a background-only call must not reset the timeline.

## 5. Geometry descriptions

Geometry descriptions are reusable values. They do not create Blender objects until passed to scene.mesh() or scene.surface().

~~~python
box = geo.box(size=(2, 1, 1), bevel=0.04)
rounded = geo.rounded_box(size=(1, 2, 1), bevel=0.08)
ball = geo.sphere(radius=0.5, segments=48, rings=24)
floor = geo.plane(size=(20, 20))
column = geo.cylinder(radius=0.4, height=2, segments=48)
peak = geo.cone(radius=0.7, height=1.5, segments=48)
ring = geo.torus(major_radius=1, minor_radius=0.08)
custom = geo.mesh(
    vertices=((0, 0, 0), (1, 0, 0), (0.5, 0, 1)),
    faces=((0, 1, 2),),
)
~~~

Available methods:

- geo.box(size=(1, 1, 1), bevel=0)
- geo.rounded_box(size=(1, 1, 1), bevel=0.06)
- geo.sphere(radius=0.5, segments=32, rings=16)
- geo.plane(size=(10, 10))
- geo.cylinder(radius=0.5, height=1, segments=32)
- geo.cone(radius=0.5, height=1, segments=32)
- geo.torus(major_radius=1, minor_radius=0.1, major_segments=48, minor_segments=12)
- geo.mesh(vertices, faces)

Custom mesh limits: at most 10,000 vertices and 20,000 faces. Each face must contain at least three valid integer vertex indices.

Geometry sizes are in Blender world units. Use sufficient segments for smooth silhouettes, but do not create unnecessary polygon counts.

## 6. Materials

Material descriptions can be shared by multiple mesh objects.

~~~python
paint = mat.pbr(
    color="#2878FF",
    roughness=0.28,
    metallic=0.35,
    coat=0.2,
)

glow = mat.emissive(
    color="#38BFFF",
    strength=2.5,
)
~~~

Available methods:

- mat.pbr(color="#B8C4D8", roughness=0.45, metallic=0, coat=0, emission=None, emission_strength=0)
- mat.emissive(color="#FFFFFF", strength=2)

Colors accept hex strings or RGB/RGBA numeric values from 0 to 1. PBR roughness, metallic, and coat values must be between 0 and 1. Emission strength must be non-negative.

Use different roughness values for metal, plastic, ceramic, fabric-like, and painted surfaces. Avoid making every material fully metallic or highly reflective. Emission should be an accent, not a substitute for lighting.


## 6.1 Procedural repetition

Use omitted IDs for incidental repeated objects. The generated ID is deterministic within the current script run, so no string formatting or counter conversion is needed in the AI-authored script.

~~~python
for row in range(4):
    for column in range(6):
        bead = scene.mesh(
            geometry=geo.sphere(radius=0.06, segments=16, rings=8),
            material=mat.emissive(color="#32BFFF", strength=0.5),
            role="decoration",
        )
        bead.position.set((column * 0.35 - 0.9, row * 0.35, 0.2))
~~~

Use explicit IDs for hero objects and components that need stable references. Auto IDs are intended for repeated details, particles, tiles, and other incidental geometry.

## 7. Objects and scene graph

### Create mesh objects and surfaces

~~~python
hero = scene.mesh(
    id="vehicle.body",
    geometry=geo.rounded_box(size=(3, 1.4, 0.8), bevel=0.12),
    material=mat.pbr(color="#D9E1EE", metallic=0.65, roughness=0.22),
    role="hero",
)

ground = scene.surface(
    id="stage.floor",
    size=(30, 30),
    material=mat.pbr(color="#111827", roughness=0.8),
)
~~~

- scene.mesh(id=None, geometry=..., material=None, role=None); geometry is required
- scene.surface(id=None, size=(10, 10), material=None, role="environment")
- scene.group(id=None, children=(), role=None)
- scene.add(object) reparents an object handle to the scene root.
- scene.update(target, ...) changes selected transform, visibility, material, or role properties.
- scene.set_material(target, material) replaces a mesh material.
- scene.remove(object_or_id) removes an object.
- Explicit object IDs must be unique and should be descriptive, such as robot.head, car.wheel.front_left, or camera.closeup.
- IDs are optional for incidental objects. When omitted, blentopy assigns deterministic per-type IDs such as mesh.0001, surface.0001, group.0001, camera.0001, and light.0001. These IDs are stable within one script execution, but may shift if earlier generated objects are inserted or removed. Use explicit IDs for important objects that need later references, animation, or targeted updates.
- Use role="hero" for the primary subject, role="environment" for environment elements, and meaningful roles for other important objects.

### Groups and parenting

~~~python
robot = scene.group(id="robot", role="hero")
body = scene.mesh(
    id="robot.body",
    geometry=geo.rounded_box(size=(1, 1.6, 0.7), bevel=0.08),
    material=mat.pbr(color="#2878FF"),
)
head = scene.mesh(
    id="robot.head",
    geometry=geo.sphere(radius=0.38),
    material=mat.pbr(color="#E8EDF5"),
)

scene.attach(body, to=robot)
robot.add(head)
~~~

scene.group() creates a transformable parent. scene.attach(child, to=parent) preserves the child's world transform while parenting it. group.add(child) is an equivalent convenience method.

Avoid reusing an object under multiple parents. Each object has at most one parent.

## 8. Transform handles

Every object handle exposes:
- id, kind, role
- position, rotation, scale
- visible
- move_to(position)
- rotate_by(rotation)
- add(child) for groups

Vector properties support set() and component access:

~~~python
hero.position.set((0, 0, 2))
hero.rotation.set((0, 0, math.radians(30)))
hero.scale.set((1.2, 1.2, 1.2))

hero.position.x = 1.5
hero.rotation.z = math.radians(15)
hero.visible = True
~~~

position and scale use world units and scale factors. Rotation uses radians. Prefer .set((x, y, z)) when setting all three components.

### Targeted updates

~~~python
scene.update(
    hero,
    position=(1, 0, 2),
    scale=(1.2, 1.2, 1.2),
    visible=True,
    material=mat.pbr(color="#FF5533", roughness=0.3),
    role="hero",
)
scene.set_material(hero, mat.emissive(color="#33BBFF", strength=1.5))
scene.update("robot.head", rotation=(0, 0, math.radians(20)))
~~~

The target can be an Object3D handle or its exact ID string. Omitted or None properties remain unchanged. These updates operate on the current in-memory scene. Each separate render or preview invocation currently starts a fresh scene; loading a previous .blend and carrying scene diffs across separate AI turns is not implemented yet.

## 9. Relationship-based spatial operations

Use semantic placement before manual coordinate arithmetic.

~~~python
scene.place(mug, on=table, anchor="top", offset=(0, 0, 0.02))
scene.look_at(camera, target=hero)
scene.frame(camera, targets=[hero, table], margin=1.25)
scene.align([wheel_a, wheel_b, wheel_c], axis="x", spacing=1.2)
~~~

- scene.place(object, on=None, anchor="center", offset=(0, 0, 0))
- scene.attach(child, to=parent)
- scene.look_at(camera, target) where target is an Object3D handle or a three-value position.
- scene.frame(camera, targets, margin=1.2) adjusts the camera to include the target bounds.
- scene.align(objects, axis="x", spacing=1, start=None) aligns objects in their supplied order along x, y, or z.

Supported anchor values: center, top, bottom, left, right, front, back.

Spatial helpers use object locations and dimensions. For heavily rotated or unusual parented geometry, inspect the result in Blender and adjust manually where necessary. These helpers are compositional aids, not a full physics or constraint solver.

## 10. Camera and lighting

### Camera

~~~python
camera = scene.camera(
    id="camera.main",
    projection="perspective",
    lens=50,
    position=(0, -10, 4),
    target=(0, 0, 1),
)

orthographic = scene.camera(
    id="camera.diagram",
    projection="orthographic",
    ortho_scale=10,
)
~~~

scene.camera(id=None, projection="perspective", lens=50, position=(0, -10, 4), target=(0, 0, 0), ortho_scale=8)

The created camera becomes the active camera. scene.frame() is usually preferable to guessing camera distance.

### Lights

~~~python
key = scene.light(
    id="light.key",
    type="area",
    target=hero,
    position=(-4, -5, 6),
    color="#FFF0DB",
    energy=1500,
    size=5,
)
~~~

scene.light(id=None, type="area", target=(0, 0, 0), position=(4, -5, 7), color="#FFFFFF", energy=1200, size=4)

Light types: area, point, spot, directional. Directional lights map to Blender Sun lights. Area lights use size; spot lights use a default 45-degree cone. Use a purposeful key/fill/rim arrangement and ensure lights illuminate the actual subject.

## 11. Animation

Use seconds instead of frame numbers. Each track controls one transform channel.

~~~python
motion = scene.motion(hero)

rise = motion.track("position")
rise.key(at=0, value=(0, 0, 1), ease="smooth")
rise.key(at=2, value=(0, 0, 3), ease="smooth")
rise.key(at=4, value=(0, 0, 1), ease="smooth")

spin = motion.track("rotation")
spin.key(at=0, value=(0, 0, 0), ease="linear")
spin.key(at=4, value=(0, 0, math.tau), ease="linear")

scale_track = motion.track("scale")
scale_track.key(at=0, value=(1, 1, 1))
scale_track.key(at=1, value=(1.2, 1.2, 1.2), ease="smooth")
~~~

- scene.motion(object) returns a motion controller.
- motion.track("position" | "rotation" | "scale") creates a transform track.
- The direct chained form scene.motion(object).track("position" | "rotation" | "scale") is also supported.
- Store the returned track in a variable, then call track.key(...). The key() method returns None, so chaining key() to another call is not useful; this is an API return-value detail, not a Python syntax restriction.
- track.key(at, value, ease="smooth") inserts a keyframe.
- ease accepts smooth, linear, or constant.
- Keyframe times must be within the configured duration.
- Rotation values are radians.
- Add multiple keys to create multi-stage motion. Do not use a single uniform spin for every scene.

## 12. Inspection and validation

~~~python
report = scene.validate()
snapshot = scene.inspect()
hero_objects = scene.find(role="hero")
~~~

- scene.find(role=None, id=None) returns facade Object3D handles registered during the current script run. For native objects already in a .blend or created directly with bpy, use bpy.data.objects.get(name), scene.objects, or a collection lookup; do not expect scene.find() to wrap arbitrary Blender objects.
- Pass a role-query result directly to bulk APIs such as scene.frame(camera, targets=hero_objects) or scene.align(hero_objects, axis="x"). Lists, tuples, and dictionaries support safe indexing with integer or string keys, and list/tuple/string slices with integer bounds. Use id=... when you need one specific object.
- scene.inspect() returns a compact snapshot of every object linked to the active Blender scene, including objects created directly through bpy; it reports IDs, names, type, role, transforms, visibility, modifiers, and materials. Native objects use blentopy_id or their Blender object name as ID and blentopy_role for an optional semantic role.
- scene.validate() reports missing cameras, empty scenes, and basic visibility/role warnings.

The worker emits a JSON scene snapshot and validation report for the entire active scene, including native bpy-created objects, to the Blender log. This lets the calling AI inspect object IDs, roles, transforms, visibility, modifiers, materials, resource usage, and camera presence from the returned render/preview log. Treat warnings as reasons to inspect and improve the scene, not as proof of a render defect.

## 13. Standard Python execution

Scene scripts are normal Python programs executed by Blender. The preflight parses syntax; it does not impose a custom grammar, AST node whitelist, API allowlist, or data-flow/type whitelist.

Use ordinary Python features whenever they improve the result:
- Imports and from-imports for Blender, mathutils, the Python standard library, and installed modules available to Blender.
- Function and class definitions, lambdas, decorators, comprehensions, generators, and helper modules.
- for and while loops, break, continue, try/except/finally, with, raise, and assert.
- Normal built-ins such as len, range, enumerate, zip, sum, min, max, sorted, set, dict, getattr, and hasattr.
- Normal attribute access, subscripting, object construction, and method chaining.
- Any supported Blender Python API call through bpy, including APIs not wrapped by the studio facade.

There are no custom per-loop or AST-expansion limits. The whole Blender operation remains subject to the runner's operation timeout. Avoid accidental infinite loops and unnecessarily expensive geometry/simulation settings; use Blender's diagnostics and the returned log to identify actual failures.

The studio facade remains useful for common scene graph, geometry, materials, transforms, and animation operations. It is optional: use bpy directly when a feature is missing from the facade or when Blender's native API is a better fit. Do not invent undocumented facade methods when the corresponding Blender API already exists.

The worker process is not a security sandbox. Python code has the same practical capabilities as code run from Blender's scripting workspace. Do not execute untrusted scripts, and do not use generated scripts to delete or overwrite unrelated user files.

## 14. Modeling and cinematic quality standards

Before writing code, plan:
1. Main subject and visual hierarchy.
2. Style, palette, and material language.
3. Environment and spatial context.
4. Composition, camera angle, and framing.
5. Key/fill/rim lighting or a purposeful outdoor lighting setup.
6. Motion with an opening, development, and payoff.
7. A readable ending.

Modeling:
- Combine multiple forms to create recognizable silhouettes.
- Use bevels on hard-surface edges and smooth shading on organic shapes.
- Add secondary details that reinforce function and identity.
- Use custom geometry when primitives are insufficient.
- Keep object IDs stable and descriptive.
- Use groups for assemblies and reusable substructures.

Cinematography:
- Use foreground, subject, and background layers when appropriate.
- Keep the hero subject inside frame throughout the animation.
- Use camera movement for reveal, approach, orbit, tracking, or parallax only when it improves readability.
- Use depth of field selectively.
- Avoid clipping, accidental intersections, and irrelevant decorative clutter.

Do not produce a scene consisting only of one rotating primitive unless the user explicitly requests it. Prioritize deliberate modeling, composition, materials, lighting, and motion over object count.


## 15. Python math and Blender mathutils

Use Python's complete math module. Import additional numerical tools when they are installed in Blender's Python environment. mathutils is provided directly and can also be imported; use mathutils.Vector, Euler, Quaternion, and Matrix for Blender-compatible spatial calculations. Trigonometric functions use radians. New API rotation values and animation rotation keys use radians. The legacy studio.animate_rotation() API continues to accept degrees.

## 16. Iterative editing of existing Blender projects

A scene does not need to be rebuilt after every user instruction. For follow-up requests involving a saved project:

1. Call `blentopy_inspect_scene(blend_path)` using the .blend path returned by the previous render or preview. Read the stable object IDs, transforms, dimensions, hierarchy, modifiers, materials, and active camera.
2. Write a small edit script that changes only the requested parts. Use `scene.find(id="...")` to get an existing object handle, then call `scene.update()`, `scene.set_material()`, `scene.set_dimensions()`, `scene.duplicate()`, `scene.remove()`, or the modeling operations below.
3. Call `blentopy_edit_scene(blend_path, python_code=...)`. This opens the existing .blend, applies the script, inspects the updated scene, and atomically saves the changed project at the same path.
4. Do not reconstruct the whole scene unless the user explicitly requests a rebuild. Preserve existing IDs and unrelated objects.

Objects created by blentopy retain their `blentopy_id` and `blentopy_role` custom properties. For ordinary Blender files without these properties, inspection assigns IDs such as `existing.Cube`; use the exact ID from the latest inspection. Each edit call creates new handles, so resolve objects again with `scene.find()` on every call.

The background edit process updates the saved .blend on disk. A Blender GUI that already has the same project open does not automatically refresh; reload or reopen the file before judging the change. Never claim the visible GUI is updated unless verified.

## 17. Expanded modeling API

Use these operations when primitives alone cannot produce a recognizable shape. They create normal editable Blender objects and non-destructive modifiers.

### Curves and text

- `scene.curve(id=None, points=(), material=None, bevel_depth=0.025, cyclic=False, spline="poly", resolution=12, role=None)`: create a 3D polyline or auto-handle Bezier curve. Supply 2–4096 XYZ points. Use for cables, pipes, trim, wires, outlines, and organic paths. `spline` is `"poly"` or `"bezier"`.
- `scene.text(id=None, body="Text", size=1, extrude=0, align="center", material=None, position=(0,0,0), rotation=(0,0,0), role=None, font_path=None, bevel_depth=0, align_y="top_baseline", character_spacing=1, word_spacing=1, line_spacing=1)`: create editable Blender text. Rotation uses radians. Horizontal alignment accepts `left`, `center`, `right`, `justify`, or `flush`; vertical alignment accepts `top`, `top_baseline`, `center`, `bottom_baseline`, or `bottom`. Optional font files must be TTF/OTF files inside the blentopy workspace (maximum 32 MiB).
- `scene.update_text(target, body=None, font_path=None, size=None, extrude=None, bevel_depth=None, align=None, align_y=None, character_spacing=None, word_spacing=None, line_spacing=None)`: update the content and typography of an existing text object. Omitted or `None` values remain unchanged; use `body=""` to clear the text. Returns the same `Object3D` handle.

### Object editing and geometry operations

- `scene.duplicate(target, id=None, offset=(1,0,0), role=None)`: duplicate an existing object and its object data with a world-space offset.
- `scene.set_dimensions(target, dimensions)`: set world-space dimensions in Blender units.
- `scene.bevel(target, width=0.05, segments=3)`: add a Bevel modifier.
- `scene.subdivide(target, levels=2, render_levels=None)`: add a Catmull–Clark Subdivision modifier.
- `scene.solidify(target, thickness=0.05, offset=-1)`: add thickness to a mesh surface.
- `scene.mirror(target, axis="x", merge=True, bisect=False)`: add a Mirror modifier on one axis.
- `scene.array(target, count=2, offset=(1,0,0))`: add an Array modifier with a constant local offset.
- `scene.boolean(target, operand, operation="DIFFERENCE")`: add a non-destructive Boolean modifier. Operations: `DIFFERENCE`, `UNION`, `INTERSECT`.
- `scene.shade_smooth(target)`: enable smooth shading for mesh polygons.

Example: create and restyle text without replacing the object handle:

~~~python
scene = studio.scene
mat = studio.mat

title = scene.text(
    id="title.main",
    body="BLENTOPY",
    size=1.8,
    extrude=0.06,
    bevel_depth=0.015,
    align="center",
    material=mat.emissive(color="#38BFFF", strength=1.8),
    role="hero",
)
scene.update_text(
    title,
    body="BLENTOPY STUDIO",
    size=1.5,
    character_spacing=1.12,
    line_spacing=1.1,
)
title.position.set((0, 0, 1.5))
rise = scene.motion(title).track("position")
rise.key(at=0, value=(0, 0, 0.5))
rise.key(at=1.5, value=(0, 0, 1.5), ease="smooth")
~~~

Text objects remain ordinary `Object3D` handles. Use `scene.update()` for transforms and visibility, `scene.set_material()` for materials, `scene.motion()` for object animation, and `scene.update_text()` only for text content and typography.


Modifiers remain editable in Blender. Prefer small, deliberate modifier stacks. For Boolean cuts, keep the cutter object identifiable; hide it only after checking that the result is correct.

### Example: edit an existing product model

```python
scene = studio.scene
body = scene.find(id="product.body")
scene.update(body, position=(0, 0, 1.2), scale=(1.1, 1.0, 1.0))
scene.bevel(body, width=0.035, segments=4)

cable = scene.curve(
    id="product.power_cable",
    points=((0.4, 0, 1.0), (0.8, 0, 0.7), (1.0, 0.2, 0.2)),
    bevel_depth=0.025,
    spline="bezier",
    material=studio.mat.pbr(color="#20242D", roughness=0.6),
)
```

All normal Python and Blender APIs remain available in edit scripts as well. Use the facade for concise, repeatable operations and native bpy for anything the facade does not expose.


## 18. Resource budgets

The convenience studio.scene facade applies scene budgets of 1,000 objects, 300,000 estimated post-modifier polygons, and 1,500 modifiers before its own object/modifier creation calls. These checks are not a limit on Blender itself: direct bpy operations can create larger scenes and bypass facade estimates. Use native operations responsibly, monitor memory/render time, and prefer staged renders for expensive simulations or dense geometry.


## 19. Coordinate and animation conventions

Blentopy uses Blender's right-handed, Z-up world coordinate system: X is left/right, Y is depth, and Z is up. The Object3D position, rotation, and scale properties are local transforms relative to the object's parent. Rotation values in the AI-native API and scene.motion(...).track("rotation").key(...) are radians. The legacy studio.animate_rotation() method deliberately retains degrees for backward compatibility.

scene.place(), scene.align(), scene.frame(), scene.look_at(), and scene.duplicate(offset=...) operate in world space. Their calculations use transformed object bounds, including parent transforms and evaluated modifiers. Motion-track keys remain local-space transforms.

Motion key times are seconds from the start of the scene. The scene timeline is frame-based and starts at Blender's frame_start; the final render frame is included, so a key requested at the exact duration is clamped to the final available frame. Use ease="smooth", "linear", or "constant" explicitly when interpolation matters.


## 20. Diagnostic and AI-repair protocol

Workers emit a machine-readable BLENTOPY_ERROR record with an error code, exception type, message, and (when available) line number, column, source line, and suggested correction. Normal Python/Blender tracebacks remain available for deeper diagnosis. Error codes distinguish Python syntax errors, invalid facade arguments, scene-validation failures, resource-limit failures, lock conflicts, cancellation, and Blender execution failures.

When an operation fails, read the complete diagnostic and traceback, identify the actual failing API/property/context, and repair the smallest relevant part of the script. Use Blender's RNA metadata and introspection when API properties differ between Blender versions. Retry with changed code when the correction is meaningful and the operation budget allows it; do not use a fixed retry count as a language restriction. Never repeat unchanged input, and do not retry a lock conflict, cancellation, unsupported Blender version, or resource exhaustion without addressing its cause. Preserve stable IDs and unrelated objects. Report success only after the tool confirms the expected saved artifact. Blentopy does not embed an LLM or silently rewrite user scripts; repair decisions remain with the connected AI client.

## 21. Camera, lighting, and render validation

Scene validation checks active camera presence/type/visibility, perspective lens or orthographic scale, near/far clipping, visible renderable geometry, output resolution, resolution percentage, frame rate, frame range, finite object world transforms, and light energy/color. It warns when no visible light is present and attempts to detect a hero object outside the active camera frame. Framing detection is diagnostic, not a guarantee of visual quality; inspect the rendered result for occlusion, exposure, composition, shadows, and material appearance.


## 22. Texture-backed and procedural node materials

The material API exposes two bounded node presets: studio.mat.image_texture(filepath, roughness, metallic, coat) and studio.mat.noise(color_a, color_b, scale, detail, roughness, metallic, bump_strength). Image paths are resolved relative to BLENTOPY_WORKSPACE (or the scene-script workspace), must remain inside that workspace, must use a supported image format, and are limited to 32 MiB and 8192 pixels per dimension. Imported images are packed into the .blend file. Textures use Blender Generated coordinates; use UV unwrapping in Blender for precise production texture placement. Procedural noise builds a Noise Texture -> Color Ramp graph with an optional Bump node. Arbitrary user-authored node graphs are not exposed to the constrained script language.


## 23. Rigging and Blender-native physics

The facade includes a lightweight armature and rigid-body convenience API:

- scene.armature(id, bones, role="rig") creates a hierarchy of 1–64 named bones. Each bone dictionary requires name, head, and tail vectors, and may include a parent name. Parent references must exist and the hierarchy must be acyclic.
- scene.bind_armature(mesh, rig, bone, weight=1.0) assigns all vertices of a mesh to one bone group. This is useful for rigid props and simple deformation, not automatic production character skinning.
- scene.rigid_body(target, body_type="ACTIVE", mass=1.0, collision_shape="CONVEX_HULL", friction=0.5, restitution=0.0) configures Blender rigid-body physics for mesh objects and creates a cache range matching the scene timeline. Default solver settings are 8 substeps per frame and 10 iterations.

This is Blender's physics system, not a blentopy physics simulator. Use bpy for full control over rigid bodies and for systems that are not wrapped by the facade.

Available Blender systems include:
- Rigid Body / Rigid Body World: active and passive bodies, mass, collision shapes, friction, restitution, constraints, gravity, solver settings, and point caches.
- Soft Body and Cloth modifiers: stiffness, bending, damping, mass, pinning groups, collision and self-collision settings.
- Fluid (Mantaflow): liquid and gas domains, flow and effector objects, resolution, viscosity, vorticity, cache formats and cache directories.
- Particle systems: emitters, counts, lifetime, velocity, distribution, instances, and hair where supported by the Blender version.
- Force fields: wind, turbulence, vortex, magnetic, harmonic, drag, and other supported field types.
- Simulation Nodes / Geometry Nodes, collision modifiers, animation, drivers, and cache baking.

A facade rigid-body example:

~~~python
scene = studio.scene
ground = scene.surface(id="physics.ground", size=(20, 20))
scene.rigid_body(ground, body_type="PASSIVE", friction=0.85)

ball = scene.mesh(
    id="physics.ball",
    geometry=studio.geo.sphere(radius=0.5, segments=48, rings=24),
    material=studio.mat.pbr(color="#2878FF", roughness=0.28),
)
ball.position.set((0, 0, 4))
scene.rigid_body(
    ball,
    body_type="ACTIVE",
    mass=1.0,
    collision_shape="SPHERE",
    friction=0.45,
    restitution=0.2,
)

world = bpy.context.scene.rigidbody_world
world.substeps_per_frame = 12
world.solver_iterations = 20
world.point_cache.frame_start = bpy.context.scene.frame_start
world.point_cache.frame_end = bpy.context.scene.frame_end
~~~

A native Blender example (useful when exact control or unsupported facade features are needed):

~~~python
import bpy

scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end = 180
scene.use_gravity = True
scene.gravity = (0.0, 0.0, -9.81)

bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
floor = bpy.context.object
floor.name = "Ground"
bpy.ops.rigidbody.object_add()
floor.rigid_body.type = "PASSIVE"
floor.rigid_body.friction = 0.85

bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 4))
cube = bpy.context.object
cube.name = "FallingCube"
bpy.ops.rigidbody.object_add()
cube.rigid_body.type = "ACTIVE"
cube.rigid_body.mass = 1.0
cube.rigid_body.friction = 0.45
cube.rigid_body.restitution = 0.2

world = scene.rigidbody_world
world.substeps_per_frame = 12
world.solver_iterations = 20
world.point_cache.frame_start = scene.frame_start
world.point_cache.frame_end = scene.frame_end
~~~

For cloth, add a CLOTH modifier to the mesh and configure its settings; for soft body, add a SOFT_BODY modifier; for fluid, create domain/flow/effector objects with FLUID modifiers and set their domain/flow settings and cache directory; for force fields use bpy.ops.object.effector_add() and configure the returned object's field; for particle systems use Blender's particle-system operators and settings. Build the required domain/flow/effector relationships and cache paths deliberately. Simulation APIs and operator context requirements vary by Blender version, so inspect the actual object's bl_rna.properties, check operator poll(), and read the traceback rather than assuming a property exists.

A simulation setup is not proof that its cache is baked or that the final motion is correct. Set the simulation frame range to match the scene, bake caches when deterministic playback or random-access rendering requires it, and inspect representative frames before delivery. Do not claim the simulation was baked unless Blender reports a successful bake.

## 24. Expanded geometry, materials, environments, and rendering

The AI-native API also includes the following convenience features. Its facade validates its own arguments; ordinary Python scripts can use additional Blender features directly.

### Additional geometry

- geo.ico_sphere(radius=0.5, subdivisions=2): create a low-poly geodesic sphere.
- geo.circle(radius=1, vertices=64, fill=True): create a flat circle; fill=False creates an outline.
- geo.ring(inner_radius=0.8, outer_radius=1, segments=64): create a flat annulus.
- geo.capsule(radius=0.5, height=2, radial_segments=32, cap_segments=8): create a rounded capsule with height >= 2 * radius.
- geo.torus_knot(radius=1, tube=0.2, tubular_segments=128, radial_segments=12, p=2, q=3): create a parametric torus knot. Segment counts and p/q are bounded.

Example:

~~~python
ico = scene.mesh(geo.ico_sphere(radius=0.8, subdivisions=3), material=mat.pbr(color="#55AADD"))
capsule = scene.mesh(geo.capsule(radius=0.35, height=2.2), material=mat.pbr(color="#D5A35E"))
ring = scene.mesh(geo.ring(inner_radius=0.65, outer_radius=0.8), material=mat.physical(metallic=0.7, transmission=0))
knot = scene.mesh(geo.torus_knot(radius=1, tube=0.12, p=2, q=3), material=mat.pbr(color="#A06BFF"))
~~~

### Extended materials

- mat.physical(color="#FFFFFF", roughness=0.08, metallic=0, transmission=1, ior=1.45, thickness=0.2, alpha=1, coat=0, subsurface=0, sheen=0, anisotropy=0): configure additional Principled BSDF inputs where supported by the installed Blender version.
- mat.glass(color="#FFFFFF", roughness=0.04, ior=1.45, thickness=0.2): glass preset using transmission.
- mat.toon(color="#FFFFFF", size=0.5, smooth=0.1): connect a Toon BSDF shader.

Blender versions expose different Principled BSDF sockets. Unsupported optional sockets are skipped; the values are still validated. Glass quality depends on the render engine, lighting, and transparent-object settings.

### Environment maps and camera depth of field

- scene.environment(filepath, strength=1, rotation=0): load an HDR or EXR file into the world shader. The file must be inside the blentopy workspace, at most 128 MiB, and no larger than 16384 pixels on either dimension. The image is packed into the .blend file.
- scene.camera_dof(camera, focus=None, focus_distance=10, f_stop=2.8, enabled=True): enable depth of field on a camera, focusing on an object ID/handle or a fixed distance.
- scene.set_visibility(target, viewport=None, render=None): independently control viewport and render visibility.

### Render configuration and compositing

- scene.configure_render(engine="eevee", samples=64, resolution_percent=100, transparent=False, motion_blur=False, color_transform="AgX"): set Eevee or Cycles quality, output percentage, transparency, motion blur, and view transform.
- scene.post_process(bloom=0, lens_distortion=0, exposure=0, contrast=1, saturation=1): build a labelled compositor chain. Repeated calls replace only blentopy-managed post-process nodes, preserving unrelated compositor nodes.

Effect ranges: bloom 0–1, lens distortion -0.5–0.5, exposure -10–10 stops, contrast 0–2, saturation 0–2. Results vary by Blender version and render engine.

### Model import and export

- scene.import_model(filepath, format="auto", id_prefix="imported", role="imported"): import GLB, glTF, OBJ, FBX, STL, PLY, USD, or USDZ data from a file inside the blentopy workspace. Returns registered Object3D handles. The importer must be available in the installed Blender build.
- scene.export_model(filepath, format="auto", selected_only=False): export GLB, glTF, OBJ, FBX, STL, PLY, or USD inside the workspace. selected_only=True exports the current Blender selection.

The facade's scene.import_model() and scene.export_model() helpers confine their paths to the workspace. Direct Blender Python file APIs follow Blender/Python's normal filesystem semantics; use workspace-relative paths and avoid touching unrelated user files.

Example:

~~~python
asset_objects = scene.import_model("assets/robot.glb")
scene.configure_render(engine="cycles", samples=96)
scene.camera_dof(camera, focus=hero, f_stop=3.2)
scene.post_process(bloom=0.25, exposure=0.2, saturation=0.95)
scene.export_model("exports/robot.glb", selected_only=False)
~~~



### Efficient repeated objects

- scene.instance(target, id=None, offset=(1,0,0), role=None): create a linked-data object instance. Geometry and material datablocks are shared with the source, reducing duplicate mesh memory. Transform the returned handle independently. Editing shared mesh data affects every linked instance; use scene.duplicate() when independent mesh data is required.

Example:

~~~python
source = scene.mesh(geometry=geo.rounded_box(size=(0.5, 0.5, 1)), material=mat.pbr(color="#5577AA"))
for index in range(8):
    column = scene.instance(source, offset=(index * 1.2, 0, 0))
~~~

