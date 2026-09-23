import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import json
import os
import re
import subprocess
import sys
import threading
import time

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


class Face:

    def __init__(
        self,
        points=None,
        filename="",
        flip_x=False,
        flip_y=False
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

        self.image = None

        self.video = None
        self.video_frame = None

        self.photo = None

        self.is_video = False

        self.load_file()

    # ---------------------------------------------------------
    # ARCHIVO
    # ---------------------------------------------------------

    def load_file(self):

        self.close_video()

        self.image = None
        self.video_frame = None

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

                    self.read_video_frame()

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

    def get_current_frame(self):

        if self.is_video:

            return self.read_video_frame()

        return self.image

    def close_video(self):

        if self.video is not None:

            self.video.release()

        self.video = None
        self.video_frame = None


class Scene:

    def __init__(
        self,
        name="Escena 1",
        screen_index=0
    ):

        self.name = name
        self.screen_index = screen_index
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

        self.project_file = None

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

        self.web_control_active = False

        self.web_media_dir = os.path.join(
            os.getcwd(),
            "web_media"
        )

        os.makedirs(
            self.web_media_dir,
            exist_ok=True
        )

        self.build_ui()

        self.new_project()

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

    def new_project(self):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        self.close_all_players()

        self.close_all_videos()

        self.project_file = None

        self.project_name = "Proyecto"

        self.scenes = []

        self.add_scene()

    # =========================================================
    # ESCENAS
    # =========================================================

    def add_scene(self):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        scene_number = len(
            self.scenes
        ) + 1

        name = simpledialog.askstring(
            "Nueva escena",
            "Nombre de la escena:",
            initialvalue=f"Escena {scene_number}",
            parent=self.root
        )

        if not name:

            name = (
                f"Escena {scene_number}"
            )

        scene = Scene(name)

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

    def edit_selected_scene(self):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        scene = self.get_selected_scene()

        if scene is None:
            return

        self.current_scene = scene

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

        scene.screen_index = screen_index

        self.update_screen_combo_selection(
            scene
        )

        if scene == self.current_scene:

            self.update_scene_label()

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
                    f"{self.current_scene.name} -> "
                    f"{screen['name']}"
                )
            )

    # =========================================================
    # CARAS
    # =========================================================

    def add_face(self):

        if self.is_execution_mode():

            self.warn_execution_mode()

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

        self.change_face_file()

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
            return

        face.filename = filename

        face.load_file()

        self.redraw()

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

    def get_face_frame(self, face):

        if face.is_video:

            frame = face.get_current_frame()

        else:

            frame = face.image

        if frame is None:
            return None

        if face.flip_x and face.flip_y:

            return cv2.flip(
                frame,
                -1
            )

        if face.flip_x:

            return cv2.flip(
                frame,
                1
            )

        if face.flip_y:

            return cv2.flip(
                frame,
                0
            )

        return frame.copy()

    # =========================================================
    # CREAR IMAGEN DE LA ESCENA
    # =========================================================

    def render_scene(
        self,
        width,
        height,
        scene=None
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

        editor_width = self.canvas_width
        editor_height = self.canvas_height

        if editor_width <= 1:
            editor_width = width

        if editor_height <= 1:
            editor_height = height

        sx = width / editor_width
        sy = height / editor_height

        for face in scene.faces:

            frame = self.get_face_frame(
                face
            )

            if frame is None:
                continue

            h, w = frame.shape[:2]

            if w <= 0 or h <= 0:
                continue

            source_points = np.float32([
                [0, 0],
                [w - 1, 0],
                [w - 1, h - 1],
                [0, h - 1]
            ])

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

            matrix = cv2.getPerspectiveTransform(
                source_points,
                destination_points
            )

            warped = cv2.warpPerspective(
                frame,
                matrix,
                (
                    width,
                    height
                )
            )

            mask = np.zeros(
                (
                    height,
                    width
                ),
                dtype=np.uint8
            )

            polygon = np.int32(
                destination_points
            )

            cv2.fillConvexPoly(
                mask,
                polygon,
                255
            )

            output[
                mask == 255
            ] = warped[
                mask == 255
            ]

        return output

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

        output = self.render_scene(
            self.canvas_width,
            self.canvas_height
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

                    points.extend([
                        x,
                        y
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

                        radius = 9

                        self.canvas.create_oval(
                            x - radius,
                            y - radius,
                            x + radius,
                            y + radius,
                            fill="red",
                            outline="white",
                            width=2,
                            tags="corner"
                        )

    # =========================================================
    # ACTUALIZAR VIDEOS DEL EDITOR
    # =========================================================

    def editor_video_loop(self):

        if self.editor_running:

            has_video = False

            if self.current_scene:

                for face in self.current_scene.faces:

                    if face.is_video:

                        has_video = True

            if has_video:

                self.redraw()

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

        for face in reversed(
            self.current_scene.faces
        ):

            if self.point_in_polygon(
                x,
                y,
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

                distance = (
                    (event.x - x) ** 2 +
                    (event.y - y) ** 2
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

        self.selected_face.points[
            self.selected_corner
        ] = [
            event.x,
            event.y
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

    # =========================================================
    # GUARDAR
    # =========================================================

    def save_project(self):

        if not self.project_file:

            filename = filedialog.asksaveasfilename(
                title="Guardar proyecto",
                defaultextension=".json",
                filetypes=[
                    (
                        "VideoMapper",
                        "*.json"
                    )
                ]
            )

            if not filename:
                return

            self.project_file = filename

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
                "faces": []
            }

            for face in scene.faces:

                scene_data[
                    "faces"
                ].append({

                    "points": face.points,

                    "file": face.filename,

                    "flip_x": face.flip_x,

                    "flip_y": face.flip_y
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

    def open_project(self):

        if self.is_execution_mode():

            self.warn_execution_mode()

            return

        filename = filedialog.askopenfilename(
            title="Abrir proyecto",
            filetypes=[
                (
                    "VideoMapper",
                    "*.json"
                )
            ]
        )

        if not filename:
            return

        try:

            self.close_all_players()

            self.close_all_videos()

            with open(
                filename,
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)

            self.project_file = filename

            self.project_name = data.get(
                "name",
                "Proyecto"
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
                    )
                )

                for face_data in scene_data.get(
                    "faces",
                    []
                ):

                    face = Face(
                        points=face_data.get(
                            "points"
                        ),
                        filename=face_data.get(
                            "file",
                            ""
                        ),
                        flip_x=face_data.get(
                            "flip_x",
                            False
                        ),
                        flip_y=face_data.get(
                            "flip_y",
                            False
                        )
                    )

                    scene.faces.append(
                        face
                    )

                self.scenes.append(
                    scene
                )

            if self.scenes:

                self.current_scene = (
                    self.scenes[0]
                )

            else:

                self.add_scene()

            self.selected_face = None

            self.update_scene_combo()

            self.update_scene_label()

            self.redraw()

        except Exception as e:

            messagebox.showerror(
                "Error",
                str(e)
            )

    # =========================================================
    # SERVIDOR WEB
    # =========================================================

    def start_web_server(self):

        if self.web_thread and self.web_thread.is_alive():

            messagebox.showinfo(
                "Web",
                f"Editor web activo en http://127.0.0.1:{self.web_port}"
            )

            return

        try:

            from flask import Flask

            app = Flask(
                __name__
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

            messagebox.showinfo(
                "Web",
                (
                    "Editor web activo.\n"
                    f"Local: http://127.0.0.1:{self.web_port}\n"
                    f"Red: http://<IP-de-esta-PC>:{self.web_port}"
                )
            )

        except ImportError:

            messagebox.showerror(
                "Web",
                "Flask no está instalado. Instalalo con: pip install flask"
            )

        except Exception as e:

            messagebox.showerror(
                "Web",
                str(e)
            )

    def configure_web_routes(
        self,
        app
    ):

        from flask import Response, jsonify, request

        @app.route("/")
        def web_index():

            return self.get_web_editor_html()

        @app.route("/api/state")
        def web_state():

            return jsonify(
                self.get_web_state()
            )

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

                scene = Scene(
                    name,
                    screen_index
                )

                self.scenes.append(
                    scene
                )

                self.current_scene = scene

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

                scene.screen_index = int(
                    data.get(
                        "screen_index",
                        0
                    )
                )

            self.schedule_ui_refresh()

            return jsonify(
                self.get_web_state()
            )

        @app.route("/api/scenes/<int:index>/faces", methods=["POST"])
        def web_add_face(index):

            with self.web_lock:

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

            filename = self.safe_upload_filename(
                uploaded.filename
            )

            path = os.path.join(
                self.web_media_dir,
                filename
            )

            uploaded.save(
                path
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

                face.filename = path
                face.load_file()

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

            for scene in self.scenes:

                faces = []

                for face in scene.faces:

                    faces.append({
                        "points": face.points,
                        "file": os.path.basename(
                            face.filename
                        ),
                        "flip_x": face.flip_x,
                        "flip_y": face.flip_y
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
                "canvas_width": self.canvas_width,
                "canvas_height": self.canvas_height
            }

    def web_stream_frames(self):

        while True:

            try:

                width = max(
                    self.canvas_width,
                    640
                )

                height = max(
                    self.canvas_height,
                    360
                )

                with self.web_lock:

                    frame = self.render_scene(
                        width,
                        height,
                        self.current_scene
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

        self.root.withdraw()

        self.close_all_players()

        if self.current_scene:

            self.play_scene(
                self.current_scene
            )

    def release_web_control(self):

        self.web_control_active = False

        self.execution_mode = False

        self.close_all_players()

        self.root.deiconify()
        self.root.lift()

    def get_web_editor_html(self):

        return r"""
<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Video Mapper Web</title>
<style>
body{margin:0;background:#111;color:#eee;font-family:Arial,sans-serif}
#bar{display:flex;gap:8px;align-items:center;padding:8px;background:#202020;flex-wrap:wrap}
button,select,input{font:inherit}
button{padding:5px 9px}
#stage{position:relative;width:100vw;height:calc(100vh - 52px);overflow:hidden;background:#000}
#stream{position:absolute;inset:0;width:100%;height:100%;object-fit:contain}
#overlay{position:absolute;inset:0;width:100%;height:100%}
#menu{position:fixed;display:none;background:#282828;border:1px solid #555;z-index:10;min-width:190px}
#menu button{display:block;width:100%;background:transparent;color:#eee;border:0;text-align:left;padding:8px}
#menu button:hover{background:#444}
</style>
</head>
<body>
<div id="bar">
  <button onclick="newScene()">+ Escena</button>
  <select id="sceneSelect" onchange="selectScene()"></select>
  <button onclick="deleteScene()">Eliminar</button>
  <select id="screenSelect" onchange="assignScreen()"></select>
  <button onclick="addFace()">+ Cara</button>
  <button onclick="executeAll()">Ejecutar</button>
  <button onclick="exitExecution()">Salir ejecución</button>
  <button onclick="takeControl()">Tomar control</button>
  <button onclick="releaseControl()">Soltar control</button>
  <span id="status"></span>
</div>
<div id="stage">
  <img id="stream" src="/stream/editor">
  <canvas id="overlay"></canvas>
</div>
<div id="menu">
  <button onclick="pickFile()">Cambiar imagen o video</button>
  <button onclick="flipFace('x')">Invertir en X</button>
  <button onclick="flipFace('y')">Invertir en Y</button>
  <button onclick="deleteFace()">Eliminar cara</button>
</div>
<input id="fileInput" type="file" accept="image/*,video/*" hidden onchange="uploadFile()">
<script>
let state=null, selectedFace=-1, dragging=-1, menuFace=-1;
const canvas=document.getElementById('overlay');
const ctx=canvas.getContext('2d');
const menu=document.getElementById('menu');
function api(url, opts={}){return fetch(url, opts).then(r=>r.json());}
async function loadState(){state=await api('/api/state'); syncControls(); draw();}
function currentScene(){return state.scenes[state.current_scene_index]||null;}
function syncControls(){
  const scenes=document.getElementById('sceneSelect');
  scenes.innerHTML='';
  state.scenes.forEach((s,i)=>scenes.add(new Option((i+1)+' - '+s.name,i)));
  scenes.value=state.current_scene_index;
  const screens=document.getElementById('screenSelect');
  screens.innerHTML='';
  state.screens.forEach((s,i)=>screens.add(new Option(s.name,i)));
  const scene=currentScene();
  if(scene) screens.value=scene.screen_index;
  document.getElementById('status').textContent=
    state.execution_mode?'Ejecución':(state.web_control_active?'Control web':'Edición');
}
function fit(){
  canvas.width=canvas.clientWidth; canvas.height=canvas.clientHeight;
}
function scaleInfo(){
  const w=state.canvas_width||1280,h=state.canvas_height||720;
  const s=Math.min(canvas.width/w, canvas.height/h);
  const ox=(canvas.width-w*s)/2, oy=(canvas.height-h*s)/2;
  return {s,ox,oy,w,h};
}
function toScreen(p){const f=scaleInfo(); return [f.ox+p[0]*f.s,f.oy+p[1]*f.s];}
function toWorld(x,y){const f=scaleInfo(); return [Math.round((x-f.ox)/f.s),Math.round((y-f.oy)/f.s)];}
function draw(){
  fit(); ctx.clearRect(0,0,canvas.width,canvas.height);
  const scene=currentScene(); if(!scene)return;
  scene.faces.forEach((face,i)=>{
    ctx.beginPath();
    face.points.forEach((p,j)=>{const q=toScreen(p); j?ctx.lineTo(q[0],q[1]):ctx.moveTo(q[0],q[1]);});
    ctx.closePath(); ctx.strokeStyle=i===selectedFace?'yellow':'cyan'; ctx.lineWidth=2; ctx.stroke();
    if(i===selectedFace){face.points.forEach(p=>{const q=toScreen(p);ctx.beginPath();ctx.arc(q[0],q[1],8,0,Math.PI*2);ctx.fillStyle='red';ctx.fill();ctx.strokeStyle='white';ctx.stroke();});}
  });
}
function faceAt(x,y){
  const scene=currentScene(); if(!scene)return -1;
  for(let i=scene.faces.length-1;i>=0;i--){
    const pts=scene.faces[i].points.map(toScreen);
    let inside=false,j=pts.length-1;
    for(let k=0;k<pts.length;k++){const xi=pts[k][0],yi=pts[k][1],xj=pts[j][0],yj=pts[j][1];
      if(((yi>y)!=(yj>y))&&(x<(xj-xi)*(y-yi)/(yj-yi+0.00001)+xi))inside=!inside; j=k;}
    if(inside)return i;
  }
  return -1;
}
canvas.addEventListener('mousedown',e=>{
  menu.style.display='none'; if(state.execution_mode)return;
  const scene=currentScene(); if(!scene)return;
  const rect=canvas.getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top;
  if(selectedFace>=0){const face=scene.faces[selectedFace];
    for(let i=0;i<4;i++){const q=toScreen(face.points[i]); if(Math.hypot(x-q[0],y-q[1])<18){dragging=i;return;}}}
  selectedFace=faceAt(x,y); draw();
});
canvas.addEventListener('mousemove',e=>{
  if(dragging<0||selectedFace<0||state.execution_mode)return;
  const rect=canvas.getBoundingClientRect(),p=toWorld(e.clientX-rect.left,e.clientY-rect.top);
  currentScene().faces[selectedFace].points[dragging]=p; draw();
});
canvas.addEventListener('mouseup',async()=>{
  if(dragging<0||selectedFace<0)return; dragging=-1;
  await api(`/api/scenes/${state.current_scene_index}/faces/${selectedFace}/points`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({points:currentScene().faces[selectedFace].points})});
});
canvas.addEventListener('contextmenu',e=>{
  e.preventDefault(); if(state.execution_mode)return;
  const rect=canvas.getBoundingClientRect(); menuFace=faceAt(e.clientX-rect.left,e.clientY-rect.top);
  if(menuFace<0)return; selectedFace=menuFace; draw();
  menu.style.left=e.clientX+'px'; menu.style.top=e.clientY+'px'; menu.style.display='block';
});
async function selectScene(){await api(`/api/scenes/${document.getElementById('sceneSelect').value}/select`,{method:'POST'}); selectedFace=-1; await loadState();}
async function newScene(){const name=prompt('Nombre de escena','Escena '+(state.scenes.length+1)); if(!name)return; await api('/api/scenes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})}); await loadState();}
async function deleteScene(){if(!confirm('¿Eliminar escena?'))return; await api(`/api/scenes/${state.current_scene_index}`,{method:'DELETE'}); selectedFace=-1; await loadState();}
async function assignScreen(){await api(`/api/scenes/${state.current_scene_index}/screen`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({screen_index:+document.getElementById('screenSelect').value})}); await loadState();}
async function addFace(){await api(`/api/scenes/${state.current_scene_index}/faces`,{method:'POST'}); await loadState();}
async function deleteFace(){if(menuFace<0||!confirm('¿Eliminar cara?'))return; await api(`/api/scenes/${state.current_scene_index}/faces/${menuFace}`,{method:'DELETE'}); menu.style.display='none'; selectedFace=-1; await loadState();}
async function flipFace(axis){if(menuFace<0)return; await api(`/api/scenes/${state.current_scene_index}/faces/${menuFace}/flip`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({axis})}); menu.style.display='none'; await loadState();}
function pickFile(){document.getElementById('fileInput').click();}
async function uploadFile(){const f=document.getElementById('fileInput').files[0]; if(!f||menuFace<0)return; const fd=new FormData(); fd.append('file',f); await fetch(`/api/scenes/${state.current_scene_index}/faces/${menuFace}/file`,{method:'POST',body:fd}); menu.style.display='none'; await loadState();}
async function takeControl(){await api('/api/control/take',{method:'POST'}); setTimeout(loadState,300);}
async function releaseControl(){await api('/api/control/release',{method:'POST'}); setTimeout(loadState,300);}
async function executeAll(){await api('/api/control/execute',{method:'POST'}); setTimeout(loadState,300);}
async function exitExecution(){await api('/api/control/exit',{method:'POST'}); setTimeout(loadState,300);}
window.addEventListener('resize',draw);
setInterval(loadState,1500);
loadState();
</script>
</body>
</html>
"""

    # =========================================================
    # REPRODUCCIÓN
    # =========================================================

    def execute_scenes(self):

        if not self.scenes:
            return

        if not self.validate_scene_outputs():
            return

        self.execution_mode = True

        self.dragging = False
        self.selected_corner = None

        self.close_all_players()

        for scene in self.scenes:

            self.play_scene(
                scene
            )

    def exit_execution_mode(self):

        self.execution_mode = False

        self.dragging = False
        self.selected_corner = None

        self.show_edit_outputs()

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
            "running": True
        }

        self.player_running = True

        player_window.after(
            50,
            lambda: self.player_loop(scene)
        )

        player_window.lift()

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

            width = (
                player_canvas.winfo_width()
            )

            height = (
                player_canvas.winfo_height()
            )

            if width <= 1:

                screen = self.get_screen(
                    scene.screen_index
                )

                width = screen["width"]

            if height <= 1:

                screen = self.get_screen(
                    scene.screen_index
                )

                height = screen["height"]

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

            else:

                output = self.render_scene(
                    width,
                    height,
                    scene
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

            player_canvas.delete(
                "player_image"
            )

            player_canvas.create_image(
                0,
                0,
                image=photo,
                anchor="nw",
                tags="player_image"
            )

            player_canvas.photo = photo

            player_window.after(
                33,
                lambda: self.player_loop(scene)
            )

        except tk.TclError:

            self.player_windows.pop(
                scene,
                None
            )

        except Exception as e:

            print(
                "Error player:",
                e
            )

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

    root = tk.Tk()

    app = VideoMapper(
        root
    )

    root.mainloop()
