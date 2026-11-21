"""Small Tkinter front end that delegates every operation to the blentopy CLI.

The GUI intentionally contains no Blender execution logic. It edits a Python scene
script and launches the same CLI commands a terminal user would run.
"""

from __future__ import annotations

import queue
import shlex
import subprocess
import sys
import threading
from pathlib import Path
from typing import Literal


GuiAction = Literal["preview", "render"]


def build_cli_command(
    action: GuiAction,
    *,
    script: str | Path,
    blender: str | None = None,
    output: str | Path | None = None,
    blend_output: str | Path | None = None,
    workspace: str | Path | None = None,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    duration: int = 8,
    timeout: int = 3600,
    startup_timeout: int = 120,
    python_executable: str | None = None,
) -> list[str]:
    """Build an argv list for the existing CLI without invoking a shell."""
    if action not in {"preview", "render"}:
        raise ValueError(f"Unsupported GUI action: {action}")

    script_path = Path(script).expanduser().resolve()
    if not script_path.is_file():
        raise FileNotFoundError(f"Scene script does not exist: {script_path}")
    if script_path.suffix.lower() != ".py":
        raise ValueError(f"Scene script must be a Python file: {script_path}")

    command = [
        python_executable or sys.executable,
        "-m",
        "blentopy.cli",
        action,
        str(script_path),
    ]

    def add_option(name: str, value: str | Path | int | None) -> None:
        if value is not None and str(value).strip():
            command.extend((name, str(value)))

    add_option("--blender", blender)
    add_option("--blend-output", blend_output)
    add_option("--workspace", workspace)
    add_option("--width", width)
    add_option("--height", height)
    add_option("--fps", fps)
    add_option("--duration", duration)

    if action == "render":
        add_option("--output", output)
        add_option("--timeout", timeout)
    else:
        add_option("--startup-timeout", startup_timeout)

    return command


def build_doctor_command(
    *, blender: str | None = None, python_executable: str | None = None
) -> list[str]:
    """Build the existing doctor command."""
    command = [python_executable or sys.executable, "-m", "blentopy.cli", "doctor"]
    if blender and blender.strip():
        command.extend(("--blender", blender.strip()))
    return command


class BlentopyGUI:
    """Minimal editor and process monitor for chat-generated scene scripts."""

    def __init__(self, root, tk, ttk, filedialog, messagebox) -> None:
        self.root = root
        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self.script_path: Path | None = None
        self.dirty = False
        self._closing = False

        root.title("blentopy — GUI")
        root.geometry("1160x820")
        root.minsize(900, 620)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        self.script_var = tk.StringVar()
        self.blender_var = tk.StringVar()
        self.output_var = tk.StringVar(value="renders/scene.mp4")
        self.blend_var = tk.StringVar(value="renders/scene.blend")
        self.workspace_var = tk.StringVar(value="blentopy-workspace")
        self.width_var = tk.StringVar(value="1080")
        self.height_var = tk.StringVar(value="1920")
        self.fps_var = tk.StringVar(value="30")
        self.duration_var = tk.StringVar(value="8")
        self.timeout_var = tk.StringVar(value="3600")
        self.status_var = tk.StringVar(value="Ready — open or paste a Python scene script.")

        self._build_widgets()
        self.root.bind("<Control-s>", lambda _event: self.save_script())
        self.root.bind("<Command-s>", lambda _event: self.save_script())
        self.root.bind("<Control-o>", lambda _event: self.open_script())
        self.root.bind("<Command-o>", lambda _event: self.open_script())
        self.root.after(80, self._drain_events)

    def _build_widgets(self) -> None:
        outer = self.ttk.Frame(self.root, padding=12)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)
        outer.rowconfigure(4, weight=1)

        header = self.ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)
        self.ttk.Label(
            header, text="blentopy", font=("TkDefaultFont", 18, "bold")
        ).grid(row=0, column=0, sticky="w")
        self.ttk.Label(
            header,
            text="A lightweight interface for AI-generated Blender scene scripts",
        ).grid(row=1, column=0, sticky="w")
        self.ttk.Button(
            header, text="Copy AI instructions", command=self.copy_ai_instructions
        ).grid(row=0, column=1, rowspan=2, padx=(8, 0))

        files = self.ttk.LabelFrame(outer, text="Scene script", padding=8)
        files.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        files.columnconfigure(1, weight=1)
        self.ttk.Label(files, text="Python file").grid(row=0, column=0, sticky="w")
        self.ttk.Entry(files, textvariable=self.script_var).grid(
            row=0, column=1, sticky="ew", padx=6
        )
        self.ttk.Button(files, text="Open…", command=self.open_script).grid(
            row=0, column=2, padx=(0, 4)
        )
        self.ttk.Button(files, text="New", command=self.new_script).grid(
            row=0, column=3, padx=(0, 4)
        )
        self.ttk.Button(files, text="Save", command=self.save_script).grid(
            row=0, column=4
        )

        settings = self.ttk.LabelFrame(outer, text="CLI options", padding=8)
        settings.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        for column in (1, 3, 5):
            settings.columnconfigure(column, weight=1)

        self._setting_row(
            settings, 0, 0, "Blender executable", self.blender_var,
            browse=self._browse_blender,
        )
        self._setting_row(
            settings, 1, 0, "Workspace", self.workspace_var,
            browse=self._browse_workspace,
        )
        self._setting_row(
            settings, 2, 0, "MP4 output", self.output_var,
            browse=self._browse_output,
        )
        self._setting_row(
            settings, 3, 0, ".blend output", self.blend_var,
            browse=self._browse_blend,
        )

        number_fields = (
            ("Width", self.width_var),
            ("Height", self.height_var),
            ("FPS", self.fps_var),
            ("Duration (s)", self.duration_var),
            ("Timeout (s)", self.timeout_var),
        )
        for index, (label, variable) in enumerate(number_fields):
            column = index * 2
            self.ttk.Label(settings, text=label).grid(
                row=4, column=column, sticky="w", pady=(7, 0)
            )
            self.ttk.Entry(settings, textvariable=variable, width=9).grid(
                row=4, column=column + 1, sticky="ew", padx=(5, 10), pady=(7, 0)
            )

        actions = self.ttk.Frame(outer)
        actions.grid(row=3, column=0, sticky="nsew")
        actions.columnconfigure(0, weight=1)
        actions.rowconfigure(1, weight=1)

        self.ttk.Label(actions, text="Scene code — paste or edit the code returned by your AI chat").grid(
            row=0, column=0, sticky="w", pady=(0, 5)
        )
        editor_frame = self.ttk.Frame(actions)
        editor_frame.grid(row=1, column=0, sticky="nsew")
        editor_frame.rowconfigure(0, weight=1)
        editor_frame.columnconfigure(0, weight=1)
        self.editor = self.tk.Text(
            editor_frame,
            wrap="none",
            undo=True,
            font=("TkFixedFont", 10),
            padx=8,
            pady=8,
        )
        self.editor.grid(row=0, column=0, sticky="nsew")
        editor_scroll_y = self.ttk.Scrollbar(
            editor_frame, orient="vertical", command=self.editor.yview
        )
        editor_scroll_y.grid(row=0, column=1, sticky="ns")
        editor_scroll_x = self.ttk.Scrollbar(
            editor_frame, orient="horizontal", command=self.editor.xview
        )
        editor_scroll_x.grid(row=1, column=0, sticky="ew")
        self.editor.configure(
            yscrollcommand=editor_scroll_y.set,
            xscrollcommand=editor_scroll_x.set,
        )
        self.editor.bind("<<Modified>>", self._on_editor_modified)

        console = self.ttk.LabelFrame(outer, text="CLI output", padding=6)
        console.grid(row=4, column=0, sticky="nsew", pady=(8, 0))
        console.columnconfigure(0, weight=1)
        console.rowconfigure(0, weight=1)
        self.console = self.tk.Text(
            console, height=9, wrap="word", font=("TkFixedFont", 9), padx=6, pady=5
        )
        self.console.grid(row=0, column=0, sticky="nsew")
        console_scroll = self.ttk.Scrollbar(
            console, orient="vertical", command=self.console.yview
        )
        console_scroll.grid(row=0, column=1, sticky="ns")
        self.console.configure(yscrollcommand=console_scroll.set)

        footer = self.ttk.Frame(outer)
        footer.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        self.status_label = self.ttk.Label(footer, textvariable=self.status_var)
        self.status_label.grid(row=0, column=0, sticky="w")
        self.doctor_button = self.ttk.Button(
            footer, text="Check Blender", command=self.run_doctor
        )
        self.doctor_button.grid(row=0, column=1, padx=(4, 0))
        self.preview_button = self.ttk.Button(
            footer, text="Preview in Blender", command=self.run_preview
        )
        self.preview_button.grid(row=0, column=2, padx=(4, 0))
        self.render_button = self.ttk.Button(
            footer, text="Render MP4", command=self.run_render
        )
        self.render_button.grid(row=0, column=3, padx=(4, 0))

    def _setting_row(self, parent, row, column, label, variable, browse=None) -> None:
        self.ttk.Label(parent, text=label).grid(
            row=row, column=column, sticky="w", pady=2
        )
        self.ttk.Entry(parent, textvariable=variable).grid(
            row=row, column=column + 1, sticky="ew", padx=6, pady=2
        )
        if browse is not None:
            self.ttk.Button(parent, text="Browse…", command=browse).grid(
                row=row, column=column + 2, sticky="w", pady=2
            )

    def _on_editor_modified(self, _event=None) -> None:
        if self.editor.edit_modified():
            self.dirty = True
            self.editor.edit_modified(False)
            self._update_title()

    def _update_title(self) -> None:
        name = self.script_path.name if self.script_path else "Untitled"
        marker = " *" if self.dirty else ""
        self.root.title(f"blentopy — {name}{marker}")

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = self.messagebox.askyesnocancel(
            "Unsaved changes",
            "Save changes to the current Python script before continuing?",
            parent=self.root,
        )
        if answer is None:
            return False
        if answer:
            return self.save_script()
        return True

    def new_script(self) -> None:
        if not self._confirm_discard():
            return
        self.script_path = None
        self.script_var.set("")
        self.editor.delete("1.0", "end")
        self.editor.edit_modified(False)
        self.dirty = False
        self.output_var.set("renders/scene.mp4")
        self.blend_var.set("renders/scene.blend")
        self._update_title()
        self.status_var.set("New unsaved scene script.")

    def open_script(self) -> None:
        if not self._confirm_discard():
            return
        selected = self.filedialog.askopenfilename(
            parent=self.root,
            title="Open a blentopy Python scene script",
            filetypes=(("Python files", "*.py"), ("All files", "*")),
        )
        if not selected:
            return
        path = Path(selected).expanduser().resolve()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            self.messagebox.showerror("Cannot open script", str(exc), parent=self.root)
            return
        self.script_path = path
        self.script_var.set(str(path))
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", source)
        self.editor.edit_modified(False)
        self.dirty = False
        self.output_var.set(str(Path("renders") / f"{path.stem}.mp4"))
        self.blend_var.set(str(Path("renders") / f"{path.stem}.blend"))
        self._update_title()
        self.status_var.set(f"Loaded {path}")

    def save_script(self) -> bool:
        candidate = self.script_path
        if candidate is None:
            selected = self.filedialog.asksaveasfilename(
                parent=self.root,
                title="Save Python scene script",
                defaultextension=".py",
                initialfile="scene.py",
                filetypes=(("Python files", "*.py"), ("All files", "*")),
            )
            if not selected:
                return False
            candidate = Path(selected).expanduser()
        if candidate.suffix.lower() != ".py":
            self.messagebox.showerror(
                "Invalid file type",
                "Scene scripts must use the .py extension.",
                parent=self.root,
            )
            return False
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_text(self.editor.get("1.0", "end-1c"), encoding="utf-8")
        except OSError as exc:
            self.messagebox.showerror("Cannot save script", str(exc), parent=self.root)
            return False
        self.script_path = candidate.resolve()
        self.script_var.set(str(self.script_path))
        self.dirty = False
        self.editor.edit_modified(False)
        self._update_title()
        self.status_var.set(f"Saved {self.script_path}")
        return True

    def _browse_blender(self) -> None:
        selected = self.filedialog.askopenfilename(
            parent=self.root, title="Select Blender executable"
        )
        if selected:
            self.blender_var.set(selected)

    def _browse_workspace(self) -> None:
        selected = self.filedialog.askdirectory(parent=self.root, title="Select workspace")
        if selected:
            self.workspace_var.set(selected)

    def _browse_output(self) -> None:
        selected = self.filedialog.asksaveasfilename(
            parent=self.root, title="MP4 output", defaultextension=".mp4",
            filetypes=(("MP4 video", "*.mp4"), ("All files", "*")),
        )
        if selected:
            self.output_var.set(selected)

    def _browse_blend(self) -> None:
        selected = self.filedialog.asksaveasfilename(
            parent=self.root, title="Blender project output", defaultextension=".blend",
            filetypes=(("Blender project", "*.blend"), ("All files", "*")),
        )
        if selected:
            self.blend_var.set(selected)

    def copy_ai_instructions(self) -> None:
        prompt_path = Path(__file__).with_name("AI_SYSTEM_PROMPT.md")
        try:
            prompt = prompt_path.read_text(encoding="utf-8")
        except OSError as exc:
            self.messagebox.showerror(
                "Cannot read AI instructions", str(exc), parent=self.root
            )
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(prompt)
        self.status_var.set(
            "AI authoring instructions copied. Paste them into your chat before requesting a scene."
        )

    def _integer(self, variable, label: str) -> int:
        try:
            value = int(variable.get())
        except ValueError as exc:
            raise ValueError(f"{label} must be a whole number.") from exc
        if value <= 0:
            raise ValueError(f"{label} must be greater than zero.")
        return value

    def _script_for_run(self) -> Path | None:
        raw_path = self.script_var.get().strip()
        if self.script_path is None and raw_path:
            self.script_path = Path(raw_path).expanduser()
        if not self.save_script():
            return None
        if self.script_path is None:
            return None
        return self.script_path

    def run_preview(self) -> None:
        self._run_scene("preview")

    def run_render(self) -> None:
        self._run_scene("render")

    def _run_scene(self, action: GuiAction) -> None:
        if self.process is not None:
            return
        script = self._script_for_run()
        if script is None:
            return
        try:
            options = {
                "script": script,
                "blender": self.blender_var.get().strip() or None,
                "blend_output": self.blend_var.get().strip() or None,
                "workspace": self.workspace_var.get().strip() or None,
                "width": self._integer(self.width_var, "Width"),
                "height": self._integer(self.height_var, "Height"),
                "fps": self._integer(self.fps_var, "FPS"),
                "duration": self._integer(self.duration_var, "Duration"),
                "timeout": self._integer(self.timeout_var, "Timeout"),
            }
            if action == "render":
                options["output"] = self.output_var.get().strip() or (
                    Path("renders") / f"{script.stem}.mp4"
                )
            command = build_cli_command(action, **options)
        except (ValueError, FileNotFoundError) as exc:
            self.messagebox.showerror("Cannot start command", str(exc), parent=self.root)
            return
        self._start_process(command, f"Running CLI {action}…")

    def run_doctor(self) -> None:
        if self.process is not None:
            return
        command = build_doctor_command(
            blender=self.blender_var.get().strip() or None
        )
        self._start_process(command, "Checking the Blender environment…")

    def _start_process(self, command: list[str], status: str) -> None:
        self._append_console("\n$ " + shlex.join(command) + "\n")
        self.status_var.set(status)
        self._set_busy(True)
        try:
            self.process = subprocess.Popen(
                command,
                cwd=Path.cwd(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            self.process = None
            self._set_busy(False)
            self.status_var.set("Could not start the CLI.")
            self._append_console(f"Failed to start process: {exc}\n")
            return

        process = self.process

        def read_output() -> None:
            assert process.stdout is not None
            buffer = ""
            while True:
                character = process.stdout.read(1)
                if not character:
                    break
                buffer += character
                if character in "\r\n" or len(buffer) >= 256:
                    self.events.put(("output", buffer))
                    buffer = ""
            if buffer:
                self.events.put(("output", buffer))
            self.events.put(("exit", process.wait()))

        threading.Thread(target=read_output, name="blentopy-cli-output", daemon=True).start()

    def _drain_events(self) -> None:
        if self._closing:
            return
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "output":
                    self._append_console(str(payload))
                elif event == "exit":
                    code = int(payload)
                    self.process = None
                    self._set_busy(False)
                    if code == 0:
                        self.status_var.set("CLI command completed successfully.")
                    else:
                        self.status_var.set(f"CLI command failed (exit code {code}). See output.")
        except queue.Empty:
            pass
        self.root.after(80, self._drain_events)

    def _append_console(self, value: str) -> None:
        for part_index, part in enumerate(value.split("\r")):
            if part_index:
                self.console.delete("end-1c linestart", "end-1c")
            if part:
                self.console.insert("end-1c", part)
        self.console.see("end")

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.preview_button.configure(state=state)
        self.render_button.configure(state=state)
        self.doctor_button.configure(state=state)

    def close(self) -> None:
        if self.process is not None:
            self.messagebox.showinfo(
                "Command still running",
                "The CLI is still running. Let it finish before closing this window.",
                parent=self.root,
            )
            return
        if not self._confirm_discard():
            return
        self._closing = True
        self.root.destroy()


def main() -> int:
    """Launch the optional desktop interface."""
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError as exc:
        print(
            "The blentopy GUI requires Tkinter, which is not available in this Python installation. "
            "Use the CUI commands instead: blentopy preview or blentopy render.",
            file=sys.stderr,
        )
        print(f"Tkinter import error: {exc}", file=sys.stderr)
        return 2

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(
            "Could not open the blentopy GUI. A desktop session is required. "
            "Use the CUI commands instead: blentopy preview or blentopy render.",
            file=sys.stderr,
        )
        print(f"Window-system error: {exc}", file=sys.stderr)
        return 2

    BlentopyGUI(root, tk, ttk, filedialog, messagebox)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
