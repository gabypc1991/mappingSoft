import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import json
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
from PIL import Image, ImageTk


VIDEO_EXTENSIONS = (
    ".mp4",
    ".avi",
    ".mov",
    ".mkv",
    ".webm",
    ".m4v"
)

IMAGE_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".webp"
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
        rotation_degrees=0
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

        self.image = None

        self.video = None
        self.video_frame = None
        self.first_video_frame = None
        self.video_fps = 30.0
        self.video_frame_count = 0
        self.playback_started_at = None
        self.playback_frame_index = -1
        self.playback_frame = None
        self.playback_stop_event = None
        self.playback_thread = None

        self.photo = None

        self.cached_warp_key = None
        self.cached_warped = None
        self.cached_mask = None
        self.cached_roi = None

        self.is_video = False

        self.load_file()

    # ---------------------------------------------------------
    # ARCHIVO
    # ---------------------------------------------------------

    def load_file(self):

        self.close_video()

        self.image = None
        self.video_frame = None
        self.first_video_frame = None

        self.cached_warp_key = None
        self.cached_warped = None
        self.cached_mask = None
        self.cached_roi = None

        if not self.filename:
            return

        extension = os.path.splitext(
            self.filename
        )[1].lower()

        if extension in IMAGE_EXTENSIONS:

            self.is_video = False

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

        elif extension in VIDEO_EXTENSIONS:

            self.is_video = True

            try:

                self.video = cv2.VideoCapture(
                    self.filename
                )

                if not self.video.isOpened():

                    print(
                        "No se pudo abrir video:",
                        self.filename
                    )

                    self.video = None

                else:

                    self.video_fps = self.video.get(
                        cv2.CAP_PROP_FPS
                    )

                    if self.video_fps <= 0:
                        self.video_fps = 30.0

                    self.video_frame_count = int(
                        self.video.get(cv2.CAP_PROP_FRAME_COUNT)
                    )

                    self.read_video_frame()

                    if self.video_frame is not None:

                        self.first_video_frame = self.video_frame.copy()

            except Exception as e:

                print(
                    "Error cargando video:",
                    e
                )

    # ---------------------------------------------------------
    # VIDEO
    # ---------------------------------------------------------

    def read_video_frame(self):

        if self.video is None:
            return None

        ret, frame = self.video.read()

        if not ret:

            # Loop
            self.video.set(
                cv2.CAP_PROP_POS_FRAMES,
                0
            )

            ret, frame = self.video.read()

        if ret:

            self.video_frame = frame

            return frame

        return None

    def reset_playback(self):

        if not self.is_video or self.video is None:
            return

        self.video.set(
            cv2.CAP_PROP_POS_FRAMES,
            0
        )

        self.playback_started_at = time.perf_counter()
        self.playback_frame_index = -1

    def start_playback_worker(self):

        if not self.is_video or not self.filename:
            return

        self.stop_playback_worker()

        stop_event = threading.Event()
        self.playback_stop_event = stop_event
        self.playback_frame = self.first_video_frame

        self.playback_thread = threading.Thread(
            target=self.playback_worker,
            args=(stop_event,),
            daemon=True
        )

        self.playback_thread.start()

    def stop_playback_worker(self):

        if self.playback_stop_event is not None:
            self.playback_stop_event.set()

        self.playback_stop_event = None
        self.playback_thread = None
        self.playback_frame = None

    def playback_worker(
        self,
        stop_event
    ):

        capture = cv2.VideoCapture(
            self.filename
        )

        if not capture.isOpened():
            capture.release()
            return

        fps = capture.get(
            cv2.CAP_PROP_FPS
        )

        if fps <= 0:
            fps = self.video_fps or 30.0

        frame_count = int(
            capture.get(cv2.CAP_PROP_FRAME_COUNT)
        )

        started_at = time.perf_counter()
        frame_index = -1
        output_interval = 1.0 / min(
            fps,
            20.0
        )
        next_output_at = started_at

        try:

            while not stop_event.is_set():

                now = time.perf_counter()

                if now < next_output_at:

                    if stop_event.wait(next_output_at - now):
                        return

                    now = time.perf_counter()

                next_output_at = now + output_interval
                elapsed = now - started_at
                target_index = int(elapsed * fps)

                if frame_count > 0:
                    target_index %= frame_count

                if target_index < frame_index:

                    capture.set(
                        cv2.CAP_PROP_POS_FRAMES,
                        0
                    )

                    frame_index = -1

                if target_index == frame_index:
                    continue

                frames_behind = target_index - frame_index - 1
                max_sequential_skips = max(
                    12,
                    int(fps * 0.5)
                )

                if frames_behind > max_sequential_skips:

                    capture.set(
                        cv2.CAP_PROP_POS_FRAMES,
                        target_index
                    )

                    frame_index = target_index - 1

                while frame_index + 1 < target_index:

                    if stop_event.is_set():
                        return

                    if not capture.grab():

                        capture.set(
                            cv2.CAP_PROP_POS_FRAMES,
                            0
                        )

                        frame_index = -1
                        break

                    frame_index += 1

                ok, frame = capture.read()

                if not ok:

                    capture.set(
                        cv2.CAP_PROP_POS_FRAMES,
                        0
                    )

                    started_at = time.perf_counter()
                    frame_index = -1
                    continue

                frame_index = target_index

                if not stop_event.is_set():
                    self.playback_frame = frame

        finally:

            capture.release()

    def read_video_frame_synced(self):

        if self.video is None:
            return None

        if self.playback_started_at is None:
            self.reset_playback()

        elapsed = time.perf_counter() - self.playback_started_at
        target_index = int(elapsed * self.video_fps)

        if self.video_frame_count > 0:
            target_index %= self.video_frame_count

        if target_index == self.playback_frame_index:
            return self.video_frame

        if target_index < self.playback_frame_index:

            self.video.set(
                cv2.CAP_PROP_POS_FRAMES,
                0
            )

            self.playback_frame_index = -1

        frames_behind = (
            target_index - self.playback_frame_index - 1
        )

        max_sequential_skips = max(
            12,
            int(self.video_fps * 0.5)
        )

        if frames_behind > max_sequential_skips:

            self.video.set(
                cv2.CAP_PROP_POS_FRAMES,
                target_index
            )

            self.playback_frame_index = target_index - 1

        while self.playback_frame_index + 1 < target_index:

            if not self.video.grab():

                self.video.set(
                    cv2.CAP_PROP_POS_FRAMES,
                    0
                )

                self.playback_frame_index = -1

                break

            self.playback_frame_index += 1

        ret, frame = self.video.read()

        if not ret:

            self.reset_playback()

            ret, frame = self.video.read()

            target_index = 0

        if ret:

            self.video_frame = frame
            self.playback_frame_index = target_index

            return frame

        return None

    def get_first_video_frame(self):

        if not self.is_video or self.video is None:
            return None

        if self.first_video_frame is not None:
            return self.first_video_frame

        current_position = self.video.get(
            cv2.CAP_PROP_POS_FRAMES
        )

        self.video.set(
            cv2.CAP_PROP_POS_FRAMES,
            0
        )

        ret, frame = self.video.read()

        self.video.set(
            cv2.CAP_PROP_POS_FRAMES,
            current_position
        )

        if ret:

            self.first_video_frame = frame

            return frame

        return None

    def get_current_frame(
        self,
        playback=False
    ):

        if self.is_video:

            if playback:

                if self.playback_frame is not None:
                    return self.playback_frame

                return self.first_video_frame

            return self.get_first_video_frame()

        return self.image

    def close_video(self):

        self.stop_playback_worker()

        if self.video is not None:

            self.video.release()

        self.video = None
        self.video_frame = None
        self.first_video_frame = None
        self.playback_started_at = None
        self.playback_frame_index = -1

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
        space_height=None
    ):

        self.name = name
        self.screen_index = screen_index
        self.space_width = space_width
        self.space_height = space_height
        self.faces = []


class VideoMapper:

    def __init__(self, root):

        self.root = root

        self.root.title(
            "Video Mapper"
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

        # Actualización de videos del editor
        self.root.after(
            40,
            self.editor_video_loop
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
            text="Salir ejecución",
            command=self.exit_execution_mode
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
            text="Archivo",
            command=self.change_face_file
        ).pack(
            side="left",
            padx=4,
            pady=5
        )

        tk.Button(
            self.top,
            text="Reproducir",
            command=self.execute_scenes
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
            or extension in VIDEO_EXTENSIONS
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
        self.close_all_videos()

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

            face.close_video()

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

        self.normalize_scene_videos(
            scene
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

    def normalize_video_for_scene(
        self,
        source_path,
        scene
    ):

        if not source_path or scene is None:
            return source_path

        extension = os.path.splitext(
            source_path
        )[1].lower()

        if extension not in VIDEO_EXTENSIONS:
            return source_path

        _, max_height = self.get_target_scene_space(
            scene
        )

        capture = cv2.VideoCapture(
            source_path
        )

        if not capture.isOpened():
            capture.release()
            return source_path

        source_width = int(
            capture.get(cv2.CAP_PROP_FRAME_WIDTH)
        )
        source_height = int(
            capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
        )

        if (
            source_width <= 0
            or source_height <= 0
            or source_height <= max_height
        ):
            capture.release()
            return source_path

        scale = max_height / source_height
        target_width = max(
            int(round(source_width * scale)),
            2
        )
        target_width += target_width % 2
        target_height = max_height - (max_height % 2)

        fps = capture.get(
            cv2.CAP_PROP_FPS
        )

        if fps <= 0:
            fps = 30.0

        base_name = os.path.splitext(
            os.path.basename(source_path)
        )[0]

        normalized_path = os.path.join(
            self.current_assets_dir,
            f"{base_name}_h{target_height}.mp4"
        )

        if os.path.abspath(normalized_path) == os.path.abspath(source_path):
            normalized_path = os.path.join(
                self.current_assets_dir,
                f"{base_name}_scaled.mp4"
            )

        writer = cv2.VideoWriter(
            normalized_path,
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (
                target_width,
                target_height
            )
        )

        if not writer.isOpened():
            capture.release()
            writer.release()
            return source_path

        try:

            while True:

                ok, frame = capture.read()

                if not ok:
                    break

                resized = cv2.resize(
                    frame,
                    (
                        target_width,
                        target_height
                    ),
                    interpolation=cv2.INTER_AREA
                )

                writer.write(
                    resized
                )

        finally:

            capture.release()
            writer.release()

        if not os.path.isfile(normalized_path):
            return source_path

        print(
            f"Video optimizado: {source_width}x{source_height} -> "
            f"{target_width}x{target_height}"
        )

        return normalized_path

    def normalize_scene_videos(
        self,
        scene
    ):

        changed = False

        for face in scene.faces:

            normalized_path = self.normalize_video_for_scene(
                face.filename,
                scene
            )

            if normalized_path == face.filename:
                continue

            face.close_video()
            face.filename = normalized_path
            face.load_file()
            changed = True

        return changed

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

        return self.normalize_video_for_scene(
            target_path,
            scene
        )

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

        return self.normalize_video_for_scene(
            path,
            scene
        )

    def add_face(self):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        if not self.require_project_for_desktop_action():
            return

        if self.current_scene is None:
            return

        face = Face()

        offset = (
            len(
                self.current_scene.faces
            ) * 30
        )

        face.points = [
            [300 + offset, 200 + offset],
            [600 + offset, 200 + offset],
            [600 + offset, 500 + offset],
            [300 + offset, 500 + offset]
        ]

        self.current_scene.faces.append(
            face
        )

        self.selected_face = face

        if not self.change_face_file():

            self.current_scene.faces.remove(
                face
            )

            self.selected_face = None

        self.redraw()

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

        filename = filedialog.askopenfilename(
            title="Seleccionar imagen o video",
            filetypes=[
                (
                    "Imágenes y videos",
                    "*.png *.jpg *.jpeg *.bmp "
                    "*.webp *.mp4 *.avi *.mov "
                    "*.mkv *.webm *.m4v"
                ),
                (
                    "Imágenes",
                    "*.png *.jpg *.jpeg *.bmp *.webp"
                ),
                (
                    "Videos",
                    "*.mp4 *.avi *.mov *.mkv *.webm *.m4v"
                ),
                (
                    "Todos",
                    "*.*"
                )
            ]
        )

        if not filename:
            return False

        try:

            stored_path = self.save_source_file_to_assets(
                filename,
                self.current_scene
            )

        except Exception as e:

            messagebox.showerror(
                "Archivo",
                str(e)
            )

            return False

        face.filename = stored_path

        face.load_file()

        self.redraw()

        self.save_project(
            notify=False
        )

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

        face.close_video()

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

        if face.is_video:

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

    # =========================================================
    # CREAR IMAGEN DE LA ESCENA
    # =========================================================

    def render_scene(
        self,
        width,
        height,
        scene=None,
        playback=False
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

        sx = width / editor_width
        sy = height / editor_height

        for face in scene.faces:

            destination_points = np.float32([
                [
                    face.points[0][0] * sx,
                    face.points[0][1] * sy
                ],
                [
                    face.points[1][0] * sx,
                    face.points[1][1] * sy
                ],
                [
                    face.points[2][0] * sx,
                    face.points[2][1] * sy
                ],
                [
                    face.points[3][0] * sx,
                    face.points[3][1] * sy
                ]
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

            # Cachea caras estáticas para evitar recalcular perspectiva cada frame.
            can_cache = (
                (not face.is_video)
                or
                (face.is_video and not playback)
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
                face.is_video,
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

        scale_x = canvas_width / scene_width
        scale_y = canvas_height / scene_height

        return scale_x, scale_y, scene_width, scene_height

    def scene_to_canvas_point(
        self,
        x,
        y,
        scene=None
    ):

        scale_x, scale_y, _, _ = self.get_editor_transform(
            scene
        )

        return x * scale_x, y * scale_y

    def canvas_to_scene_point(
        self,
        x,
        y,
        scene=None
    ):

        scale_x, scale_y, scene_width, scene_height = self.get_editor_transform(
            scene
        )

        scene_x = int(round(x / scale_x))
        scene_y = int(round(y / scale_y))

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

                if face == self.selected_face:

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

    # =========================================================
    # ACTUALIZAR VIDEOS DEL EDITOR
    # =========================================================

    def editor_video_loop(self):

        self.root.after(
            40,
            self.editor_video_loop
        )

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
            label="Cambiar imagen o video",
            command=self.change_face_file
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

    # =========================================================
    # GEOMETRÍA
    # =========================================================

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

                    "rotation_degrees": face.rotation_degrees
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

        self.close_all_videos()

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

                media_path = self.normalize_video_for_scene(
                    media_path,
                    scene
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

        from flask import Response, jsonify, request, render_template

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
                    screen_index
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

                    face.close_video()

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

                self.normalize_scene_videos(
                    scene
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

        @app.route("/api/scenes/<int:index>/faces", methods=["POST"])
        def web_add_face(index):

            uploaded = request.files.get(
                "file"
            )

            if uploaded is None:

                return jsonify({
                    "ok": False,
                    "error": "Debes subir una imagen o video."
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

                face = Face()

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

                face.close_video()

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
                        "rotation_degrees": face.rotation_degrees
                    })

                scenes.append({
                    "name": scene.name,
                    "screen_index": scene.screen_index,
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

                face.start_playback_worker()

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

        self.show_edit_outputs()

    def stop_execution_workers(self):

        for scene in self.scenes:

            for face in scene.faces:

                face.stop_playback_worker()

        for player in self.player_windows.values():

            stop_event = player.get(
                "render_stop_event"
            )

            if stop_event is not None:
                stop_event.set()

    def show_edit_outputs(self):

        if not self.scenes:
            return

        for scene in self.scenes:

            if scene not in self.player_windows:

                self.play_scene(
                    scene
                )

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

        if self.execution_mode:

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

        video_count = sum(
            1
            for face in scene.faces
            if face.is_video
        )

        if video_count >= 3:
            render_scale = 0.5
        elif video_count == 2:
            render_scale = 0.75
        else:
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
            and self.execution_mode
            and player.get("running", False)
        ):

            started_at = time.perf_counter()

            try:

                output = self.render_scene(
                    render_width,
                    render_height,
                    scene,
                    playback=True
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

                if stop_event.is_set() or not self.execution_mode:
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
            remaining = (1.0 / 30.0) - elapsed

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

            if (
                not self.execution_mode
                and scene != self.current_scene
            ):

                output = np.zeros(
                    (
                        height,
                        width,
                        3
                    ),
                    dtype=np.uint8
                )

            elif self.execution_mode:

                output = player.get(
                    "latest_output"
                )

                output_id = player.get(
                    "latest_output_id",
                    0
                )

                if (
                    output is None
                    or output_id == player.get("displayed_output_id")
                ):

                    player_window.after(
                        5,
                        lambda: self.player_loop(scene)
                    )

                    return

                player["displayed_output_id"] = output_id

            else:

                # Serializado con web_lock: evita que el hilo del stream
                # web lea el mismo cv2.VideoCapture al mismo tiempo.
                with self.web_lock:

                    output = self.render_scene(
                        width,
                        height,
                        scene,
                        playback=self.execution_mode
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
    # CERRAR VIDEOS
    # =========================================================

    def close_all_videos(self):

        for scene in self.scenes:

            for face in scene.faces:

                face.close_video()

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
