import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import json
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback

import cv2
import numpy as np
from PIL import Image, ImageSequence, ImageTk


IMAGE_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".webp"
)

ANIMATED_IMAGE_EXTENSIONS = (
    ".gif",
)


def configure_windows_dpi_awareness():

    if not sys.platform.startswith("win"):
        return

    try:

        import ctypes

        try:

            # Per-monitor DPI aware for accurate geometry on multi-screen setups.
            ctypes.windll.shcore.SetProcessDpiAwareness(2)

        except Exception:

            ctypes.windll.user32.SetProcessDPIAware()

    except Exception:

        pass


class Face:

    def __init__(
        self,
        points=None,
        filename="",
        flip_x=False,
        flip_y=False,
        rotation_degrees=0,
        shape="rectangle",
        depth_point=None
    ):

        self.points = points or [
            [300, 200],
            [600, 200],
            [600, 500],
            [300, 500]
        ]

        self.filename = filename

        self.flip_x = flip_x
        self.flip_y = flip_y
        self.rotation_degrees = rotation_degrees % 360
        self.shape = "circle" if shape == "circle" else "rectangle"
        self.depth_point = depth_point

        self.image = None

        self.gif_frames = []
        self.gif_durations = []
        self.gif_duration_ms = 0
        self.is_animated = False

        self.playback_started_at = None

        self.photo = None

        self.cached_warp_key = None
        self.cached_warped = None
        self.cached_mask = None
        self.cached_roi = None

        self.load_file()

    # ---------------------------------------------------------
    # ARCHIVO
    # ---------------------------------------------------------

    def load_file(self):

        self.close_media()

        self.image = None
        self.gif_frames = []
        self.gif_durations = []
        self.gif_duration_ms = 0
        self.is_animated = False

        self.cached_warp_key = None
        self.cached_warped = None
        self.cached_mask = None
        self.cached_roi = None

        if not self.filename:
            return

        extension = os.path.splitext(
            self.filename
        )[1].lower()

        if extension in ANIMATED_IMAGE_EXTENSIONS:

            self.is_animated = True

            try:

                with Image.open(self.filename) as image:

                    for gif_frame in ImageSequence.Iterator(image):

                        rgba_frame = gif_frame.convert("RGBA")
                        background = Image.new(
                            "RGBA",
                            rgba_frame.size,
                            (0, 0, 0, 255)
                        )
                        background.alpha_composite(rgba_frame)
                        frame = cv2.cvtColor(
                            np.array(background),
                            cv2.COLOR_RGBA2BGR
                        )
                        duration = max(
                            int(gif_frame.info.get("duration", 100)),
                            20
                        )
                        self.gif_frames.append(frame)
                        self.gif_durations.append(duration)

                if self.gif_frames:

                    self.image = self.gif_frames[0]
                    self.gif_duration_ms = sum(self.gif_durations)

            except Exception as e:

                print(
                    "Error cargando GIF:",
                    e
                )

        elif extension in IMAGE_EXTENSIONS:

            try:

                image = cv2.imread(
                    self.filename
                )

                if image is not None:
                    self.image = image

            except Exception as e:

                print(
                    "Error cargando imagen:",
                    e
                )

    # ---------------------------------------------------------
    # GIF ANIMADO
    # ---------------------------------------------------------

    def start_animation(self):

        if self.is_animated:

            self.playback_started_at = time.perf_counter()

    def stop_animation(self):

        self.playback_started_at = None

    def get_current_frame(
        self,
        playback=False
    ):

        if self.is_animated:

            if not playback or not self.gif_frames:
                return self.image

            if self.playback_started_at is None:
                self.playback_started_at = time.perf_counter()

            elapsed_ms = int(
                (time.perf_counter() - self.playback_started_at) * 1000
            ) % self.gif_duration_ms
            current_ms = 0

            for frame, duration in zip(
                self.gif_frames,
                self.gif_durations
            ):

                current_ms += duration

                if elapsed_ms < current_ms:
                    return frame

            return self.gif_frames[-1]

        return self.image

    def close_media(self):

        self.playback_started_at = None
        self.gif_frames = []
        self.gif_durations = []
        self.gif_duration_ms = 0
        self.is_animated = False

        self.cached_warp_key = None
        self.cached_warped = None
        self.cached_mask = None
        self.cached_roi = None


class Scene:

    def __init__(
        self,
        name="Escena 1",
        screen_index=0,
        space_width=None,
        space_height=None,
        orientation="horizontal"
    ):

        self.name = name
        self.screen_index = screen_index
        self.space_width = space_width
        self.space_height = space_height
        self.orientation = orientation
        self.faces = []


class VideoMapper:

    def __init__(self, root):

        self.root = root

        self.root.title(
            "GIF Mapper"
        )

        self.root.geometry(
            "1280x720"
        )

        self.root.configure(
            bg="black"
        )

        self.maximize_main_window()

        self.project_file = None
        self.current_project_dir = None
        self.current_assets_dir = None

        self.project_name = "Proyecto"

        self.scenes = []

        self.current_scene = None

        self.selected_face = None

        self.selected_corner = None

        self.dragging = False
        self.dragging_depth = False

        self.canvas_width = 1280
        self.canvas_height = 720

        self.editor_running = True

        self.available_screens = (
            self.get_available_screens()
        )

        self.player_windows = {}

        self.player_running = False

        self.execution_mode = False

        self.web_lock = threading.RLock()

        self.web_server = None

        self.web_thread = None

        self.web_port = 5000
        self.web_host_ip = "127.0.0.1"

        self.web_control_active = False

        self.projects_root_dir = self.get_projects_root_dir()

        os.makedirs(
            self.projects_root_dir,
            exist_ok=True
        )

        self.build_ui()

        self.show_desktop_project_manager(
            startup=True
        )

        self.start_web_server(
            notify=False
        )

    # =========================================================
    # PANTALLAS
    # =========================================================

    def get_available_screens(self):

        detectors = [
            self.get_screens_from_screeninfo
        ]

        if sys.platform.startswith("win"):

            detectors.append(
                self.get_screens_from_windows
            )

        if sys.platform.startswith("linux"):

            detectors.append(
                self.get_screens_from_xrandr
            )

        for detector in detectors:

            try:

                screens = detector()

                if screens:

                    return self.normalize_screens(
                        screens
                    )

            except Exception as e:

                print(
                    "No se pudieron detectar pantallas:",
                    e
                )

        return self.get_fallback_screen()

    def get_screens_from_screeninfo(self):

        try:

            from screeninfo import get_monitors

        except ImportError:

            return []

        screens = []

        for monitor in get_monitors():

            screens.append({
                "name": getattr(
                    monitor,
                    "name",
                    ""
                ),
                "x": monitor.x,
                "y": monitor.y,
                "width": monitor.width,
                "height": monitor.height
            })

        return screens

    def get_screens_from_windows(self):

        import ctypes
        from ctypes import wintypes

        monitors = []

        monitor_enum_proc = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HMONITOR,
            wintypes.HDC,
            ctypes.POINTER(wintypes.RECT),
            wintypes.LPARAM
        )

        def callback(
            monitor,
            device_context,
            rectangle,
            data
        ):

            rect = rectangle.contents

            monitors.append({
                "x": rect.left,
                "y": rect.top,
                "width": rect.right - rect.left,
                "height": rect.bottom - rect.top
            })

            return 1

        ctypes.windll.user32.EnumDisplayMonitors(
            0,
            0,
            monitor_enum_proc(callback),
            0
        )

        return monitors

    def get_screens_from_xrandr(self):

        result = subprocess.run(
            [
                "xrandr",
                "--query"
            ],
            capture_output=True,
            text=True,
            timeout=2,
            check=False
        )

        if result.returncode != 0:
            return []

        screens = []

        pattern = re.compile(
            r"^(?P<name>\S+) connected"
            r"(?: primary)? "
            r"(?P<width>\d+)x(?P<height>\d+)"
            r"(?P<x>[+-]\d+)(?P<y>[+-]\d+)"
        )

        for line in result.stdout.splitlines():

            match = pattern.search(
                line
            )

            if not match:
                continue

            screens.append({
                "name": match.group(
                    "name"
                ),
                "x": int(
                    match.group("x")
                ),
                "y": int(
                    match.group("y")
                ),
                "width": int(
                    match.group("width")
                ),
                "height": int(
                    match.group("height")
                )
            })

        return screens

    def normalize_screens(
        self,
        screens
    ):

        normalized = []

        for index, screen in enumerate(screens):

            width = int(
                screen.get(
                    "width",
                    0
                )
            )

            height = int(
                screen.get(
                    "height",
                    0
                )
            )

            if width <= 0 or height <= 0:
                continue

            name = screen.get(
                "name",
                ""
            )

            if not name:

                name = (
                    f"Pantalla {index + 1}"
                )

            normalized.append({
                "name": (
                    f"{name} ({width}x{height})"
                ),
                "x": int(
                    screen.get(
                        "x",
                        0
                    )
                ),
                "y": int(
                    screen.get(
                        "y",
                        0
                    )
                ),
                "width": width,
                "height": height
            })

        return normalized

    def get_fallback_screen(self):

        width = self.root.winfo_screenwidth()
        height = self.root.winfo_screenheight()

        return [{
            "name": (
                f"Pantalla 1 ({width}x{height})"
            ),
            "x": 0,
            "y": 0,
            "width": width,
            "height": height
        }]

    def get_screen(
        self,
        screen_index
    ):

        if not self.available_screens:
            self.available_screens = (
                self.get_available_screens()
            )

        if screen_index < 0:
            screen_index = 0

        if screen_index >= len(
            self.available_screens
        ):
            screen_index = 0

        return self.available_screens[
            screen_index
        ]

    def get_scene_orientation(self, scene):

        orientation = getattr(scene, "orientation", "horizontal")

        if orientation not in (
            "horizontal",
            "vertical",
            "horizontal_inverted",
            "vertical_inverted"
        ):

            return "horizontal"

        return orientation

    def get_target_scene_space(
        self,
        scene=None
    ):

        if scene is None:
            scene = self.current_scene

        if scene is not None and self.available_screens:

            screen = self.get_screen(
                scene.screen_index
            )

            width = int(
                screen.get(
                    "width",
                    0
                )
            )

            height = int(
                screen.get(
                    "height",
                    0
                )
            )

            if width > 1 and height > 1:

                if self.get_scene_orientation(scene).startswith("vertical"):

                    width, height = height, width

                return width, height

        width = int(self.canvas_width)
        height = int(self.canvas_height)

        if width <= 1:
            width = 1280

        if height <= 1:
            height = 720

        return width, height

    def rescale_scene_faces(
        self,
        scene,
        source_width,
        source_height,
        target_width,
        target_height
    ):

        if scene is None:
            return False

        if (
            source_width <= 1
            or source_height <= 1
            or target_width <= 1
            or target_height <= 1
        ):
            return False

        sx = target_width / source_width
        sy = target_height / source_height

        if abs(sx - 1.0) < 1e-9 and abs(sy - 1.0) < 1e-9:
            scene.space_width = target_width
            scene.space_height = target_height
            return False

        for face in scene.faces:

            scaled_points = []

            for x, y in face.points:

                scaled_points.append([
                    int(round(x * sx)),
                    int(round(y * sy))
                ])

            face.points = scaled_points

        scene.space_width = target_width
        scene.space_height = target_height

        return True

    def adapt_scene_to_assigned_screen(
        self,
        scene,
        source_width=None,
        source_height=None,
        force=False
    ):

        if scene is None:
            return False

        target_width, target_height = self.get_target_scene_space(
            scene
        )

        if source_width is None or source_height is None:

            source_width = int(
                scene.space_width
                if scene.space_width is not None
                else 0
            )

            source_height = int(
                scene.space_height
                if scene.space_height is not None
                else 0
            )

        source_width = int(source_width)
        source_height = int(source_height)

        if source_width <= 1 or source_height <= 1:

            source_width = int(self.canvas_width)
            source_height = int(self.canvas_height)

        if source_width <= 1 or source_height <= 1:

            source_width, source_height = (
                target_width,
                target_height
            )

        if (
            not force
            and source_width == target_width
            and source_height == target_height
        ):

            scene.space_width = target_width
            scene.space_height = target_height
            return False

        return self.rescale_scene_faces(
            scene,
            source_width,
            source_height,
            target_width,
            target_height
        )

    def build_screen_geometry(
        self,
        screen
    ):

        def offset(value):

            if value >= 0:

                return f"+{value}"

            return str(value)

        return (
            f"{screen['width']}x{screen['height']}"
            f"{offset(screen['x'])}"
            f"{offset(screen['y'])}"
        )

    def refresh_screens(self):

        self.available_screens = (
            self.get_available_screens()
        )

        self.update_screen_combo()

    def get_editor_screen_index(self):

        try:

            self.root.update_idletasks()

            editor_x = self.root.winfo_rootx()
            editor_y = self.root.winfo_rooty()
            editor_width = self.root.winfo_width()
            editor_height = self.root.winfo_height()

            center_x = editor_x + editor_width // 2
            center_y = editor_y + editor_height // 2

            for index, screen in enumerate(
                self.available_screens
            ):

                if (
                    center_x >= screen["x"]
                    and center_x < screen["x"] + screen["width"]
                    and center_y >= screen["y"]
                    and center_y < screen["y"] + screen["height"]
                ):

                    return index

        except Exception:

            pass

        return 0

    def validate_scene_outputs(self):

        if self.web_control_active:

            return True

        if len(self.available_screens) <= 1:

            messagebox.showinfo(
                "Pantallas",
                (
                    "No hay una pantalla disponible para reproducir "
                    "sin compartir la pantalla del editor. Usá el "
                    "servidor web para controlar desde otro dispositivo."
                )
            )

            return False

        editor_screen_index = self.get_editor_screen_index()

        for scene in self.scenes:

            if scene.screen_index == editor_screen_index:

                messagebox.showinfo(
                    "Pantallas",
                    (
                        f"'{scene.name}' está asociado a la pantalla "
                        "del editor. Asociá ese escenario a otra "
                        "pantalla antes de ejecutar."
                    )
                )

                return False

        return True

    # =========================================================
    # UI
    # =========================================================

    def build_ui(self):

        self.top = tk.Frame(
            self.root,
            bg="#202020",
            height=50
        )

        self.top.pack(
            side="top",
            fill="x"
        )

        tk.Button(
            self.top,
            text="Nuevo",
            command=self.new_project
        ).pack(
            side="left",
            padx=4,
            pady=5
        )

        tk.Button(
            self.top,
            text="Abrir",
            command=self.open_project
        ).pack(
            side="left",
            padx=4,
            pady=5
        )

        tk.Button(
            self.top,
            text="Guardar",
            command=self.save_project
        ).pack(
            side="left",
            padx=4,
            pady=5
        )

        tk.Button(
            self.top,
            text="+ Escena",
            command=self.add_scene
        ).pack(
            side="left",
            padx=(15, 4),
            pady=5
        )

        self.scene_var = tk.StringVar()

        self.scene_combo = ttk.Combobox(
            self.top,
            textvariable=self.scene_var,
            state="readonly",
            width=18
        )

        self.scene_combo.pack(
            side="left",
            padx=4,
            pady=5
        )

        self.scene_combo.bind(
            "<<ComboboxSelected>>",
            self.scene_selected
        )

        tk.Button(
            self.top,
            text="Editar",
            command=self.edit_selected_scene
        ).pack(
            side="left",
            padx=4,
            pady=5
        )

        tk.Button(
            self.top,
            text="Eliminar",
            command=self.delete_selected_scene
        ).pack(
            side="left",
            padx=4,
            pady=5
        )

        self.screen_var = tk.StringVar()

        self.screen_combo = ttk.Combobox(
            self.top,
            textvariable=self.screen_var,
            state="readonly",
            width=24
        )

        self.screen_combo.pack(
            side="left",
            padx=(15, 4),
            pady=5
        )

        tk.Button(
            self.top,
            text="Asociar",
            command=self.assign_selected_screen
        ).pack(
            side="left",
            padx=4,
            pady=5
        )

        self.orientation_labels = {
            "horizontal": "Horizontal",
            "vertical": "Vertical",
            "horizontal_inverted": "Horizontal invertida",
            "vertical_inverted": "Vertical invertida"
        }
        self.orientation_values = {
            label: value
            for value, label in self.orientation_labels.items()
        }
        self.orientation_combo = ttk.Combobox(
            self.top,
            state="readonly",
            width=20,
            values=list(self.orientation_values.keys())
        )
        self.orientation_combo.pack(
            side="left",
            padx=4,
            pady=5
        )
        self.orientation_combo.bind(
            "<<ComboboxSelected>>",
            self.assign_selected_orientation
        )

        tk.Button(
            self.top,
            text="Reescalar",
            command=self.rescale_current_scene
        ).pack(
            side="left",
            padx=4,
            pady=5
        )

        tk.Button(
            self.top,
            text="Ejecutar",
            command=self.execute_scenes
        ).pack(
            side="left",
            padx=(15, 4),
            pady=5
        )

        tk.Button(
            self.top,
            text="Modo edición",
            command=self.enter_edit_mode
        ).pack(
            side="left",
            padx=4,
            pady=5
        )

        tk.Button(
            self.top,
            text="Web",
            command=self.start_web_server
        ).pack(
            side="left",
            padx=4,
            pady=5
        )

        tk.Button(
            self.top,
            text="+ Cara",
            command=self.add_face
        ).pack(
            side="left",
            padx=4,
            pady=5
        )

        tk.Button(
            self.top,
            text="+ Círculo",
            command=self.add_circular_face
        ).pack(
            side="left",
            padx=4,
            pady=5
        )

        tk.Button(
            self.top,
            text="Galería",
            command=lambda: self.open_gallery("add")
        ).pack(
            side="left",
            padx=4,
            pady=5
        )

        tk.Button(
            self.top,
            text="Archivo",
            command=self.change_face_file
        ).pack(
            side="left",
            padx=4,
            pady=5
        )

        self.scene_label = tk.Label(
            self.top,
            text="",
            bg="#202020",
            fg="white"
        )

        self.scene_label.pack(
            side="left",
            padx=20
        )

        self.canvas = tk.Canvas(
            self.root,
            bg="black",
            highlightthickness=0
        )

        self.canvas.pack(
            fill="both",
            expand=True
        )

        self.canvas.bind(
            "<ButtonPress-1>",
            self.mouse_down
        )

        self.canvas.bind(
            "<B1-Motion>",
            self.mouse_move
        )

        self.canvas.bind(
            "<ButtonRelease-1>",
            self.mouse_up
        )

        self.canvas.bind(
            "<ButtonPress-3>",
            self.show_face_context_menu
        )

        self.canvas.bind(
            "<ButtonPress-2>",
            self.show_face_context_menu
        )

        self.canvas.bind(
            "<Configure>",
            self.canvas_resize
        )

        self.add_face_button = tk.Button(
            self.canvas,
            text="+",
            font=("Arial", 22, "bold"),
            command=self.add_face,
            width=3,
            height=1
        )

        self.canvas.create_window(
            60,
            60,
            window=self.add_face_button
        )

        self.root.bind(
            "<Escape>",
            self.escape
        )

        self.update_screen_combo()

    # =========================================================
    # PROYECTO
    # =========================================================

    def is_execution_mode(self):

        return self.execution_mode

    def warn_execution_mode(self):

        messagebox.showinfo(
            "Modo ejecución",
            "Salí del modo ejecución para editar."
        )

    def get_user_documents_dir(self):

        home_dir = os.path.expanduser(
            "~"
        )

        candidates = [
            os.path.join(home_dir, "Documentos"),
            os.path.join(home_dir, "Documents")
        ]

        for candidate in candidates:

            if os.path.isdir(candidate):

                return candidate

        return candidates[0]

    def maximize_main_window(self):

        try:

            if sys.platform.startswith("win"):

                self.root.state("zoomed")

                return

            if sys.platform.startswith("linux"):

                try:

                    self.root.attributes(
                        "-zoomed",
                        True
                    )

                    return

                except tk.TclError:

                    pass

            width = self.root.winfo_screenwidth()
            height = self.root.winfo_screenheight()

            self.root.geometry(
                f"{width}x{height}+0+0"
            )

        except Exception:

            pass

    def center_window(
        self,
        window,
        width,
        height
    ):

        window.update_idletasks()

        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()

        x = max(
            (screen_width - width) // 2,
            0
        )

        y = max(
            (screen_height - height) // 2,
            0
        )

        window.geometry(
            f"{width}x{height}+{x}+{y}"
        )

    def get_projects_root_dir(self):

        return os.path.join(
            self.get_user_documents_dir(),
            "mappingSoft",
            "proyectos"
        )

    def get_gallery_dir(self):

        gallery_dir = os.path.join(
            self.get_user_documents_dir(),
            "mappingSoft",
            "galeria"
        )
        os.makedirs(
            gallery_dir,
            exist_ok=True
        )
        return gallery_dir

    def get_gallery_items(self):

        images = []
        animations = []

        for filename in sorted(os.listdir(self.get_gallery_dir())):

            path = os.path.join(self.get_gallery_dir(), filename)

            if not os.path.isfile(path) or not self.is_allowed_media_file(path):
                continue

            item = {
                "name": filename,
                "path": path
            }

            if os.path.splitext(filename)[1].lower() in ANIMATED_IMAGE_EXTENSIONS:
                animations.append(item)
            else:
                images.append(item)

        return {
            "images": images,
            "animations": animations
        }

    def add_file_to_gallery(self, source_path):

        if not self.is_allowed_media_file(source_path):
            raise ValueError("Formato no permitido.")

        filename = self.safe_upload_filename(os.path.basename(source_path))
        target_path = os.path.join(self.get_gallery_dir(), filename)
        base_name, extension = os.path.splitext(filename)
        suffix = 1

        while os.path.exists(target_path):
            target_path = os.path.join(
                self.get_gallery_dir(),
                f"{base_name}_{suffix:02d}{extension}"
            )
            suffix += 1

        shutil.copy2(source_path, target_path)
        return target_path

    def delete_gallery_item(self, filename):

        path = os.path.join(self.get_gallery_dir(), os.path.basename(filename))

        if os.path.isfile(path):
            os.remove(path)

    def open_gallery(self, mode, face=None, shape="rectangle"):

        if self.is_execution_mode():
            self.warn_execution_mode()
            return

        if not self.require_project_for_desktop_action():
            return

        gallery = tk.Toplevel(self.root)
        gallery.title("Galería")
        gallery.transient(self.root)
        gallery.grab_set()

        screen_height = self.root.winfo_screenheight()
        height = max(screen_height // 2, 360)
        width = min(max(self.root.winfo_screenwidth() * 3 // 4, 720), 1100)
        self.center_window(gallery, width, height)

        selected = {"path": None, "button": None}
        thumbnails = []
        animated_labels = []

        def select_item(path, button):
            if selected["button"] is not None:
                selected["button"].configure(relief="raised", bg="#2b2b2b")
            selected["path"] = path
            selected["button"] = button
            button.configure(relief="sunken", bg="#2d7d8c")

        def add_to_gallery():
            source_path = filedialog.askopenfilename(
                title="Agregar imagen o GIF",
                filetypes=[("Imágenes y GIF", "*.png *.jpg *.jpeg *.bmp *.webp *.gif")]
            )
            if not source_path:
                return
            try:
                self.add_file_to_gallery(source_path)
            except Exception as error:
                messagebox.showerror("Galería", str(error))
                return
            gallery.destroy()
            self.open_gallery(mode, face, shape)

        def delete_selected():
            if not selected["path"]:
                return
            self.delete_gallery_item(os.path.basename(selected["path"]))
            gallery.destroy()
            self.open_gallery(mode, face, shape)

        def use_selected():
            if not selected["path"]:
                return
            try:
                stored_path = self.save_source_file_to_assets(
                    selected["path"], self.current_scene
                )
            except Exception as error:
                messagebox.showerror("Galería", str(error))
                return

            if mode == "add":
                new_face = Face(shape=shape)
                offset = len(self.current_scene.faces) * 30
                new_face.points = [
                    [300 + offset, 200 + offset],
                    [600 + offset, 200 + offset],
                    [600 + offset, 500 + offset],
                    [300 + offset, 500 + offset]
                ]
                self.current_scene.faces.append(new_face)
                face_to_update = new_face
            else:
                face_to_update = face

            face_to_update.filename = stored_path
            face_to_update.load_file()
            self.selected_face = face_to_update
            self.save_project(notify=False)
            self.redraw()
            gallery.destroy()

        notebook = ttk.Notebook(gallery)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        def build_tab(parent, items, animated=False):
            canvas = tk.Canvas(parent, bg="#1c1c1c", highlightthickness=0)
            scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
            horizontal_scrollbar = ttk.Scrollbar(parent, orient="horizontal", command=canvas.xview)
            content = tk.Frame(canvas, bg="#1c1c1c")
            content.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.create_window((0, 0), window=content, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal_scrollbar.set)
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            horizontal_scrollbar.pack(side="bottom", fill="x")

            for index, item in enumerate(items):
                row, column = divmod(index, 6)
                try:
                    with Image.open(item["path"]) as source:
                        preview = source.convert("RGB")
                        preview.thumbnail((220, 180))
                        photo = ImageTk.PhotoImage(preview)
                except Exception:
                    continue
                button = tk.Button(content, image=photo, text=item["name"], compound="top", wraplength=520, bg="#2b2b2b", fg="white", command=lambda path=item["path"], button=None: None)
                button.configure(command=lambda path=item["path"], button=button: select_item(path, button))
                button.grid(row=row, column=column, padx=6, pady=6, sticky="n")
                thumbnails.append(photo)

                if animated:
                    try:
                        with Image.open(item["path"]) as source:
                            frames = []
                            durations = []
                            for frame in ImageSequence.Iterator(source):
                                preview = frame.convert("RGB")
                                preview.thumbnail((220, 180))
                                frames.append(ImageTk.PhotoImage(preview))
                                durations.append(max(int(frame.info.get("duration", 100)), 40))
                            if frames:
                                animated_labels.append([button, frames, durations, 0])
                                thumbnails.extend(frames)
                    except Exception:
                        pass

            return canvas

        items = self.get_gallery_items()
        image_tab = tk.Frame(notebook, bg="#1c1c1c")
        animation_tab = tk.Frame(notebook, bg="#1c1c1c")
        notebook.add(image_tab, text="Imágenes")
        notebook.add(animation_tab, text="Animaciones")
        build_tab(image_tab, items["images"])
        build_tab(animation_tab, items["animations"], animated=True)

        def animate_previews():
            if not gallery.winfo_exists():
                return
            for entry in animated_labels:
                button, frames, durations, index = entry
                button.configure(image=frames[index])
                entry[3] = (index + 1) % len(frames)
            gallery.after(100, animate_previews)

        animate_previews()
        commands = tk.Frame(gallery)
        commands.pack(fill="x", padx=8, pady=(0, 8))
        if mode == "add":
            tk.Button(commands, text="+ Cara", command=use_selected).pack(side="left", padx=4)
        else:
            tk.Button(commands, text="Usar", command=use_selected).pack(side="left", padx=4)
        tk.Button(commands, text="Agregar imagen o animación", command=add_to_gallery).pack(side="left", padx=4)
        tk.Button(commands, text="Eliminar", command=delete_selected).pack(side="left", padx=4)
        tk.Button(commands, text="Volver", command=gallery.destroy).pack(side="right", padx=4)
        gallery._thumbnails = thumbnails

    def normalize_project_name(
        self,
        name
    ):

        value = re.sub(
            r"\s+",
            "_",
            (name or "Proyecto").strip()
        )

        value = re.sub(
            r"[^A-Za-z0-9_-]",
            "",
            value
        )

        return value or "Proyecto"

    def get_project_file_path(
        self,
        project_dir
    ):

        return os.path.join(
            project_dir,
            "project.json"
        )

    def get_project_assets_dir(
        self,
        project_dir
    ):

        return os.path.join(
            project_dir,
            "assets"
        )

    def ensure_project_structure(
        self,
        project_dir
    ):

        os.makedirs(
            project_dir,
            exist_ok=True
        )

        os.makedirs(
            self.get_project_assets_dir(project_dir),
            exist_ok=True
        )

    def get_project_list(self):

        if not os.path.isdir(self.projects_root_dir):
            return []

        projects = []

        for entry in sorted(
            os.listdir(self.projects_root_dir)
        ):

            path = os.path.join(
                self.projects_root_dir,
                entry
            )

            if os.path.isdir(path):

                projects.append({
                    "name": entry,
                    "path": path
                })

        return projects

    def create_project_folder(
        self,
        name
    ):

        base_name = self.normalize_project_name(
            name
        )

        candidate = base_name
        suffix = 1

        while os.path.exists(
            os.path.join(
                self.projects_root_dir,
                candidate
            )
        ):

            candidate = f"{base_name}_{suffix:02d}"
            suffix += 1

        project_dir = os.path.join(
            self.projects_root_dir,
            candidate
        )

        self.ensure_project_structure(
            project_dir
        )

        return project_dir

    def set_current_project_dir(
        self,
        project_dir
    ):

        self.current_project_dir = project_dir

        self.current_assets_dir = self.get_project_assets_dir(
            project_dir
        )

        self.project_file = self.get_project_file_path(
            project_dir
        )

        self.project_name = os.path.basename(
            project_dir
        )

        self.ensure_project_structure(
            project_dir
        )

    def resolve_media_path(
        self,
        media_path
    ):

        if not media_path:
            return ""

        if os.path.isabs(media_path):
            return media_path

        if self.current_project_dir:

            absolute = os.path.join(
                self.current_project_dir,
                media_path
            )

            if os.path.exists(absolute):
                return absolute

            asset_fallback = os.path.join(
                self.current_assets_dir,
                os.path.basename(media_path)
            )

            if os.path.exists(asset_fallback):
                return asset_fallback

        return media_path

    def media_to_stored_path(
        self,
        media_path
    ):

        if not media_path:
            return ""

        if (
            self.current_project_dir
            and os.path.isabs(media_path)
        ):

            try:

                relative = os.path.relpath(
                    media_path,
                    self.current_project_dir
                )

                if not relative.startswith(".."):

                    return relative.replace("\\", "/")

            except Exception:

                pass

        return media_path

    def is_allowed_media_file(
        self,
        filename
    ):

        extension = os.path.splitext(
            filename or ""
        )[1].lower()

        return (
            extension in IMAGE_EXTENSIONS
            or extension in ANIMATED_IMAGE_EXTENSIONS
        )

    def ensure_current_project(self):

        return bool(
            self.current_project_dir
        )

    def require_project_for_desktop_action(self):

        if self.ensure_current_project():
            return True

        self.show_desktop_project_manager(
            startup=False
        )

        if self.ensure_current_project():
            return True

        return False

    def initialize_project(
        self,
        project_dir,
        create_default_scene=True
    ):

        self.close_all_players()
        self.close_all_media()

        self.set_current_project_dir(
            project_dir
        )

        self.scenes = []
        self.current_scene = None
        self.selected_face = None
        self.selected_corner = None

        if create_default_scene:

            self.add_scene(
                name="Escena 1",
                ask_name=False
            )

        else:

            self.update_scene_combo()
            self.update_scene_label()
            self.redraw()

    def load_project_by_dir(
        self,
        project_dir
    ):

        self.ensure_project_structure(
            project_dir
        )

        self.set_current_project_dir(
            project_dir
        )

        if not os.path.exists(self.project_file):

            self.initialize_project(
                project_dir,
                create_default_scene=True
            )

            self.save_project(
                notify=False
            )

            return

        self.load_project_from_file(
            self.project_file
        )

    def show_desktop_project_manager(
        self,
        startup=False
    ):

        result = {
            "opened": False
        }

        dialog = tk.Toplevel(
            self.root
        )

        dialog.title(
            "Proyectos"
        )

        dialog.geometry(
            "520x380"
        )

        self.center_window(
            dialog,
            520,
            380
        )

        dialog.configure(
            bg="#202020"
        )

        dialog.transient(
            self.root
        )

        dialog.grab_set()

        tk.Label(
            dialog,
            text=(
                "Selecciona un proyecto para abrir"
            ),
            bg="#202020",
            fg="white"
        ).pack(
            pady=(12, 8)
        )

        listbox = tk.Listbox(
            dialog,
            bg="#111111",
            fg="white",
            selectbackground="#2d6cdf",
            activestyle="none"
        )

        listbox.pack(
            fill="both",
            expand=True,
            padx=12,
            pady=8
        )

        def refresh_projects():

            listbox.delete(
                0,
                tk.END
            )

            for project in self.get_project_list():

                listbox.insert(
                    tk.END,
                    project["name"]
                )

        def open_selected_project():

            selection = listbox.curselection()

            if not selection:

                messagebox.showinfo(
                    "Proyectos",
                    "Selecciona un proyecto."
                )

                return

            selected_name = listbox.get(
                selection[0]
            )

            selected_path = os.path.join(
                self.projects_root_dir,
                selected_name
            )

            self.load_project_by_dir(
                selected_path
            )

            result["opened"] = True

            dialog.destroy()

        def create_project():

            name = simpledialog.askstring(
                "Nuevo proyecto",
                "Nombre del proyecto:",
                parent=dialog
            )

            if not name:
                return

            project_dir = self.create_project_folder(
                name
            )

            self.initialize_project(
                project_dir,
                create_default_scene=True
            )

            self.save_project(
                notify=False
            )

            result["opened"] = True

            dialog.destroy()

        def close_dialog():

            result["opened"] = False

            dialog.destroy()

        controls = tk.Frame(
            dialog,
            bg="#202020"
        )

        controls.pack(
            fill="x",
            padx=12,
            pady=(6, 12)
        )

        tk.Button(
            controls,
            text="Abrir",
            command=open_selected_project
        ).pack(
            side="left",
            padx=4
        )

        tk.Button(
            controls,
            text="Crear nuevo",
            command=create_project
        ).pack(
            side="left",
            padx=4
        )

        tk.Button(
            controls,
            text="Cerrar",
            command=close_dialog
        ).pack(
            side="right",
            padx=4
        )

        dialog.protocol(
            "WM_DELETE_WINDOW",
            close_dialog
        )

        refresh_projects()

        self.root.wait_window(
            dialog
        )

        if result["opened"]:

            self.refresh_desktop_ui()

        return result["opened"]

    def new_project(self):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        name = simpledialog.askstring(
            "Nuevo proyecto",
            "Nombre del proyecto:",
            initialvalue="Proyecto",
            parent=self.root
        )

        if not name:
            return

        project_dir = self.create_project_folder(
            name
        )

        self.initialize_project(
            project_dir,
            create_default_scene=True
        )

        self.save_project(
            notify=False
        )

    # =========================================================
    # ESCENAS
    # =========================================================

    def add_scene(
        self,
        name=None,
        ask_name=True
    ):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        if not self.require_project_for_desktop_action():
            return

        scene_number = len(
            self.scenes
        ) + 1

        default_name = f"Escena {scene_number}"

        if ask_name:

            name = simpledialog.askstring(
                "Nueva escena",
                "Nombre de la escena:",
                initialvalue=name or default_name,
                parent=self.root
            )

        if not name:

            name = default_name

        scene = Scene(name)

        scene.space_width, scene.space_height = self.get_target_scene_space(
            scene
        )

        self.scenes.append(
            scene
        )

        self.current_scene = scene

        self.selected_face = None

        self.update_scene_combo()

        self.update_scene_label()

        self.redraw()

        if self.player_windows:

            self.show_edit_outputs()

        self.save_project(
            notify=False
        )

    def delete_selected_scene(self):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        scene = self.get_selected_scene()

        if scene is None:
            return

        if len(self.scenes) <= 1:

            messagebox.showinfo(
                "Escena",
                "El proyecto debe conservar al menos una escena."
            )

            return

        if not messagebox.askyesno(
            "Eliminar escena",
            f"¿Eliminar '{scene.name}'?"
        ):
            return

        self.close_scene_player(
            scene
        )

        for face in scene.faces:

            face.close_media()

        self.scenes.remove(
            scene
        )

        if self.current_scene == scene:

            self.current_scene = self.scenes[0]

        self.selected_face = None
        self.selected_corner = None

        self.update_scene_combo()

        self.update_scene_label()

        self.redraw()

        if self.player_windows:

            self.show_edit_outputs()

    def get_scene_combo_values(self):

        values = []

        for index, scene in enumerate(
            self.scenes
        ):

            values.append(
                f"{index + 1} - {scene.name}"
            )

        return values

    def update_scene_combo(self):

        if not hasattr(
            self,
            "scene_combo"
        ):
            return

        values = self.get_scene_combo_values()

        self.scene_combo[
            "values"
        ] = values

        if self.current_scene in self.scenes:

            index = self.scenes.index(
                self.current_scene
            )

            if index < len(values):

                self.scene_combo.current(
                    index
                )

        elif values:

            self.scene_combo.current(
                0
            )

        self.update_screen_combo_selection()

    def update_screen_combo(self):

        if not hasattr(
            self,
            "screen_combo"
        ):
            return

        self.screen_combo[
            "values"
        ] = [
            screen["name"]
            for screen in self.available_screens
        ]

        self.update_screen_combo_selection()

    def update_screen_combo_selection(
        self,
        scene=None
    ):

        if not hasattr(
            self,
            "screen_combo"
        ):
            return

        if not self.available_screens:
            return

        screen_index = 0

        if scene is not None:

            screen_index = scene.screen_index

        elif self.current_scene is not None:

            screen_index = self.current_scene.screen_index

        if screen_index >= len(
            self.available_screens
        ):
            screen_index = 0

        self.screen_combo.current(
            screen_index
        )

        if hasattr(self, "orientation_combo"):

            selected_scene = scene or self.current_scene

            if selected_scene is not None:

                self.orientation_combo.set(
                    self.orientation_labels[
                        self.get_scene_orientation(selected_scene)
                    ]
                )

    def get_selected_scene_index(self):

        if not hasattr(
            self,
            "scene_combo"
        ):
            return -1

        return self.scene_combo.current()

    def get_selected_scene(self):

        index = self.get_selected_scene_index()

        if index < 0:
            return self.current_scene

        if index >= len(
            self.scenes
        ):
            return self.current_scene

        return self.scenes[
            index
        ]

    def scene_selected(
        self,
        event=None
    ):

        scene = self.get_selected_scene()

        if scene is None:
            return

        self.update_screen_combo_selection(
            scene
        )

        self.current_scene = scene

        changed = self.adapt_scene_to_assigned_screen(
            scene
        )

        if changed:

            self.save_project(
                notify=False
            )

        self.update_scene_label()
        self.redraw()

    def edit_selected_scene(self):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        scene = self.get_selected_scene()

        if scene is None:
            return

        self.current_scene = scene

        changed = self.adapt_scene_to_assigned_screen(
            scene
        )

        if changed:

            self.save_project(
                notify=False
            )

        self.selected_face = None
        self.selected_corner = None

        self.update_scene_label()

        self.update_screen_combo_selection(
            scene
        )

        self.redraw()

        if self.player_windows:

            self.show_edit_outputs()

    def assign_selected_screen(self):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        scene = self.get_selected_scene()

        if scene is None:
            return

        screen_index = self.screen_combo.current()

        if screen_index < 0:
            screen_index = 0

        previous_width, previous_height = self.get_scene_space(
            scene
        )

        scene.screen_index = screen_index

        self.adapt_scene_to_assigned_screen(
            scene,
            source_width=previous_width,
            source_height=previous_height,
            force=True
        )

        self.update_screen_combo_selection(
            scene
        )

        if scene == self.current_scene:

            self.update_scene_label()

        self.redraw()

        self.save_project(
            notify=False
        )

        if scene in self.player_windows:

            self.close_scene_player(
                scene
            )

            self.play_scene(
                scene
            )

    def assign_selected_orientation(self, event=None):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        scene = self.get_selected_scene()

        if scene is None:
            return

        previous_width = int(scene.space_width or 0)
        previous_height = int(scene.space_height or 0)

        if previous_width <= 1 or previous_height <= 1:

            previous_width, previous_height = self.get_scene_space(scene)

        scene.orientation = self.orientation_values.get(
            self.orientation_combo.get(),
            "horizontal"
        )

        self.adapt_scene_to_assigned_screen(
            scene,
            source_width=previous_width,
            source_height=previous_height,
            force=True
        )

        self.current_scene = scene
        self.update_screen_combo_selection(scene)
        self.update_scene_label()
        self.redraw()
        self.save_project(notify=False)

    def update_scene_label(self):

        if self.current_scene:

            screen = self.get_screen(
                self.current_scene.screen_index
            )

            self.scene_label.config(
                text=(
                    f"[{self.project_name}] "
                    f"{self.current_scene.name} -> "
                    f"{screen['name']}"
                )
            )

    # =========================================================
    # CARAS
    # =========================================================

    def save_source_file_to_assets(
        self,
        source_path,
        scene=None
    ):

        if not source_path:
            return ""

        if not self.is_allowed_media_file(
            source_path
        ):

            raise ValueError(
                "Formato no permitido."
            )

        if not self.ensure_current_project():

            raise ValueError(
                "Debes abrir o crear un proyecto."
            )

        filename = self.safe_upload_filename(
            os.path.basename(source_path)
        )

        target_path = os.path.join(
            self.current_assets_dir,
            filename
        )

        shutil.copy2(
            source_path,
            target_path
        )

        return target_path

    def save_uploaded_file_to_assets(
        self,
        uploaded,
        scene=None
    ):

        if uploaded is None:
            raise ValueError("Archivo inválido.")

        if not self.is_allowed_media_file(
            uploaded.filename
        ):

            raise ValueError(
                "Formato no permitido."
            )

        if not self.ensure_current_project():

            raise ValueError(
                "Debes abrir o crear un proyecto."
            )

        filename = self.safe_upload_filename(
            uploaded.filename
        )

        path = os.path.join(
            self.current_assets_dir,
            filename
        )

        uploaded.save(
            path
        )

        return path

    def add_face(self):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        if not self.require_project_for_desktop_action():
            return

        if self.current_scene is None:
            return

        self.open_gallery("add", shape="rectangle")

    def add_circular_face(self):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        if not self.require_project_for_desktop_action():
            return

        if self.current_scene is None:
            return

        self.open_gallery("add", shape="circle")

    def change_face_file(self):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        face = self.selected_face

        if face is None:

            messagebox.showinfo(
                "Cara",
                "Primero selecciona una cara."
            )

            return

        self.open_gallery("replace", face)
        return True

    def delete_selected_face(self):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        face = self.selected_face

        if face is None:

            messagebox.showinfo(
                "Cara",
                "Primero selecciona una cara."
            )

            return

        if self.current_scene is None:
            return

        if face not in self.current_scene.faces:
            return

        if not messagebox.askyesno(
            "Eliminar cara",
            "¿Eliminar la cara seleccionada?"
        ):
            return

        face.close_media()

        self.current_scene.faces.remove(
            face
        )

        self.selected_face = None
        self.selected_corner = None
        self.dragging = False

        self.redraw()

    def toggle_selected_face_flip_x(self):

        self.toggle_selected_face_flip(
            "x"
        )

    def toggle_selected_face_flip_y(self):

        self.toggle_selected_face_flip(
            "y"
        )

    def rotate_selected_face(
        self,
        degrees
    ):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        face = self.selected_face

        if face is None:

            messagebox.showinfo(
                "Cara",
                "Primero selecciona una cara."
            )

            return

        face.rotation_degrees = (
            face.rotation_degrees + degrees
        ) % 360

        self.redraw()

    def toggle_selected_face_depth(self):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        face = self.selected_face

        if face is None:
            return

        if face.depth_point is None:
            face.depth_point = [0.5, 0.25]
        else:
            face.depth_point = None

        self.save_project(notify=False)
        self.redraw()

    def toggle_selected_face_flip(
        self,
        axis
    ):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        face = self.selected_face

        if face is None:

            messagebox.showinfo(
                "Cara",
                "Primero selecciona una cara."
            )

            return

        if axis == "x":

            face.flip_x = not face.flip_x

        elif axis == "y":

            face.flip_y = not face.flip_y

        self.redraw()

    # =========================================================
    # OBTENER FRAME
    # =========================================================

    def get_face_frame(
        self,
        face,
        playback=False,
        target_width=None,
        target_height=None
    ):

        if face.is_animated:

            frame = face.get_current_frame(
                playback=playback
            )

        else:

            frame = face.image

        if frame is None:
            return None

        if target_width and target_height:

            source_height, source_width = frame.shape[:2]

            if face.rotation_degrees in (90, 270):
                useful_width = target_height
                useful_height = target_width
            else:
                useful_width = target_width
                useful_height = target_height

            scale = min(
                max(
                    useful_width / source_width,
                    useful_height / source_height
                ) * 1.1,
                1.0
            )

            if scale < 1.0:

                frame = cv2.resize(
                    frame,
                    (
                        max(int(source_width * scale), 2),
                        max(int(source_height * scale), 2)
                    ),
                    interpolation=cv2.INTER_AREA
                )

        if face.flip_x and face.flip_y:
            frame = cv2.flip(
                frame,
                -1
            )

        elif face.flip_x:

            frame = cv2.flip(
                frame,
                1
            )

        elif face.flip_y:

            frame = cv2.flip(
                frame,
                0
            )

        if face.rotation_degrees:

            height, width = frame.shape[:2]
            matrix = cv2.getRotationMatrix2D(
                (width / 2, height / 2),
                face.rotation_degrees,
                1
            )
            cosine = abs(matrix[0, 0])
            sine = abs(matrix[0, 1])
            rotated_width = int(height * sine + width * cosine)
            rotated_height = int(height * cosine + width * sine)
            matrix[0, 2] += rotated_width / 2 - width / 2
            matrix[1, 2] += rotated_height / 2 - height / 2
            frame = cv2.warpAffine(
                frame,
                matrix,
                (rotated_width, rotated_height)
            )

        return frame

    def apply_face_depth(self, frame, face):

        if face.depth_point is None:
            return frame

        depth_x, depth_y = face.depth_point
        direction_x = depth_x - 0.5
        direction_y = depth_y - 0.5
        distance = (direction_x ** 2 + direction_y ** 2) ** 0.5

        if distance < 0.001:
            return frame

        direction_x /= distance
        direction_y /= distance
        strength = min(distance / 0.5, 0.9)
        frame_height, frame_width = frame.shape[:2]
        grid_x, grid_y = np.meshgrid(
            np.linspace(0, 1, frame_width, dtype=np.float32),
            np.linspace(0, 1, frame_height, dtype=np.float32)
        )
        centered_x = grid_x - 0.5
        centered_y = grid_y - 0.5

        if face.shape == "circle":
            radius = np.sqrt(centered_x ** 2 + centered_y ** 2) * 2
            falloff = np.clip(1 - radius ** 2, 0, 1)
        else:
            falloff = np.clip(
                1 - np.maximum(np.abs(centered_x), np.abs(centered_y)) * 2,
                0,
                1
            )

        displacement = strength * falloff * 0.18
        map_x = (grid_x - direction_x * displacement) * (frame_width - 1)
        map_y = (grid_y - direction_y * displacement) * (frame_height - 1)

        return cv2.remap(
            frame,
            map_x.astype(np.float32),
            map_y.astype(np.float32),
            cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE
        )

    # =========================================================
    # CREAR IMAGEN DE LA ESCENA
    # =========================================================

    def render_scene(
        self,
        width,
        height,
        scene=None,
        playback=False,
        show_screen_border=False
    ):

        output = np.zeros(
            (
                height,
                width,
                3
            ),
            dtype=np.uint8
        )

        if scene is None:

            scene = self.current_scene

        if scene is None:
            return output

        editor_width, editor_height = self.get_scene_space(
            scene
        )

        scale = min(
            width / editor_width,
            height / editor_height
        )
        offset_x = (width - editor_width * scale) / 2
        offset_y = (height - editor_height * scale) / 2
        orientation = self.get_scene_orientation(scene)

        def to_output(point):

            x, y = point

            if orientation in (
                "horizontal_inverted",
                "vertical_inverted"
            ):

                x = editor_width - x
                y = editor_height - y

            return [
                offset_x + x * scale,
                offset_y + y * scale
            ]

        guide_faces = []

        for face in scene.faces:

            destination_points = np.float32([
                to_output(point)
                for point in face.points
            ])

            polygon = np.int32(
                np.round(destination_points)
            )

            x, y, roi_width, roi_height = cv2.boundingRect(
                polygon
            )

            x0 = max(x, 0)
            y0 = max(y, 0)
            x1 = min(x + roi_width, width)
            y1 = min(y + roi_height, height)

            if x1 <= x0 or y1 <= y0:
                continue

            if show_screen_border:
                guide_faces.append((face, destination_points))

            # Cachea caras estáticas para evitar recalcular perspectiva cada frame.
            can_cache = (
                (not face.is_animated)
                or
                (face.is_animated and not playback)
            )

            destination_key = tuple(
                tuple(
                    round(float(value), 3)
                    for value in point
                )
                for point in destination_points
            )

            cache_key = (
                width,
                height,
                face.filename,
                face.flip_x,
                face.flip_y,
                face.rotation_degrees,
                face.shape,
                tuple(face.depth_point) if face.depth_point else None,
                face.is_animated,
                playback,
                destination_key
            )

            if (
                can_cache
                and face.cached_warp_key == cache_key
                and face.cached_warped is not None
                and face.cached_mask is not None
                and face.cached_roi is not None
            ):

                warped = face.cached_warped
                mask = face.cached_mask
                x0, y0, x1, y1 = face.cached_roi

            else:

                frame = self.get_face_frame(
                    face,
                    playback=playback,
                    target_width=x1 - x0,
                    target_height=y1 - y0
                )

                if frame is None:
                    continue

                frame = self.apply_face_depth(frame, face)

                frame_height, frame_width = frame.shape[:2]

                if frame_width <= 0 or frame_height <= 0:
                    continue

                source_points = np.float32([
                    [0, 0],
                    [frame_width - 1, 0],
                    [frame_width - 1, frame_height - 1],
                    [0, frame_height - 1]
                ])

                local_destination_points = destination_points - np.float32([
                    x0,
                    y0
                ])

                matrix = cv2.getPerspectiveTransform(
                    source_points,
                    local_destination_points
                )

                warped = cv2.warpPerspective(
                    frame,
                    matrix,
                    (
                        x1 - x0,
                        y1 - y0
                    )
                )

                mask = np.zeros(
                    (
                        y1 - y0,
                        x1 - x0
                    ),
                    dtype=np.uint8
                )

                local_polygon = np.int32(
                    np.round(local_destination_points)
                )

                cv2.fillConvexPoly(
                    mask,
                    local_polygon,
                    255
                )

                if face.shape == "circle":

                    source_mask = np.zeros(
                        (
                            frame_height,
                            frame_width
                        ),
                        dtype=np.uint8
                    )

                    cv2.ellipse(
                        source_mask,
                        (
                            frame_width // 2,
                            frame_height // 2
                        ),
                        (
                            frame_width // 2,
                            frame_height // 2
                        ),
                        0,
                        0,
                        360,
                        255,
                        -1
                    )

                    circular_mask = cv2.warpPerspective(
                        source_mask,
                        matrix,
                        (
                            x1 - x0,
                            y1 - y0
                        )
                    )

                    mask = cv2.bitwise_and(
                        mask,
                        circular_mask
                    )

                mask = mask == 255

                if can_cache:

                    face.cached_warp_key = cache_key
                    face.cached_warped = warped
                    face.cached_mask = mask
                    face.cached_roi = (
                        x0,
                        y0,
                        x1,
                        y1
                    )

            output_roi = output[
                y0:y1,
                x0:x1
            ]

            output_roi[
                mask
            ] = warped[
                mask
            ]

        if show_screen_border:

            guide_color = (255, 212, 140)

            for face, guide_points in guide_faces:

                if face.shape == "circle":

                    guide_matrix = cv2.getPerspectiveTransform(
                        np.float32([[0, 0], [1, 0], [1, 1], [0, 1]]),
                        guide_points
                    )

                    for radius in (0.25, 0.5, 0.75, 1.0):
                        source_circle = np.float32([[
                            [
                                0.5 + math.cos(math.tau * step / 32) * radius * 0.5,
                                0.5 + math.sin(math.tau * step / 32) * radius * 0.5
                            ]
                            for step in range(33)
                        ]])
                        projected_circle = cv2.perspectiveTransform(
                            source_circle,
                            guide_matrix
                        ).astype(np.int32)
                        cv2.polylines(
                            output,
                            [projected_circle],
                            False,
                            guide_color,
                            1,
                            cv2.LINE_AA
                        )

                    center = cv2.perspectiveTransform(
                        np.float32([[[0.5, 0.5]]]),
                        guide_matrix
                    )[0][0].astype(np.int32)

                    for step in range(8):
                        angle = math.tau * step / 8
                        edge = cv2.perspectiveTransform(
                            np.float32([[[
                                0.5 + math.cos(angle) * 0.5,
                                0.5 + math.sin(angle) * 0.5
                            ]]]),
                            guide_matrix
                        )[0][0].astype(np.int32)
                        cv2.line(output, center, edge, guide_color, 1, cv2.LINE_AA)

                else:

                    for fraction in (0.25, 0.5, 0.75):
                        top = guide_points[0] + (guide_points[1] - guide_points[0]) * fraction
                        bottom = guide_points[3] + (guide_points[2] - guide_points[3]) * fraction
                        left = guide_points[0] + (guide_points[3] - guide_points[0]) * fraction
                        right = guide_points[1] + (guide_points[2] - guide_points[1]) * fraction
                        cv2.line(output, top.astype(np.int32), bottom.astype(np.int32), guide_color, 1, cv2.LINE_AA)
                        cv2.line(output, left.astype(np.int32), right.astype(np.int32), guide_color, 1, cv2.LINE_AA)

            cv2.rectangle(
                output,
                (
                    int(round(offset_x)),
                    int(round(offset_y))
                ),
                (
                    int(round(offset_x + editor_width * scale)) - 1,
                    int(round(offset_y + editor_height * scale)) - 1
                ),
                (255, 255, 255),
                2
            )

        return output

    def get_scene_space(
        self,
        scene=None
    ):

        if scene is None:

            scene = self.current_scene

        if scene is not None:

            return self.get_target_scene_space(
                scene
            )

        width = int(self.canvas_width)
        height = int(self.canvas_height)

        if width <= 1:
            width = 1280

        if height <= 1:
            height = 720

        return width, height

    def get_editor_transform(
        self,
        scene=None
    ):

        scene_width, scene_height = self.get_scene_space(
            scene
        )

        canvas_width = max(
            int(self.canvas_width),
            1
        )

        canvas_height = max(
            int(self.canvas_height),
            1
        )

        scale = min(
            canvas_width / scene_width,
            canvas_height / scene_height
        )

        return scale, scale, scene_width, scene_height

    def scene_to_canvas_point(
        self,
        x,
        y,
        scene=None
    ):

        scale_x, scale_y, _, _ = self.get_editor_transform(
            scene
        )

        scene_width, scene_height = self.get_scene_space(scene)
        offset_x = (self.canvas_width - scene_width * scale_x) / 2
        offset_y = (self.canvas_height - scene_height * scale_y) / 2

        if self.get_scene_orientation(scene) in (
            "horizontal_inverted",
            "vertical_inverted"
        ):

            x = scene_width - x
            y = scene_height - y

        return offset_x + x * scale_x, offset_y + y * scale_y

    def canvas_to_scene_point(
        self,
        x,
        y,
        scene=None
    ):

        scale_x, scale_y, scene_width, scene_height = self.get_editor_transform(
            scene
        )

        offset_x = (self.canvas_width - scene_width * scale_x) / 2
        offset_y = (self.canvas_height - scene_height * scale_y) / 2
        scene_x = int(round((x - offset_x) / scale_x))
        scene_y = int(round((y - offset_y) / scale_y))

        if self.get_scene_orientation(scene) in (
            "horizontal_inverted",
            "vertical_inverted"
        ):

            scene_x = scene_width - scene_x
            scene_y = scene_height - scene_y

        scene_x = min(
            max(scene_x, 0),
            scene_width - 1
        )

        scene_y = min(
            max(scene_y, 0),
            scene_height - 1
        )

        return scene_x, scene_y

    # =========================================================
    # EDITOR
    # =========================================================

    def redraw(self):

        if not hasattr(
            self,
            "canvas"
        ):
            return

        self.canvas.delete(
            "face_image"
        )

        self.canvas.delete(
            "face_border"
        )

        self.canvas.delete(
            "corner"
        )

        self.canvas.delete(
            "face_grid"
        )

        self.canvas.delete(
            "screen_border"
        )

        self.canvas_width = (
            self.canvas.winfo_width()
        )

        self.canvas_height = (
            self.canvas.winfo_height()
        )

        if self.canvas_width <= 1:
            return

        if self.canvas_height <= 1:
            return

        with self.web_lock:

            output = self.render_scene(
                self.canvas_width,
                self.canvas_height,
                self.current_scene,
                playback=False
            )

        output = cv2.cvtColor(
            output,
            cv2.COLOR_BGR2RGB
        )

        image = Image.fromarray(
            output
        )

        photo = ImageTk.PhotoImage(
            image
        )

        self.canvas.create_image(
            0,
            0,
            image=photo,
            anchor="nw",
            tags="face_image"
        )

        # Importante: conservar referencia
        self.canvas.photo = photo

        # Bordes y esquinas
        if self.current_scene:

            scale_x, scale_y, scene_width, scene_height = self.get_editor_transform(
                self.current_scene
            )
            offset_x = (self.canvas_width - scene_width * scale_x) / 2
            offset_y = (self.canvas_height - scene_height * scale_y) / 2

            self.canvas.create_rectangle(
                offset_x,
                offset_y,
                offset_x + scene_width * scale_x,
                offset_y + scene_height * scale_y,
                outline="white",
                width=2,
                tags="screen_border"
            )

            for face in self.current_scene.faces:

                points = []

                for x, y in face.points:

                    cx, cy = self.scene_to_canvas_point(
                        x,
                        y,
                        self.current_scene
                    )

                    points.extend([
                        cx,
                        cy
                    ])

                if face == self.selected_face:

                    color = "yellow"

                else:

                    color = "cyan"

                self.canvas.create_polygon(
                    points,
                    outline=color,
                    width=2,
                    fill="",
                    tags="face_border"
                )

                canvas_points = [
                    (points[index], points[index + 1])
                    for index in range(0, len(points), 2)
                ]

                if face.shape == "circle":

                    guide_matrix = cv2.getPerspectiveTransform(
                        np.float32([
                            [0, 0],
                            [1, 0],
                            [1, 1],
                            [0, 1]
                        ]),
                        np.float32(face.points)
                    )

                    def guide_point(u, v):
                        projected = cv2.perspectiveTransform(
                            np.float32([[[u, v]]]),
                            guide_matrix
                        )[0][0]
                        return self.scene_to_canvas_point(
                            projected[0],
                            projected[1],
                            self.current_scene
                        )

                    for radius in (0.25, 0.5, 0.75, 1.0):
                        circle_points = []

                        for step in range(33):
                            angle = math.tau * step / 32
                            circle_points.extend(guide_point(
                                0.5 + math.cos(angle) * radius * 0.5,
                                0.5 + math.sin(angle) * radius * 0.5
                            ))

                        self.canvas.create_line(
                            circle_points,
                            fill="#8cd4ff",
                            width=1,
                            tags="face_grid"
                        )

                    for step in range(8):
                        angle = math.tau * step / 8
                        self.canvas.create_line(
                            guide_point(0.5, 0.5),
                            guide_point(
                                0.5 + math.cos(angle) * 0.5,
                                0.5 + math.sin(angle) * 0.5
                            ),
                            fill="#8cd4ff",
                            width=1,
                            tags="face_grid"
                        )

                else:

                    for fraction in (0.25, 0.5, 0.75):

                        top = (
                            canvas_points[0][0] + (canvas_points[1][0] - canvas_points[0][0]) * fraction,
                            canvas_points[0][1] + (canvas_points[1][1] - canvas_points[0][1]) * fraction
                        )
                        bottom = (
                            canvas_points[3][0] + (canvas_points[2][0] - canvas_points[3][0]) * fraction,
                            canvas_points[3][1] + (canvas_points[2][1] - canvas_points[3][1]) * fraction
                        )
                        left = (
                            canvas_points[0][0] + (canvas_points[3][0] - canvas_points[0][0]) * fraction,
                            canvas_points[0][1] + (canvas_points[3][1] - canvas_points[0][1]) * fraction
                        )
                        right = (
                            canvas_points[1][0] + (canvas_points[2][0] - canvas_points[1][0]) * fraction,
                            canvas_points[1][1] + (canvas_points[2][1] - canvas_points[1][1]) * fraction
                        )

                        self.canvas.create_line(
                            top,
                            bottom,
                            fill="#8cd4ff",
                            width=1,
                            tags="face_grid"
                        )
                        self.canvas.create_line(
                            left,
                            right,
                            fill="#8cd4ff",
                            width=1,
                            tags="face_grid"
                        )

                if face == self.selected_face:

                    if face.depth_point is not None:

                        left_scene = self.get_face_normalized_scene_point(
                            face,
                            0,
                            0.5
                        )
                        right_scene = self.get_face_normalized_scene_point(
                            face,
                            1,
                            0.5
                        )
                        left_canvas = self.scene_to_canvas_point(
                            left_scene[0],
                            left_scene[1],
                            self.current_scene
                        )
                        right_canvas = self.scene_to_canvas_point(
                            right_scene[0],
                            right_scene[1],
                            self.current_scene
                        )
                        depth_canvas = self.get_face_depth_canvas_point(face)
                        depth_color = (
                            "#ff9f1c"
                            if face.depth_point[1] < 0.5
                            else "#8e7dff"
                        )

                        self.canvas.create_line(
                            left_canvas,
                            right_canvas,
                            fill="#ffffff",
                            width=1,
                            dash=(4, 4),
                            tags="depth_guide"
                        )
                        self.canvas.create_oval(
                            depth_canvas[0] - 9,
                            depth_canvas[1] - 9,
                            depth_canvas[0] + 9,
                            depth_canvas[1] + 9,
                            fill=depth_color,
                            outline="white",
                            width=2,
                            tags="depth_guide"
                        )

                    for x, y in face.points:

                        cx, cy = self.scene_to_canvas_point(
                            x,
                            y,
                            self.current_scene
                        )

                        radius = 9

                        self.canvas.create_oval(
                            cx - radius,
                            cy - radius,
                            cx + radius,
                            cy + radius,
                            fill="red",
                            outline="white",
                            width=2,
                            tags="corner"
                        )

                self.canvas.tag_raise("screen_border")

    # =========================================================
    # MOUSE
    # =========================================================

    def find_face_at(
        self,
        x,
        y
    ):

        if self.current_scene is None:
            return None

        scene_x, scene_y = self.canvas_to_scene_point(
            x,
            y,
            self.current_scene
        )

        for face in reversed(
            self.current_scene.faces
        ):

            if self.point_in_polygon(
                scene_x,
                scene_y,
                face.points
            ):

                return face

        return None

    def show_face_context_menu(
        self,
        event
    ):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        face = self.find_face_at(
            event.x,
            event.y
        )

        if face is None:
            return

        self.selected_face = face
        self.selected_corner = None
        self.dragging = False

        self.redraw()

        menu = tk.Menu(
            self.root,
            tearoff=0
        )

        menu.add_command(
            label="Cambiar imagen o GIF",
            command=self.change_face_file
        )

        menu.add_command(
            label=(
                "Desactivar profundidad"
                if face.depth_point is not None
                else "Activar profundidad"
            ),
            command=self.toggle_selected_face_depth
        )

        menu.add_separator()

        menu.add_command(
            label=(
                "✓ Invertir en X"
                if face.flip_x
                else "Invertir en X"
            ),
            command=self.toggle_selected_face_flip_x
        )

        menu.add_command(
            label=(
                "✓ Invertir en Y"
                if face.flip_y
                else "Invertir en Y"
            ),
            command=self.toggle_selected_face_flip_y
        )

        menu.add_separator()

        menu.add_command(
            label="Rotar 5° a la izquierda",
            command=lambda: self.rotate_selected_face(5)
        )

        menu.add_command(
            label="Rotar 5° a la derecha",
            command=lambda: self.rotate_selected_face(-5)
        )

        menu.add_command(
            label="Rotar 90° a la izquierda",
            command=lambda: self.rotate_selected_face(90)
        )

        menu.add_command(
            label="Rotar 90° a la derecha",
            command=lambda: self.rotate_selected_face(-90)
        )

        menu.add_separator()

        menu.add_command(
            label="Eliminar cara",
            command=self.delete_selected_face
        )

        try:

            menu.tk_popup(
                event.x_root,
                event.y_root
            )

        finally:

            menu.grab_release()

    def mouse_down(
        self,
        event
    ):

        if self.is_execution_mode():
            return

        if self.current_scene is None:
            return

        # Buscar esquina
        if self.selected_face:

            if self.selected_face.depth_point is not None:

                depth_x, depth_y = self.get_face_depth_canvas_point(
                    self.selected_face
                )

                if ((event.x - depth_x) ** 2 + (event.y - depth_y) ** 2) ** 0.5 < 20:

                    self.dragging_depth = True
                    self.dragging = True

                    return

            for index, (
                x,
                y
            ) in enumerate(
                self.selected_face.points
            ):

                cx, cy = self.scene_to_canvas_point(
                    x,
                    y,
                    self.current_scene
                )

                distance = (
                    (event.x - cx) ** 2 +
                    (event.y - cy) ** 2
                ) ** 0.5

                if distance < 20:

                    self.selected_corner = index

                    self.dragging = True

                    return

        face = self.find_face_at(
            event.x,
            event.y
        )

        if face is not None:

            self.selected_face = face

            self.selected_corner = None

            self.redraw()

            return

        self.selected_face = None

        self.selected_corner = None

        self.redraw()

    def mouse_move(
        self,
        event
    ):

        if self.is_execution_mode():
            return

        if not self.dragging:
            return

        if self.selected_face is None:
            return

        if self.dragging_depth:

            scene_x, scene_y = self.canvas_to_scene_point(
                event.x,
                event.y,
                self.current_scene
            )

            self.selected_face.depth_point = self.get_face_depth_from_scene_point(
                self.selected_face,
                scene_x,
                scene_y
            )

            self.redraw()

            return

        if self.selected_corner is None:
            return

        scene_x, scene_y = self.canvas_to_scene_point(
            event.x,
            event.y,
            self.current_scene
        )

        self.selected_face.points[
            self.selected_corner
        ] = [
            scene_x,
            scene_y
        ]

        self.redraw()

    def mouse_up(
        self,
        event
    ):

        if self.is_execution_mode():
            return

        self.dragging = False
        self.dragging_depth = False
        self.save_project(notify=False)

    # =========================================================
    # GEOMETRÍA
    # =========================================================

    def get_face_depth_scene_point(self, face):

        if face.depth_point is None:
            return None

        return self.get_face_normalized_scene_point(
            face,
            face.depth_point[0],
            face.depth_point[1]
        )

    def get_face_normalized_scene_point(self, face, normalized_x, normalized_y):

        matrix = cv2.getPerspectiveTransform(
            np.float32([[0, 0], [1, 0], [1, 1], [0, 1]]),
            np.float32(face.points)
        )
        point = cv2.perspectiveTransform(
            np.float32([[[normalized_x, normalized_y]]]),
            matrix
        )[0][0]

        return point[0], point[1]

    def get_face_depth_canvas_point(self, face):

        scene_point = self.get_face_depth_scene_point(face)

        return self.scene_to_canvas_point(
            scene_point[0],
            scene_point[1],
            self.current_scene
        )

    def get_face_depth_from_scene_point(self, face, scene_x, scene_y):

        matrix = cv2.getPerspectiveTransform(
            np.float32(face.points),
            np.float32([[0, 0], [1, 0], [1, 1], [0, 1]])
        )
        point = cv2.perspectiveTransform(
            np.float32([[[scene_x, scene_y]]]),
            matrix
        )[0][0]
        depth_x = min(max(float(point[0]), 0), 1)
        depth_y = min(max(float(point[1]), 0), 1)

        if face.shape == "circle":
            offset_x = depth_x - 0.5
            offset_y = depth_y - 0.5
            distance = (offset_x ** 2 + offset_y ** 2) ** 0.5

            if distance > 0.5:
                depth_x = 0.5 + offset_x * 0.5 / distance
                depth_y = 0.5 + offset_y * 0.5 / distance

        return [depth_x, depth_y]

    def normalize_face_depth_point(self, face, depth_point):

        if not isinstance(depth_point, (list, tuple)) or len(depth_point) != 2:
            return None

        try:
            depth_x = min(max(float(depth_point[0]), 0), 1)
            depth_y = min(max(float(depth_point[1]), 0), 1)
        except (TypeError, ValueError):
            return None

        if face.shape == "circle":
            offset_x = depth_x - 0.5
            offset_y = depth_y - 0.5
            distance = (offset_x ** 2 + offset_y ** 2) ** 0.5

            if distance > 0.5:
                depth_x = 0.5 + offset_x * 0.5 / distance
                depth_y = 0.5 + offset_y * 0.5 / distance

        return [depth_x, depth_y]

    def point_in_polygon(
        self,
        x,
        y,
        polygon
    ):

        inside = False

        j = len(
            polygon
        ) - 1

        for i in range(
            len(polygon)
        ):

            xi, yi = polygon[i]

            xj, yj = polygon[j]

            intersect = (
                ((yi > y) != (yj > y))
                and
                (
                    x <
                    (
                        (xj - xi)
                        *
                        (y - yi)
                        /
                        (yj - yi + 0.00001)
                    )
                    + xi
                )
            )

            if intersect:

                inside = not inside

            j = i

        return inside

    # =========================================================
    # RESIZE
    # =========================================================

    def canvas_resize(
        self,
        event
    ):

        self.canvas_width = (
            event.width
        )

        self.canvas_height = (
            event.height
        )

        self.redraw()

    def rescale_current_scene(self):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        scene = self.current_scene

        if scene is None:
            return

        changed = self.adapt_scene_to_assigned_screen(
            scene,
            force=True
        )

        if changed:

            self.save_project(
                notify=False
            )

        self.redraw()

    # =========================================================
    # GUARDAR
    # =========================================================

    def save_project(
        self,
        notify=True
    ):

        if not self.ensure_current_project():
            return

        if not self.project_file:

            self.project_file = self.get_project_file_path(
                self.current_project_dir
            )

        data = {
            "name": self.project_name,
            "width": self.canvas_width,
            "height": self.canvas_height,
            "scenes": []
        }

        for scene in self.scenes:

            scene_data = {
                "name": scene.name,
                "screen_index": scene.screen_index,
                "space_width": scene.space_width,
                "space_height": scene.space_height,
                "orientation": self.get_scene_orientation(scene),
                "faces": []
            }

            for face in scene.faces:

                scene_data[
                    "faces"
                ].append({

                    "points": face.points,

                    "file": self.media_to_stored_path(
                        face.filename
                    ),

                    "flip_x": face.flip_x,

                    "flip_y": face.flip_y,

                    "rotation_degrees": face.rotation_degrees,

                    "shape": face.shape,

                    "depth_point": face.depth_point
                })

            data[
                "scenes"
            ].append(
                scene_data
            )

        try:

            with open(
                self.project_file,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    data,
                    f,
                    indent=4,
                    ensure_ascii=False
                )

            if notify:

                messagebox.showinfo(
                    "Proyecto",
                    "Proyecto guardado."
                )

        except Exception as e:

            messagebox.showerror(
                "Error",
                str(e)
            )

    # =========================================================
    # ABRIR
    # =========================================================

    def load_project_from_file(
        self,
        filename
    ):

        self.close_all_players()

        self.close_all_media()

        with open(
            filename,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        project_dir = os.path.dirname(
            filename
        )

        self.set_current_project_dir(
            project_dir
        )

        self.project_name = data.get(
            "name",
            os.path.basename(project_dir)
        )

        default_scene_width = int(
            data.get(
                "width",
                self.canvas_width
            )
        )

        default_scene_height = int(
            data.get(
                "height",
                self.canvas_height
            )
        )

        self.scenes = []

        for scene_data in data.get(
            "scenes",
            []
        ):

            scene = Scene(
                scene_data.get(
                    "name",
                    "Escena"
                ),
                scene_data.get(
                    "screen_index",
                    0
                ),
                scene_data.get(
                    "space_width",
                    default_scene_width
                ),
                scene_data.get(
                    "space_height",
                    default_scene_height
                ),
                scene_data.get(
                    "orientation",
                    "horizontal"
                )
            )

            for face_data in scene_data.get(
                "faces",
                []
            ):

                raw_file = face_data.get(
                    "file",
                    ""
                )

                media_path = self.resolve_media_path(
                    raw_file
                )

                face = Face(
                    points=face_data.get(
                        "points"
                    ),
                    filename=media_path,
                    flip_x=face_data.get(
                        "flip_x",
                        False
                    ),
                    flip_y=face_data.get(
                        "flip_y",
                        False
                    ),
                    rotation_degrees=face_data.get(
                        "rotation_degrees",
                        0
                    ),
                    shape=face_data.get(
                        "shape",
                        "rectangle"
                    ),
                    depth_point=face_data.get(
                        "depth_point"
                    )
                )

                scene.faces.append(
                    face
                )

            self.scenes.append(
                scene
            )

        for scene in self.scenes:

            self.adapt_scene_to_assigned_screen(
                scene
            )

        if self.scenes:

            self.current_scene = (
                self.scenes[0]
            )

        else:

            self.add_scene(
                name="Escena 1",
                ask_name=False
            )

        self.selected_face = None

        self.update_scene_combo()

        self.update_scene_label()

        self.redraw()

        self.save_project(
            notify=False
        )

    def open_project(self):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        if not self.show_desktop_project_manager(
            startup=False
        ):

            return

    def get_current_project_info(self):

        if not self.current_project_dir:

            return {
                "name": "",
                "path": "",
                "has_project": False
            }

        return {
            "name": self.project_name,
            "path": self.current_project_dir,
            "has_project": True
        }

    # =========================================================
    # SERVIDOR WEB
    # =========================================================

    def get_local_ip_address(self):

        probe = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM
        )

        try:

            probe.connect((
                "8.8.8.8",
                80
            ))

            ip = probe.getsockname()[0]

            if ip:
                return ip

        except Exception:

            pass

        finally:

            probe.close()

        return "127.0.0.1"

    def start_web_server(
        self,
        notify=True
    ):

        self.web_host_ip = self.get_local_ip_address()

        if self.web_thread and self.web_thread.is_alive():

            if notify:

                messagebox.showinfo(
                    "Web",
                    (
                        "Editor web activo.\n"
                        f"Local: http://127.0.0.1:{self.web_port}\n"
                        f"Red: http://{self.web_host_ip}:{self.web_port}"
                    )
                )

            return

        try:

            from flask import Flask

            app = Flask(
                __name__,
                template_folder="templates",
                static_folder="static"
            )

            self.configure_web_routes(
                app
            )

            self.web_server = app

            self.web_thread = threading.Thread(
                target=lambda: app.run(
                    host="0.0.0.0",
                    port=self.web_port,
                    debug=False,
                    use_reloader=False,
                    threaded=True
                ),
                daemon=True
            )

            self.web_thread.start()

            if notify:

                messagebox.showinfo(
                    "Web",
                    (
                        "Editor web activo.\n"
                        f"Local: http://127.0.0.1:{self.web_port}\n"
                        f"Red: http://{self.web_host_ip}:{self.web_port}"
                    )
                )

        except ImportError:

            if notify:

                messagebox.showerror(
                    "Web",
                    "Flask no está instalado. Instalalo con: pip install flask"
                )

            else:

                print(
                    "Flask no está instalado. Instalalo con: pip install flask"
                )

        except Exception as e:

            if notify:

                messagebox.showerror(
                    "Web",
                    str(e)
                )

            else:

                print(
                    "No se pudo iniciar servidor web:",
                    e
                )

    def configure_web_routes(
        self,
        app
    ):

        from flask import Response, jsonify, request, render_template, send_from_directory

        @app.route("/")
        def web_index():

            return render_template(
                "index.html"
            )

        @app.route("/api/state")
        def web_state():

            return jsonify(
                self.get_web_state()
            )

        @app.route("/api/gallery")
        def web_gallery():

            return jsonify(self.get_gallery_items())

        @app.route("/api/gallery/media/<path:filename>")
        def web_gallery_media(filename):

            return send_from_directory(
                self.get_gallery_dir(),
                os.path.basename(filename)
            )

        @app.route("/api/gallery", methods=["POST"])
        def web_add_gallery_item():

            uploaded = request.files.get("file")

            if uploaded is None or not self.is_allowed_media_file(uploaded.filename):
                return jsonify({"ok": False, "error": "Formato no permitido."}), 400

            filename = self.safe_upload_filename(uploaded.filename)
            base_name, extension = os.path.splitext(filename)
            target_path = os.path.join(self.get_gallery_dir(), filename)
            suffix = 1

            while os.path.exists(target_path):
                target_path = os.path.join(
                    self.get_gallery_dir(),
                    f"{base_name}_{suffix:02d}{extension}"
                )
                suffix += 1

            uploaded.save(target_path)
            return jsonify(self.get_gallery_items())

        @app.route("/api/gallery/<path:filename>", methods=["DELETE"])
        def web_delete_gallery_item(filename):

            self.delete_gallery_item(filename)
            return jsonify(self.get_gallery_items())

        @app.route("/api/gallery/use", methods=["POST"])
        def web_use_gallery_item():

            data = request.get_json(silent=True) or {}
            filename = os.path.basename(data.get("filename", ""))
            mode = data.get("mode")
            shape = data.get("shape", "rectangle")
            scene_index = data.get("scene_index")
            gallery_path = os.path.join(self.get_gallery_dir(), filename)

            if shape not in ("rectangle", "circle"):
                return jsonify({"ok": False, "error": "Forma inválida."}), 400

            if not filename or not os.path.isfile(gallery_path):
                return jsonify({"ok": False, "error": "Elemento de galería inválido."}), 404

            with self.web_lock:

                if not self.ensure_current_project():
                    return jsonify({
                        "ok": False,
                        "project_required": True,
                        "error": "Debes abrir o crear un proyecto."
                    }), 409

                scene = self.get_scene_by_index(scene_index)

                if scene is None:
                    return jsonify({"ok": False}), 404

                stored_path = self.save_source_file_to_assets(gallery_path, scene)

                if mode == "add":
                    face = Face(shape=shape)
                    offset = len(scene.faces) * 30
                    face.points = [
                        [300 + offset, 200 + offset],
                        [600 + offset, 200 + offset],
                        [600 + offset, 500 + offset],
                        [300 + offset, 500 + offset]
                    ]
                    scene.faces.append(face)
                elif mode == "replace":
                    face = self.get_face_by_index(scene_index, data.get("face_index"))
                    if face is None:
                        return jsonify({"ok": False}), 404
                else:
                    return jsonify({"ok": False, "error": "Acción inválida."}), 400

                face.filename = stored_path
                face.load_file()
                self.save_project(notify=False)

            self.schedule_ui_refresh()
            return jsonify(self.get_web_state())

        @app.route("/api/projects")
        def web_projects():

            projects = [
                project["name"]
                for project in self.get_project_list()
            ]

            return jsonify({
                "projects": projects,
                "current": self.project_name if self.current_project_dir else ""
            })

        @app.route("/api/projects", methods=["POST"])
        def web_create_project():

            data = request.get_json(
                silent=True
            ) or {}

            name = data.get(
                "name",
                "Proyecto"
            )

            def create_in_ui():

                with self.web_lock:

                    project_dir = self.create_project_folder(
                        name
                    )

                    self.initialize_project(
                        project_dir,
                        create_default_scene=True
                    )

                    self.save_project(
                        notify=False
                    )

            self.run_on_ui_thread(
                create_in_ui
            )

            return jsonify(
                self.get_web_state()
            )

        @app.route("/api/projects/open", methods=["POST"])
        def web_open_project():

            data = request.get_json(
                silent=True
            ) or {}

            project_name = data.get(
                "name",
                ""
            )

            if not project_name:

                return jsonify({
                    "ok": False,
                    "error": "Proyecto inválido."
                }), 400

            project_dir = os.path.join(
                self.projects_root_dir,
                project_name
            )

            if not os.path.isdir(project_dir):

                return jsonify({
                    "ok": False,
                    "error": "Proyecto no encontrado."
                }), 404

            def open_in_ui():

                with self.web_lock:

                    self.load_project_by_dir(
                        project_dir
                    )

            self.run_on_ui_thread(
                open_in_ui
            )

            return jsonify(
                self.get_web_state()
            )

        @app.route("/api/projects/close", methods=["POST"])
        def web_close_program():

            self.root.after(
                0,
                self.root.destroy
            )

            return jsonify({
                "ok": True
            })

        @app.route(
            "/api/scenes/<int:scene_index>/faces/<int:face_index>/depth",
            methods=["POST"]
        )
        def web_update_face_depth(scene_index, face_index):

            data = request.get_json(silent=True) or {}

            with self.web_lock:

                face = self.get_face_by_index(scene_index, face_index)

                if face is None:
                    return jsonify({"ok": False}), 404

                if data.get("enabled", True):
                    depth_point = self.normalize_face_depth_point(
                        face,
                        data.get("depth_point", [0.5, 0.25])
                    )

                    if depth_point is None:
                        return jsonify({"ok": False}), 400

                    face.depth_point = depth_point
                else:
                    face.depth_point = None

                self.save_project(notify=False)

            self.schedule_ui_refresh()

            return jsonify(self.get_web_state())

        @app.route("/api/scenes", methods=["POST"])
        def web_add_scene():

            data = request.get_json(
                silent=True
            ) or {}

            name = data.get(
                "name",
                f"Escena {len(self.scenes) + 1}"
            )

            screen_index = int(
                data.get(
                    "screen_index",
                    0
                )
            )

            with self.web_lock:

                if not self.ensure_current_project():

                    return jsonify({
                        "ok": False,
                        "project_required": True,
                        "error": "Debes abrir o crear un proyecto."
                    }), 409

                scene = Scene(
                    name,
                    screen_index,
                    orientation=data.get("orientation", "horizontal")
                )

                scene.space_width, scene.space_height = self.get_target_scene_space(
                    scene
                )

                self.scenes.append(
                    scene
                )

                self.current_scene = scene

                self.save_project(
                    notify=False
                )

            self.schedule_ui_refresh()

            return jsonify(
                self.get_web_state()
            )

        @app.route("/api/scenes/<int:index>", methods=["DELETE"])
        def web_delete_scene(index):

            with self.web_lock:

                if len(self.scenes) <= 1:

                    return jsonify({
                        "ok": False,
                        "error": "Debe quedar al menos una escena."
                    }), 400

                if index < 0 or index >= len(self.scenes):

                    return jsonify({
                        "ok": False,
                        "error": "Escena inválida."
                    }), 404

                scene = self.scenes[index]

                self.root.after(
                    0,
                    lambda scene=scene: self.close_scene_player(scene)
                )

                for face in scene.faces:

                    face.close_media()

                self.scenes.remove(
                    scene
                )

                if self.current_scene == scene:

                    self.current_scene = self.scenes[0]

                self.save_project(
                    notify=False
                )

            self.schedule_ui_refresh()

            return jsonify(
                self.get_web_state()
            )

        @app.route("/api/scenes/<int:index>/select", methods=["POST"])
        def web_select_scene(index):

            with self.web_lock:

                scene = self.get_scene_by_index(
                    index
                )

                if scene is None:

                    return jsonify({
                        "ok": False
                    }), 404

                self.current_scene = scene
                self.selected_face = None
                self.selected_corner = None

                changed = self.adapt_scene_to_assigned_screen(
                    scene
                )

                if changed:

                    self.save_project(
                        notify=False
                    )

            self.schedule_ui_refresh()

            return jsonify(
                self.get_web_state()
            )

        @app.route("/api/scenes/<int:index>/screen", methods=["POST"])
        def web_assign_scene_screen(index):

            data = request.get_json(
                silent=True
            ) or {}

            with self.web_lock:

                scene = self.get_scene_by_index(
                    index
                )

                if scene is None:

                    return jsonify({
                        "ok": False
                    }), 404

                previous_width, previous_height = self.get_scene_space(
                    scene
                )

                scene.screen_index = int(
                    data.get(
                        "screen_index",
                        0
                    )
                )

                self.adapt_scene_to_assigned_screen(
                    scene,
                    source_width=previous_width,
                    source_height=previous_height,
                    force=True
                )

                self.save_project(
                    notify=False
                )

            self.schedule_ui_refresh()

            return jsonify(
                self.get_web_state()
            )

        @app.route("/api/scenes/<int:index>/rescale", methods=["POST"])
        def web_rescale_scene(index):

            data = request.get_json(
                silent=True
            ) or {}

            with self.web_lock:

                scene = self.get_scene_by_index(
                    index
                )

                if scene is None:

                    return jsonify({
                        "ok": False
                    }), 404

                source_width = data.get(
                    "source_width"
                )

                source_height = data.get(
                    "source_height"
                )

                self.adapt_scene_to_assigned_screen(
                    scene,
                    source_width=source_width,
                    source_height=source_height,
                    force=True
                )

                self.save_project(
                    notify=False
                )

            self.schedule_ui_refresh()

            return jsonify(
                self.get_web_state()
            )

        @app.route("/api/scenes/<int:index>/orientation", methods=["POST"])
        def web_assign_scene_orientation(index):

            data = request.get_json(
                silent=True
            ) or {}
            orientation = data.get("orientation", "horizontal")

            if orientation not in (
                "horizontal",
                "vertical",
                "horizontal_inverted",
                "vertical_inverted"
            ):

                return jsonify({
                    "ok": False,
                    "error": "Orientación inválida."
                }), 400

            with self.web_lock:

                scene = self.get_scene_by_index(index)

                if scene is None:

                    return jsonify({"ok": False}), 404

                previous_width, previous_height = self.get_scene_space(scene)
                scene.orientation = orientation

                self.adapt_scene_to_assigned_screen(
                    scene,
                    source_width=previous_width,
                    source_height=previous_height,
                    force=True
                )

                self.save_project(notify=False)

            self.schedule_ui_refresh()

            return jsonify(self.get_web_state())

        @app.route("/api/scenes/<int:index>/faces", methods=["POST"])
        def web_add_face(index):

            uploaded = request.files.get(
                "file"
            )

            if uploaded is None:

                return jsonify({
                    "ok": False,
                    "error": "Debes subir una imagen o GIF."
                }), 400

            with self.web_lock:

                if not self.ensure_current_project():

                    return jsonify({
                        "ok": False,
                        "project_required": True,
                        "error": "Debes abrir o crear un proyecto."
                    }), 409

                scene = self.get_scene_by_index(
                    index
                )

                if scene is None:

                    return jsonify({
                        "ok": False
                    }), 404

                shape = request.form.get("shape", "rectangle")

                if shape not in ("rectangle", "circle"):
                    return jsonify({
                        "ok": False,
                        "error": "Forma inválida."
                    }), 400

                face = Face(shape=shape)

                offset = len(scene.faces) * 30

                face.points = [
                    [300 + offset, 200 + offset],
                    [600 + offset, 200 + offset],
                    [600 + offset, 500 + offset],
                    [300 + offset, 500 + offset]
                ]

                scene.faces.append(
                    face
                )

                try:

                    path = self.save_uploaded_file_to_assets(
                        uploaded,
                        scene
                    )

                except Exception as e:

                    scene.faces.remove(
                        face
                    )

                    return jsonify({
                        "ok": False,
                        "error": str(e)
                    }), 400

                face.filename = path
                face.load_file()

                self.save_project(
                    notify=False
                )

            self.schedule_ui_refresh()

            return jsonify(
                self.get_web_state()
            )

        @app.route(
            "/api/scenes/<int:scene_index>/faces/<int:face_index>",
            methods=["DELETE"]
        )
        def web_delete_face(scene_index, face_index):

            with self.web_lock:

                face = self.get_face_by_index(
                    scene_index,
                    face_index
                )

                scene = self.get_scene_by_index(
                    scene_index
                )

                if face is None or scene is None:

                    return jsonify({
                        "ok": False
                    }), 404

                face.close_media()

                scene.faces.remove(
                    face
                )

                self.save_project(
                    notify=False
                )

            self.schedule_ui_refresh()

            return jsonify(
                self.get_web_state()
            )

        @app.route(
            "/api/scenes/<int:scene_index>/faces/<int:face_index>/points",
            methods=["POST"]
        )
        def web_update_face_points(scene_index, face_index):

            data = request.get_json(
                silent=True
            ) or {}

            points = data.get(
                "points",
                []
            )

            if len(points) != 4:

                return jsonify({
                    "ok": False
                }), 400

            with self.web_lock:

                face = self.get_face_by_index(
                    scene_index,
                    face_index
                )

                if face is None:

                    return jsonify({
                        "ok": False
                    }), 404

                face.points = [
                    [
                        int(point[0]),
                        int(point[1])
                    ]
                    for point in points
                ]

                self.save_project(
                    notify=False
                )

            self.schedule_ui_refresh()

            return jsonify({
                "ok": True
            })

        @app.route(
            "/api/scenes/<int:scene_index>/faces/<int:face_index>/flip",
            methods=["POST"]
        )
        def web_flip_face(scene_index, face_index):

            data = request.get_json(
                silent=True
            ) or {}

            axis = data.get(
                "axis"
            )

            with self.web_lock:

                face = self.get_face_by_index(
                    scene_index,
                    face_index
                )

                if face is None:

                    return jsonify({
                        "ok": False
                    }), 404

                if axis == "x":

                    face.flip_x = not face.flip_x

                elif axis == "y":

                    face.flip_y = not face.flip_y

                self.save_project(
                    notify=False
                )

            self.schedule_ui_refresh()

            return jsonify(
                self.get_web_state()
            )

        @app.route(
            "/api/scenes/<int:scene_index>/faces/<int:face_index>/rotate",
            methods=["POST"]
        )
        def web_rotate_face(scene_index, face_index):

            data = request.get_json(
                silent=True
            ) or {}

            degrees = data.get(
                "degrees"
            )

            if not isinstance(degrees, (int, float)):

                return jsonify({
                    "ok": False
                }), 400

            with self.web_lock:

                face = self.get_face_by_index(
                    scene_index,
                    face_index
                )

                if face is None:

                    return jsonify({
                        "ok": False
                    }), 404

                face.rotation_degrees = (
                    face.rotation_degrees + degrees
                ) % 360

                self.save_project(
                    notify=False
                )

            self.schedule_ui_refresh()

            return jsonify(
                self.get_web_state()
            )

        @app.route(
            "/api/scenes/<int:scene_index>/faces/<int:face_index>/file",
            methods=["POST"]
        )
        def web_change_face_file(scene_index, face_index):

            uploaded = request.files.get(
                "file"
            )

            if uploaded is None:

                return jsonify({
                    "ok": False
                }), 400

            with self.web_lock:

                scene = self.get_scene_by_index(
                    scene_index
                )

                if scene is None:

                    return jsonify({
                        "ok": False
                    }), 404

                try:

                    path = self.save_uploaded_file_to_assets(
                        uploaded,
                        scene
                    )

                except Exception as e:

                    return jsonify({
                        "ok": False,
                        "error": str(e)
                    }), 400

                face = self.get_face_by_index(
                    scene_index,
                    face_index
                )

                if face is None:

                    return jsonify({
                        "ok": False
                    }), 404

                face.filename = path
                face.load_file()

                self.save_project(
                    notify=False
                )

            self.schedule_ui_refresh()

            return jsonify(
                self.get_web_state()
            )

        @app.route("/api/control/take", methods=["POST"])
        def web_take_control():

            self.root.after(
                0,
                self.enter_web_control
            )

            return jsonify({
                "ok": True
            })

        @app.route("/api/control/release", methods=["POST"])
        def web_release_control():

            self.root.after(
                0,
                self.release_web_control
            )

            return jsonify({
                "ok": True
            })

        @app.route("/api/control/execute", methods=["POST"])
        def web_execute():

            if not self.ensure_current_project():

                return jsonify({
                    "ok": False,
                    "project_required": True,
                    "error": "Debes abrir o crear un proyecto."
                }), 409

            self.root.after(
                0,
                self.execute_scenes
            )

            return jsonify({
                "ok": True
            })

        @app.route("/api/control/exit", methods=["POST"])
        def web_exit_execution():

            self.root.after(
                0,
                self.exit_execution_mode
            )

            return jsonify({
                "ok": True
            })

        @app.route("/stream/editor")
        def web_editor_stream():

            return Response(
                self.web_stream_frames(),
                mimetype=(
                    "multipart/x-mixed-replace; "
                    "boundary=frame"
                )
            )

    def safe_upload_filename(
        self,
        filename
    ):

        name = os.path.basename(
            filename or "archivo"
        )

        name = re.sub(
            r"[^A-Za-z0-9_.-]",
            "_",
            name
        )

        stamp = int(
            time.time() * 1000
        )

        return f"{stamp}_{name}"

    def get_scene_by_index(
        self,
        index
    ):

        if index < 0 or index >= len(
            self.scenes
        ):
            return None

        return self.scenes[
            index
        ]

    def get_face_by_index(
        self,
        scene_index,
        face_index
    ):

        scene = self.get_scene_by_index(
            scene_index
        )

        if scene is None:
            return None

        if face_index < 0 or face_index >= len(
            scene.faces
        ):
            return None

        return scene.faces[
            face_index
        ]

    def schedule_ui_refresh(self):

        self.root.after(
            0,
            self.refresh_desktop_ui
        )

    def run_on_ui_thread(
        self,
        callback
    ):

        done = threading.Event()
        state = {
            "error": None,
            "value": None
        }

        def wrapper():

            try:

                state["value"] = callback()

            except Exception as e:

                state["error"] = e

            finally:

                done.set()

        self.root.after(
            0,
            wrapper
        )

        done.wait()

        if state["error"] is not None:

            raise state["error"]

        return state["value"]

    def refresh_desktop_ui(self):

        self.update_scene_combo()
        self.update_scene_label()
        self.redraw()

        if self.player_windows and not self.execution_mode:

            self.show_edit_outputs()

    def get_web_state(self):

        with self.web_lock:

            current_scene_index = -1

            if self.current_scene in self.scenes:

                current_scene_index = self.scenes.index(
                    self.current_scene
                )

            scenes = []

            canvas_width, canvas_height = self.get_scene_space(
                self.current_scene
            )

            for scene in self.scenes:

                faces = []

                for face in scene.faces:

                    faces.append({
                        "points": face.points,
                        "file": os.path.basename(
                            face.filename
                        ),
                        "flip_x": face.flip_x,
                        "flip_y": face.flip_y,
                        "rotation_degrees": face.rotation_degrees,
                        "shape": face.shape,
                        "depth_point": face.depth_point
                    })

                scenes.append({
                    "name": scene.name,
                    "screen_index": scene.screen_index,
                    "space_width": scene.space_width,
                    "space_height": scene.space_height,
                    "orientation": self.get_scene_orientation(scene),
                    "faces": faces
                })

            return {
                "scenes": scenes,
                "current_scene_index": current_scene_index,
                "screens": self.available_screens,
                "execution_mode": self.execution_mode,
                "web_control_active": self.web_control_active,
                "single_screen": len(self.available_screens) <= 1,
                "canvas_width": canvas_width,
                "canvas_height": canvas_height,
                "web_local_url": f"http://127.0.0.1:{self.web_port}",
                "web_lan_url": f"http://{self.web_host_ip}:{self.web_port}",
                "project": self.get_current_project_info(),
                "projects": [
                    {
                        "name": project["name"],
                        "path": project["path"]
                    }
                    for project in self.get_project_list()
                ]
            }

    def web_stream_frames(self):

        while True:

            if self.execution_mode:

                time.sleep(
                    0.1
                )

                continue

            try:
                with self.web_lock:

                    width, height = self.get_scene_space(
                        self.current_scene
                    )

                    width = max(width, 2)
                    height = max(height, 2)

                    frame = self.render_scene(
                        width,
                        height,
                        self.current_scene,
                        playback=False
                    )

                ok, buffer = cv2.imencode(
                    ".jpg",
                    frame,
                    [
                        int(cv2.IMWRITE_JPEG_QUALITY),
                        80
                    ]
                )

                if ok:

                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + buffer.tobytes()
                        + b"\r\n"
                    )

            except Exception as e:

                print(
                    "Error stream web:",
                    e
                )

            time.sleep(
                0.04
            )

    def enter_web_control(self):

        self.web_control_active = True

        self.execution_mode = False

        self.stop_execution_workers()

        self.root.withdraw()

        self.close_all_players()

        if self.current_scene:

            self.play_scene(
                self.current_scene
            )

    def release_web_control(self):

        self.web_control_active = False

        self.execution_mode = False

        self.stop_execution_workers()

        self.close_all_players()

        self.root.deiconify()
        self.root.lift()

    # =========================================================
    # REPRODUCCIÓN
    # =========================================================

    def execute_scenes(self):

        if not self.require_project_for_desktop_action():
            return

        if not self.scenes:
            return

        if not self.validate_scene_outputs():
            return

        self.execution_mode = True

        self.dragging = False
        self.selected_corner = None

        for scene in self.scenes:

            for face in scene.faces:

                face.start_animation()

        self.close_all_players()

        for scene in self.scenes:

            self.play_scene(
                scene
            )

    def exit_execution_mode(self):

        self.execution_mode = False

        self.stop_execution_workers()

        self.dragging = False
        self.selected_corner = None

        self.close_all_players()
        self.player_running = False
        self.redraw()
        self.show_edit_outputs()

    def enter_edit_mode(self):

        if self.web_control_active:

            self.release_web_control()

            return

        self.exit_execution_mode()
        self.root.deiconify()
        self.root.lift()

    def stop_execution_workers(self):

        for scene in self.scenes:

            for face in scene.faces:

                face.stop_animation()

        for player in self.player_windows.values():

            stop_event = player.get(
                "render_stop_event"
            )

            if stop_event is not None:
                stop_event.set()

    def show_edit_outputs(self):

        if self.current_scene is None:
            return

        for scene in list(self.player_windows):

            if scene != self.current_scene:

                self.close_scene_player(scene)

        if self.current_scene not in self.player_windows:

            self.play_scene(self.current_scene)

        self.player_running = bool(
            self.player_windows
        )

    def play_scene(
        self,
        scene=None
    ):

        if scene is None:

            scene = self.current_scene

        if scene is None:
            return

        self.close_scene_player(
            scene
        )

        screen = self.get_screen(
            scene.screen_index
        )

        player_window = tk.Toplevel(
            self.root
        )

        player_window.title(
            scene.name
        )

        player_window.configure(
            bg="black"
        )

        player_window.overrideredirect(
            True
        )

        geometry = self.build_screen_geometry(
            screen
        )

        player_window.geometry(
            geometry
        )

        try:

            player_window.attributes(
                "-topmost",
                True
            )

        except tk.TclError:

            pass

        player_canvas = tk.Canvas(
            player_window,
            bg="black",
            width=screen["width"],
            height=screen["height"],
            highlightthickness=0
        )

        player_canvas.pack(
            fill="both",
            expand=True
        )

        player_window.bind(
            "<Escape>",
            self.escape
        )

        player_window.bind(
            "<F11>",
            self.escape
        )

        self.player_windows[
            scene
        ] = {
            "window": player_window,
            "canvas": player_canvas,
            "screen_width": screen["width"],
            "screen_height": screen["height"],
            "image_item": None,
            "latest_output": None,
            "latest_output_id": 0,
            "displayed_output_id": -1,
            "render_stop_event": threading.Event(),
            "running": True
        }

        player = self.player_windows[
            scene
        ]

        if self.execution_mode or scene == self.current_scene:

            threading.Thread(
                target=self.player_render_worker,
                args=(scene, player),
                daemon=True
            ).start()

        self.player_running = True

        print(
            f"[player] Ventana creada para '{scene.name}' "
            f"-> {screen['name']} ({screen['width']}x{screen['height']})"
        )

        player_window.after(
            50,
            lambda: self.player_loop(scene)
        )

        # Reafirma tamaño exacto de salida en pantalla asignada.
        player_window.update_idletasks()
        player_window.geometry(
            self.build_screen_geometry(screen)
        )

        player_window.lift()

    def player_render_worker(
        self,
        scene,
        player
    ):

        stop_event = player[
            "render_stop_event"
        ]

        width = int(
            player["screen_width"]
        )

        height = int(
            player["screen_height"]
        )

        render_scale = 1.0

        render_width = max(
            int(width * render_scale),
            1
        )

        render_height = max(
            int(height * render_scale),
            1
        )

        while (
            not stop_event.is_set()
            and player.get("running", False)
            and (self.execution_mode or scene == self.current_scene)
        ):

            started_at = time.perf_counter()

            try:

                output = self.render_scene(
                    render_width,
                    render_height,
                    scene,
                    playback=self.execution_mode,
                    show_screen_border=not self.execution_mode
                )

                if render_width != width or render_height != height:

                    output = cv2.resize(
                        output,
                        (
                            width,
                            height
                        ),
                        interpolation=cv2.INTER_LINEAR
                    )

                if (
                    stop_event.is_set()
                    or (
                        not self.execution_mode
                        and scene != self.current_scene
                    )
                ):
                    return

                player["latest_output"] = output
                player["latest_output_id"] += 1

            except Exception as e:

                print(
                    f"[player] Error renderizando '{scene.name}': {e}"
                )

                traceback.print_exc()

                if stop_event.wait(0.1):
                    return

            elapsed = time.perf_counter() - started_at
            target_fps = 30 if self.execution_mode else 12
            remaining = (1.0 / target_fps) - elapsed

            if remaining > 0 and stop_event.wait(remaining):
                return

    # =========================================================
    # LOOP DEL PLAYER
    # =========================================================

    def player_loop(
        self,
        scene
    ):

        if not self.player_running:
            return

        player = self.player_windows.get(
            scene
        )

        if player is None:
            return

        if not player.get(
            "running",
            False
        ):
            return

        player_window = player[
            "window"
        ]

        player_canvas = player[
            "canvas"
        ]

        try:

            frame_started_at = time.perf_counter()

            width = int(
                player.get(
                    "screen_width",
                    0
                )
            )

            height = int(
                player.get(
                    "screen_height",
                    0
                )
            )

            if width <= 1 or height <= 1:

                screen = self.get_screen(
                    scene.screen_index
                )

                width = int(screen["width"])
                height = int(screen["height"])

            output = player.get("latest_output")
            output_id = player.get("latest_output_id", 0)

            if (
                output is None
                or output_id == player.get("displayed_output_id")
            ):

                player_window.after(
                    16,
                    lambda: self.player_loop(scene)
                )

                return

            player["displayed_output_id"] = output_id

            output = cv2.cvtColor(
                output,
                cv2.COLOR_BGR2RGB
            )

            image = Image.fromarray(
                output
            )

            photo = ImageTk.PhotoImage(
                image
            )

            image_item = player.get(
                "image_item"
            )

            if image_item is None:

                image_item = player_canvas.create_image(
                    0,
                    0,
                    image=photo,
                    anchor="nw",
                    tags="player_image"
                )

                player["image_item"] = image_item

            else:

                player_canvas.itemconfig(
                    image_item,
                    image=photo
                )

            player_canvas.photo = photo

            elapsed_ms = int(
                (time.perf_counter() - frame_started_at) * 1000
            )

            next_delay = max(
                1,
                33 - elapsed_ms
            )

            player_window.after(
                next_delay,
                lambda: self.player_loop(scene)
            )

        except tk.TclError as e:

            window_alive = False

            try:
                window_alive = player_window.winfo_exists()
            except Exception:
                window_alive = False

            print(
                f"[player] TclError en '{scene.name}' "
                f"(ventana viva: {window_alive}): {e}"
            )

            if window_alive:

                player_window.after(
                    100,
                    lambda: self.player_loop(scene)
                )

                return

            self.player_windows.pop(
                scene,
                None
            )

            if self.execution_mode or scene == self.current_scene:

                self.play_scene(
                    scene
                )

        except Exception as e:

            print(
                f"[player] Error inesperado en '{scene.name}': {e}"
            )

            traceback.print_exc()

            player_window.after(
                100,
                lambda: self.player_loop(scene)
            )

    # =========================================================
    # CERRAR PLAYER
    # =========================================================

    def close_scene_player(
        self,
        scene
    ):

        player = self.player_windows.pop(
            scene,
            None
        )

        if not player:
            return

        player[
            "running"
        ] = False

        stop_event = player.get(
            "render_stop_event"
        )

        if stop_event is not None:
            stop_event.set()

        window = player.get(
            "window"
        )

        if window:

            try:

                window.destroy()

            except:
                pass

        self.player_running = bool(
            self.player_windows
        )

    def close_all_players(
        self,
        event=None
    ):

        for scene in list(
            self.player_windows.keys()
        ):

            self.close_scene_player(
                scene
            )

        self.player_running = False

    # =========================================================
    # CERRAR MEDIOS
    # =========================================================

    def close_all_media(self):

        for scene in self.scenes:

            for face in scene.faces:

                face.close_media()

    # =========================================================
    # ESCAPE
    # =========================================================

    def escape(
        self,
        event=None
    ):

        if self.execution_mode:

            self.exit_execution_mode()

        elif self.player_windows:

            self.close_all_players()

        else:

            self.root.destroy()


# =============================================================
# MAIN
# =============================================================

if __name__ == "__main__":

    configure_windows_dpi_awareness()

    root = tk.Tk()

    app = VideoMapper(
        root
    )

    root.mainloop()
