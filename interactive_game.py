import math
import os
import random
import sys
import threading
import time

import cv2
import numpy as np
from PIL import Image, ImageSequence


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


class MediaAsset:

    def __init__(self, filename=""):
        self.filename = filename
        self.image = None
        self.frames = []
        self.durations = []
        self.total_duration_ms = 0
        self.is_animated = False
        self.playback_started_at = None
        self.load_file(filename)

    def load_file(self, filename=None):

        if filename is not None:
            self.filename = filename

        self.image = None
        self.frames = []
        self.durations = []
        self.total_duration_ms = 0
        self.is_animated = False
        self.playback_started_at = None

        if not self.filename:
            return

        extension = os.path.splitext(self.filename)[1].lower()

        if extension in ANIMATED_IMAGE_EXTENSIONS:
            self.is_animated = True
            try:
                with Image.open(self.filename) as image:
                    for gif_frame in ImageSequence.Iterator(image):
                        rgba_frame = gif_frame.convert("RGBA")
                        background = Image.new(
                            "RGBA",
                            rgba_frame.size,
                            (0, 0, 0, 0)
                        )
                        background.alpha_composite(rgba_frame)
                        frame = cv2.cvtColor(
                            np.array(background),
                            cv2.COLOR_RGBA2BGRA
                        )
                        duration = max(int(gif_frame.info.get("duration", 100)), 20)
                        self.frames.append(frame)
                        self.durations.append(duration)
            except Exception:
                self.frames = []
                self.durations = []
                self.is_animated = False

            if self.frames:
                self.image = self.frames[0]
                self.total_duration_ms = sum(self.durations)
        elif extension in IMAGE_EXTENSIONS:
            image = cv2.imread(self.filename, cv2.IMREAD_UNCHANGED)
            if image is not None:
                if len(image.shape) == 2:
                    image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGRA)
                elif image.shape[2] == 3:
                    image = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
                self.image = image

    def get_current_frame(self, playback=False):

        if not self.is_animated:
            return self.image

        if not self.frames:
            return self.image

        if not playback:
            return self.frames[0]

        if self.playback_started_at is None:
            self.playback_started_at = time.perf_counter()

        elapsed_ms = int((time.perf_counter() - self.playback_started_at) * 1000)

        if self.total_duration_ms <= 0:
            return self.frames[0]

        elapsed_ms = elapsed_ms % self.total_duration_ms
        current_ms = 0

        for frame, duration in zip(self.frames, self.durations):
            current_ms += duration
            if elapsed_ms < current_ms:
                return frame

        return self.frames[-1]


class GameConfig:

    def __init__(self, points=None):
        self.points = points or [
            [240, 140],
            [920, 140],
            [920, 580],
            [240, 580]
        ]
        self.background_file = ""
        self.butterfly_file = ""
        self.min_butterfly_size = 80
        self.max_butterfly_size = 180
        self.butterfly_orientation_degrees = 0
        self.min_butterfly_count = 3
        self.max_butterfly_count = 8
        self.min_flee_speed = 80.0
        self.max_flee_speed = 200.0
        self.catch_radius = 42.0
        self.reaction_radius = 170.0
        self.safe_spawn_radius = 130.0
        self.edge_margin = 18.0
        self.camera_index = 0
        self.aruco_layout = {
            "0": [0.08, 0.08],
            "1": [0.92, 0.08],
            "2": [0.08, 0.92]
        }

    def to_dict(self):
        return {
            "points": self.points,
            "background_file": self.background_file,
            "butterfly_file": self.butterfly_file,
            "min_butterfly_size": self.min_butterfly_size,
            "max_butterfly_size": self.max_butterfly_size,
            "butterfly_orientation_degrees": self.butterfly_orientation_degrees,
            "min_butterfly_count": self.min_butterfly_count,
            "max_butterfly_count": self.max_butterfly_count,
            "min_flee_speed": self.min_flee_speed,
            "max_flee_speed": self.max_flee_speed,
            "catch_radius": self.catch_radius,
            "reaction_radius": self.reaction_radius,
            "safe_spawn_radius": self.safe_spawn_radius,
            "edge_margin": self.edge_margin,
            "camera_index": self.camera_index,
            "aruco_layout": self.aruco_layout
        }

    @classmethod
    def from_dict(cls, data):
        config = cls(points=data.get("points"))
        config.background_file = data.get("background_file", "")
        config.butterfly_file = data.get("butterfly_file", "")
        config.min_butterfly_size = int(data.get("min_butterfly_size", 80))
        config.max_butterfly_size = int(data.get("max_butterfly_size", 180))
        config.butterfly_orientation_degrees = float(
            data.get("butterfly_orientation_degrees", 0)
        )
        config.min_butterfly_count = int(data.get("min_butterfly_count", 3))
        config.max_butterfly_count = int(data.get("max_butterfly_count", 8))
        config.min_flee_speed = float(data.get("min_flee_speed", 80.0))
        config.max_flee_speed = float(data.get("max_flee_speed", 200.0))
        config.catch_radius = float(data.get("catch_radius", 42.0))
        config.reaction_radius = float(data.get("reaction_radius", 170.0))
        config.safe_spawn_radius = float(data.get("safe_spawn_radius", 130.0))
        config.edge_margin = float(data.get("edge_margin", 18.0))
        config.camera_index = int(data.get("camera_index", 0))
        config.aruco_layout = data.get("aruco_layout", config.aruco_layout)
        config.sanitize()
        return config

    def sanitize(self):

        self.min_butterfly_size = max(10, int(self.min_butterfly_size))
        self.max_butterfly_size = max(self.min_butterfly_size, int(self.max_butterfly_size))
        self.min_butterfly_count = max(1, int(self.min_butterfly_count))
        self.max_butterfly_count = max(self.min_butterfly_count, int(self.max_butterfly_count))
        self.min_flee_speed = max(5.0, float(self.min_flee_speed))
        self.max_flee_speed = max(self.min_flee_speed, float(self.max_flee_speed))
        self.catch_radius = max(8.0, float(self.catch_radius))
        self.reaction_radius = max(self.catch_radius + 10.0, float(self.reaction_radius))
        self.safe_spawn_radius = max(self.catch_radius, float(self.safe_spawn_radius))
        self.edge_margin = max(0.0, float(self.edge_margin))


class Butterfly:

    def __init__(self, x, y, size, speed):
        self.x = float(x)
        self.y = float(y)
        self.vx = 0.0
        self.vy = 0.0
        self.heading = random.uniform(0, math.tau)
        self.speed = float(speed)
        self.size = float(size)
        self.state = "FLYING"
        self.wander_timer = random.uniform(0.2, 1.3)


class GameEngine:

    def __init__(self):
        self.config = None
        self.width = 0.0
        self.height = 0.0
        self.butterflies = []
        self.background_asset = MediaAsset()
        self.butterfly_asset = MediaAsset()
        self.last_update_time = None
        self.last_known_baby = None
        self.last_detected_at = 0.0
        self.random = random.Random()

    def configure(self, config, width, height):

        self.config = config
        self.width = max(float(width), 2.0)
        self.height = max(float(height), 2.0)
        self.config.sanitize()

        if self.background_asset.filename != self.config.background_file:
            self.background_asset.load_file(self.config.background_file)

        if self.butterfly_asset.filename != self.config.butterfly_file:
            self.butterfly_asset.load_file(self.config.butterfly_file)

        target_count = self.random.randint(
            self.config.min_butterfly_count,
            self.config.max_butterfly_count
        )

        while len(self.butterflies) > target_count:
            self.butterflies.pop()

        while len(self.butterflies) < target_count:
            butterfly = self.spawn_butterfly(avoid_point=self.last_known_baby)
            if butterfly is None:
                break
            self.butterflies.append(butterfly)

        if self.last_update_time is None:
            self.last_update_time = time.perf_counter()

    def spawn_butterfly(self, avoid_point=None):

        if self.config is None:
            return None

        for _ in range(60):
            size = self.random.uniform(
                self.config.min_butterfly_size,
                self.config.max_butterfly_size
            )
            margin = (size * 0.5) + self.config.edge_margin
            if margin * 2 >= self.width or margin * 2 >= self.height:
                margin = min(self.width, self.height) * 0.2
            x = self.random.uniform(margin, self.width - margin)
            y = self.random.uniform(margin, self.height - margin)

            too_close = False
            if avoid_point is not None:
                distance = math.hypot(x - avoid_point[0], y - avoid_point[1])
                if distance < self.config.safe_spawn_radius:
                    too_close = True

            if not too_close:
                for other in self.butterflies:
                    if math.hypot(x - other.x, y - other.y) < (size + other.size) * 0.45:
                        too_close = True
                        break

            if too_close:
                continue

            speed = self.random.uniform(
                self.config.min_flee_speed,
                self.config.max_flee_speed
            )

            return Butterfly(x=x, y=y, size=size, speed=speed)

        return None

    def update(self, baby_position):

        if self.config is None:
            return

        now = time.perf_counter()

        if self.last_update_time is None:
            self.last_update_time = now

        dt = max(min(now - self.last_update_time, 0.09), 1.0 / 120.0)
        self.last_update_time = now

        if baby_position is not None:
            self.last_known_baby = baby_position
            self.last_detected_at = now
        elif now - self.last_detected_at > 0.8:
            self.last_known_baby = None

        baby = self.last_known_baby

        removed = 0
        for butterfly in list(self.butterflies):
            self._update_butterfly(butterfly, dt, baby)

            if baby is not None:
                if math.hypot(butterfly.x - baby[0], butterfly.y - baby[1]) < self.config.catch_radius:
                    butterfly.state = "CAUGHT"

            if butterfly.state == "CAUGHT":
                self.butterflies.remove(butterfly)
                removed += 1

        while removed > 0:
            new_butterfly = self.spawn_butterfly(avoid_point=baby)
            if new_butterfly is not None:
                self.butterflies.append(new_butterfly)
            removed -= 1

        target_count = self.random.randint(
            self.config.min_butterfly_count,
            self.config.max_butterfly_count
        )
        while len(self.butterflies) < target_count:
            new_butterfly = self.spawn_butterfly(avoid_point=baby)
            if new_butterfly is None:
                break
            self.butterflies.append(new_butterfly)

    def _update_butterfly(self, butterfly, dt, baby):

        if self.config is None:
            return

        if baby is None:
            butterfly.state = "FLYING"
        else:
            distance = math.hypot(butterfly.x - baby[0], butterfly.y - baby[1])
            if distance < self.config.catch_radius:
                butterfly.state = "CAUGHT"
            elif distance < self.config.reaction_radius:
                butterfly.state = "FLEEING"
            elif distance < self.config.reaction_radius * 1.45:
                butterfly.state = "ALERT"
            else:
                butterfly.state = "FLYING"

        if butterfly.state == "FLEEING" and baby is not None:
            direction_x = butterfly.x - baby[0]
            direction_y = butterfly.y - baby[1]
            norm = math.hypot(direction_x, direction_y) + 1e-6
            direction_x /= norm
            direction_y /= norm
            panic = max(0.0, 1.0 - (norm / self.config.reaction_radius))
            speed = self.config.min_flee_speed + (
                self.config.max_flee_speed - self.config.min_flee_speed
            ) * panic
            butterfly.vx = direction_x * speed
            butterfly.vy = direction_y * speed
            butterfly.heading = math.atan2(butterfly.vy, butterfly.vx)
        else:
            butterfly.wander_timer -= dt
            if butterfly.wander_timer <= 0:
                butterfly.wander_timer = self.random.uniform(0.5, 1.8)
                jitter = self.random.uniform(-0.8, 0.8)
                butterfly.heading += jitter
            cruise_speed = max(self.config.min_flee_speed * 0.35, 18.0)
            butterfly.vx = math.cos(butterfly.heading) * cruise_speed
            butterfly.vy = math.sin(butterfly.heading) * cruise_speed

            if butterfly.state == "ALERT" and baby is not None:
                to_baby_x = baby[0] - butterfly.x
                to_baby_y = baby[1] - butterfly.y
                norm = math.hypot(to_baby_x, to_baby_y) + 1e-6
                to_baby_x /= norm
                to_baby_y /= norm
                butterfly.vx = butterfly.vx * 0.65 + to_baby_x * cruise_speed * 0.7
                butterfly.vy = butterfly.vy * 0.65 + to_baby_y * cruise_speed * 0.7
                butterfly.heading = math.atan2(butterfly.vy, butterfly.vx)

        butterfly.x += butterfly.vx * dt
        butterfly.y += butterfly.vy * dt

        margin = self.config.edge_margin + butterfly.size * 0.5
        min_x = margin
        min_y = margin
        max_x = self.width - margin
        max_y = self.height - margin

        if butterfly.x < min_x:
            butterfly.x = min_x
            butterfly.vx = abs(butterfly.vx)
            butterfly.heading = math.atan2(butterfly.vy, butterfly.vx)

        if butterfly.x > max_x:
            butterfly.x = max_x
            butterfly.vx = -abs(butterfly.vx)
            butterfly.heading = math.atan2(butterfly.vy, butterfly.vx)

        if butterfly.y < min_y:
            butterfly.y = min_y
            butterfly.vy = abs(butterfly.vy)
            butterfly.heading = math.atan2(butterfly.vy, butterfly.vx)

        if butterfly.y > max_y:
            butterfly.y = max_y
            butterfly.vy = -abs(butterfly.vy)
            butterfly.heading = math.atan2(butterfly.vy, butterfly.vx)

    def render(self, playback=False):

        if self.config is None:
            return None

        width = int(max(self.width, 2))
        height = int(max(self.height, 2))
        output = np.zeros((height, width, 3), dtype=np.uint8)

        background = self.background_asset.get_current_frame(playback=playback)
        if background is not None:
            resized_background = cv2.resize(
                background,
                (width, height),
                interpolation=cv2.INTER_LINEAR
            )
            if resized_background.shape[2] == 4:
                alpha = resized_background[:, :, 3:4].astype(np.float32) / 255.0
                rgb = resized_background[:, :, :3]
                output = (rgb * alpha + output * (1.0 - alpha)).astype(np.uint8)
            else:
                output = resized_background[:, :, :3]

        butterfly_frame = self.butterfly_asset.get_current_frame(playback=playback)

        if butterfly_frame is None:
            for butterfly in self.butterflies:
                center = (int(round(butterfly.x)), int(round(butterfly.y)))
                radius = int(max(6, round(butterfly.size * 0.18)))
                cv2.circle(output, center, radius, (255, 180, 64), -1)
                cv2.circle(output, center, max(1, radius // 3), (255, 255, 255), -1)
            return output

        for butterfly in self.butterflies:
            sprite = self._build_butterfly_sprite(butterfly_frame, butterfly)
            self._blit_rgba(output, sprite, int(round(butterfly.x)), int(round(butterfly.y)))

        return output

    def _build_butterfly_sprite(self, source, butterfly):

        side = max(int(round(butterfly.size)), 8)
        sprite = cv2.resize(source, (side, side), interpolation=cv2.INTER_LINEAR)
        rotation = butterfly.heading + math.radians(self.config.butterfly_orientation_degrees)
        rotation_degrees = -math.degrees(rotation)
        matrix = cv2.getRotationMatrix2D((side / 2, side / 2), rotation_degrees, 1.0)
        rotated = cv2.warpAffine(
            sprite,
            matrix,
            (side, side),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(0, 0, 0, 0)
        )

        if len(rotated.shape) == 2:
            rotated = cv2.cvtColor(rotated, cv2.COLOR_GRAY2BGRA)
        elif rotated.shape[2] == 3:
            rotated = cv2.cvtColor(rotated, cv2.COLOR_BGR2BGRA)

        return rotated

    def _blit_rgba(self, output, sprite, center_x, center_y):

        if sprite is None:
            return

        height, width = output.shape[:2]
        sprite_h, sprite_w = sprite.shape[:2]
        x0 = center_x - sprite_w // 2
        y0 = center_y - sprite_h // 2
        x1 = x0 + sprite_w
        y1 = y0 + sprite_h

        clip_x0 = max(0, x0)
        clip_y0 = max(0, y0)
        clip_x1 = min(width, x1)
        clip_y1 = min(height, y1)

        if clip_x0 >= clip_x1 or clip_y0 >= clip_y1:
            return

        local_x0 = clip_x0 - x0
        local_y0 = clip_y0 - y0
        local_x1 = local_x0 + (clip_x1 - clip_x0)
        local_y1 = local_y0 + (clip_y1 - clip_y0)

        sprite_roi = sprite[local_y0:local_y1, local_x0:local_x1]
        output_roi = output[clip_y0:clip_y1, clip_x0:clip_x1]

        alpha = sprite_roi[:, :, 3:4].astype(np.float32) / 255.0
        rgb = sprite_roi[:, :, :3]
        output_roi[:] = (rgb * alpha + output_roi * (1.0 - alpha)).astype(np.uint8)


class VisionBackend:

    def __init__(self, project_root):
        self.project_root = project_root
        self.model_path = os.path.join(
            project_root,
            "vision",
            "models",
            "baby_detector.pt"
        )
        self.camera_index = 0
        self.capture = None
        self.running = False
        self.thread = None
        self.lock = threading.RLock()
        self.latest_state = {
            "baby_detected": False,
            "baby_position": None,
            "confidence": 0.0,
            "timestamp": 0.0,
            "calibration_valid": False,
            "aruco_centers": {},
            "fps": 0.0,
            "inference_ms": 0.0,
            "model_name": "none",
            "running": False,
            "camera_index": 0,
            "camera_error": ""
        }
        self.latest_debug_frame = None
        self.homography = None
        self.aruco_layout = {
            0: [0.08, 0.08],
            1: [0.92, 0.08],
            2: [0.08, 0.92]
        }
        self.smoothed_position = None
        self.last_bbox = None
        self.last_detection_at = 0.0
        self.detector_frame_skip = 2
        self.frame_counter = 0
        self.confidence = 0.0
        self.inference_ms = 0.0
        self.yolo_model = None
        self.hog_detector = None
        self.model_name = "Detector no disponible"
        self.detector_status = "Sin inicializar"
        self._init_hog_if_available()
        self._init_yolo_if_available()
        self.latest_state["model_name"] = self.model_name
        self.latest_state["detector_status"] = self.detector_status

    @staticmethod
    def _resolve_log_level(name):

        if hasattr(cv2, name):
            return getattr(cv2, name)

        if (
            hasattr(cv2, "utils")
            and hasattr(cv2.utils, "logging")
            and hasattr(cv2.utils.logging, name)
        ):
            return getattr(cv2.utils.logging, name)

        return None

    @staticmethod
    def _get_opencv_log_level():

        if hasattr(cv2, "getLogLevel"):
            try:
                return cv2.getLogLevel()
            except Exception:
                pass

        if (
            hasattr(cv2, "utils")
            and hasattr(cv2.utils, "logging")
            and hasattr(cv2.utils.logging, "getLogLevel")
        ):
            try:
                return cv2.utils.logging.getLogLevel()
            except Exception:
                pass

        return None

    @staticmethod
    def _set_opencv_log_level(level):

        if level is None:
            return

        if hasattr(cv2, "setLogLevel"):
            try:
                cv2.setLogLevel(level)
                return
            except Exception:
                pass

        if (
            hasattr(cv2, "utils")
            and hasattr(cv2.utils, "logging")
            and hasattr(cv2.utils.logging, "setLogLevel")
        ):
            try:
                cv2.utils.logging.setLogLevel(level)
            except Exception:
                pass

    @staticmethod
    def _open_capture(camera_index):

        attempts = []

        if sys.platform.startswith("win"):
            if hasattr(cv2, "CAP_DSHOW"):
                attempts.append(cv2.CAP_DSHOW)
            if hasattr(cv2, "CAP_MSMF"):
                attempts.append(cv2.CAP_MSMF)
            if not attempts:
                attempts.append(None)
        else:
            attempts.append(None)

        seen_backends = set()

        for backend in attempts:
            backend_key = backend if backend is not None else "default"
            if backend_key in seen_backends:
                continue
            seen_backends.add(backend_key)

            try:
                if backend is None:
                    capture = cv2.VideoCapture(camera_index)
                else:
                    capture = cv2.VideoCapture(camera_index, backend)
            except TypeError:
                capture = cv2.VideoCapture(camera_index)
            except Exception:
                capture = None

            if capture is not None and capture.isOpened():
                return capture

            if capture is not None:
                capture.release()

        return None

    @staticmethod
    def list_cameras(max_index=8, include_details=False):
        cameras = []

        previous_log_level = VisionBackend._get_opencv_log_level()
        quiet_log_level = (
            VisionBackend._resolve_log_level("LOG_LEVEL_SILENT")
            or VisionBackend._resolve_log_level("LOG_LEVEL_FATAL")
            or VisionBackend._resolve_log_level("LOG_LEVEL_ERROR")
        )

        if quiet_log_level is not None:
            VisionBackend._set_opencv_log_level(quiet_log_level)

        try:
            for index in range(max_index + 1):
                capture = VisionBackend._open_capture(index)
                if capture is None:
                    continue

                ok, _ = capture.read()
                width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
                height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
                fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
                capture.release()

                if not ok:
                    continue

                if include_details:
                    label = f"Cámara {index}"
                    if width > 0 and height > 0:
                        label = f"{label} ({width}x{height})"
                    cameras.append({
                        "index": index,
                        "label": label,
                        "width": width,
                        "height": height,
                        "fps": fps
                    })
                else:
                    cameras.append(index)
        finally:
            VisionBackend._set_opencv_log_level(previous_log_level)

        return cameras

    def _init_yolo_if_available(self):
        if not os.path.isfile(self.model_path):
            if self.hog_detector is not None:
                self.detector_status = "YOLO no configurado; usando HOG"
            else:
                self.detector_status = (
                    "YOLO no configurado y OpenCV sin HOGDescriptor"
                )
            return

        try:
            from ultralytics import YOLO

            self.yolo_model = YOLO(self.model_path)
            self.model_name = f"YOLO ({os.path.basename(self.model_path)})"
            self.detector_status = "YOLO activo"
        except Exception:
            self.yolo_model = None
            if self.hog_detector is not None:
                self.model_name = "HOG person"
                self.detector_status = "Fallo al cargar YOLO; usando HOG"
            else:
                self.model_name = "Detector no disponible"
                self.detector_status = (
                    "Fallo al cargar YOLO y OpenCV sin HOGDescriptor"
                )

    def _init_hog_if_available(self):

        if not hasattr(cv2, "HOGDescriptor"):
            self.hog_detector = None
            self.model_name = "Detector no disponible"
            self.detector_status = "OpenCV sin HOGDescriptor"
            return

        if not hasattr(cv2, "HOGDescriptor_getDefaultPeopleDetector"):
            self.hog_detector = None
            self.model_name = "Detector no disponible"
            self.detector_status = "OpenCV sin detector HOG por defecto"
            return

        try:
            detector = cv2.HOGDescriptor()
            detector.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            self.hog_detector = detector
            self.model_name = "HOG person"
            self.detector_status = "HOG activo"
        except Exception:
            self.hog_detector = None
            self.model_name = "Detector no disponible"
            self.detector_status = "Error inicializando HOG"

    def start(self, camera_index=0, aruco_layout=None):
        self.stop()

        with self.lock:

            self.camera_index = int(camera_index)

            if isinstance(aruco_layout, dict):
                normalized = {}
                for key, value in aruco_layout.items():
                    try:
                        marker_id = int(key)
                    except Exception:
                        continue
                    if (
                        isinstance(value, (list, tuple))
                        and len(value) == 2
                    ):
                        normalized[marker_id] = [float(value[0]), float(value[1])]
                if normalized:
                    self.aruco_layout = normalized

            previous_log_level = self._get_opencv_log_level()
            quiet_log_level = (
                self._resolve_log_level("LOG_LEVEL_SILENT")
                or self._resolve_log_level("LOG_LEVEL_FATAL")
                or self._resolve_log_level("LOG_LEVEL_ERROR")
            )

            if quiet_log_level is not None:
                self._set_opencv_log_level(quiet_log_level)

            try:
                self.capture = self._open_capture(self.camera_index)
            finally:
                self._set_opencv_log_level(previous_log_level)

            if self.capture is None or not self.capture.isOpened():
                self.capture = None
                self.latest_state["running"] = False
                self.latest_state["camera_index"] = self.camera_index
                self.latest_state["camera_error"] = "No camera available at selected index."
                return False

            self.running = True
            self.latest_state["running"] = True
            self.latest_state["camera_index"] = self.camera_index
            self.latest_state["camera_error"] = ""
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()
            return True

    def stop(self):
        thread = None
        capture = None

        with self.lock:
            self.running = False
            thread = self.thread
            capture = self.capture
            self.thread = None
            self.capture = None
            self.latest_state["running"] = False
            self.latest_state["calibration_valid"] = False
            self.latest_state["baby_detected"] = False
            self.latest_state["baby_position"] = None
            self.latest_state["camera_error"] = ""
            self.homography = None
            self.smoothed_position = None
            self.last_bbox = None
            self.latest_debug_frame = None

        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

        if capture is not None:
            capture.release()

    def _loop(self):
        last_loop_time = time.perf_counter()

        while self.running:
            started = time.perf_counter()
            frame = None

            with self.lock:
                if self.capture is not None:
                    ok, frame = self.capture.read()
                    if not ok:
                        frame = None

            if frame is None:
                time.sleep(0.03)
                continue

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            aruco_centers = self._detect_aruco(rgb)
            self._update_calibration(aruco_centers)
            self._process_detection(rgb)
            normalized_position = self._map_position_to_game()

            now = time.perf_counter()
            elapsed = max(now - last_loop_time, 1e-6)
            fps = 1.0 / elapsed
            last_loop_time = now
            timestamp = time.time()

            debug = frame.copy()
            self._draw_debug_overlay(debug, aruco_centers, normalized_position, fps)

            with self.lock:
                self.latest_debug_frame = debug
                self.latest_state = {
                    "baby_detected": normalized_position is not None,
                    "baby_position": normalized_position,
                    "confidence": float(self.confidence),
                    "timestamp": timestamp,
                    "calibration_valid": self.homography is not None,
                    "aruco_centers": aruco_centers,
                    "fps": float(fps),
                    "inference_ms": float(self.inference_ms),
                    "model_name": self.model_name,
                    "detector_status": self.detector_status,
                    "running": self.running,
                    "camera_index": self.camera_index,
                    "camera_error": ""
                }

            elapsed_total = time.perf_counter() - started
            wait = max(0.0, (1.0 / 24.0) - elapsed_total)
            if wait > 0:
                time.sleep(wait)

    def _detect_aruco(self, rgb):

        centers = {}

        if not hasattr(cv2, "aruco"):
            return centers

        try:
            dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
            detector_params = cv2.aruco.DetectorParameters()
            detector = cv2.aruco.ArucoDetector(dictionary, detector_params)
            corners, ids, _ = detector.detectMarkers(rgb)
        except Exception:
            return centers

        if ids is None:
            return centers

        for marker_corners, marker_id in zip(corners, ids.flatten()):
            marker_id = int(marker_id)
            center = marker_corners[0].mean(axis=0)
            centers[marker_id] = [float(center[0]), float(center[1])]

        return centers

    def _update_calibration(self, centers):

        required = [0, 1, 2]
        if not all(marker_id in centers for marker_id in required):
            self.homography = None
            return

        source = np.float32([
            centers[0],
            centers[1],
            centers[2]
        ])
        target = np.float32([
            self.aruco_layout.get(0, [0.08, 0.08]),
            self.aruco_layout.get(1, [0.92, 0.08]),
            self.aruco_layout.get(2, [0.08, 0.92])
        ])

        matrix = cv2.getAffineTransform(source, target)
        determinant = matrix[0, 0] * matrix[1, 1] - matrix[0, 1] * matrix[1, 0]
        if abs(determinant) < 1e-6:
            self.homography = None
            return

        self.homography = matrix

    def _process_detection(self, rgb):

        should_detect = (
            self.frame_counter % (self.detector_frame_skip + 1) == 0
            or self.last_bbox is None
        )
        self.frame_counter += 1

        if not should_detect:
            return

        started = time.perf_counter()
        bbox = None
        confidence = 0.0

        if self.yolo_model is not None:
            bbox, confidence = self._detect_with_yolo(rgb)

        if bbox is None:
            bbox, confidence = self._detect_with_hog(rgb)
            if self.hog_detector is not None:
                self.model_name = "HOG person"
                if self.yolo_model is None:
                    self.detector_status = "Usando HOG"
            elif self.yolo_model is None:
                self.model_name = "Detector no disponible"
                self.detector_status = (
                    "Sin YOLO y OpenCV no expone HOGDescriptor"
                )

        self.inference_ms = (time.perf_counter() - started) * 1000.0

        if bbox is None:
            if time.perf_counter() - self.last_detection_at > 0.9:
                self.last_bbox = None
                self.smoothed_position = None
                self.confidence = 0.0
            return

        self.last_bbox = bbox
        self.confidence = confidence
        self.last_detection_at = time.perf_counter()
        center_x = bbox[0] + bbox[2] * 0.5
        center_y = bbox[1] + bbox[3] * 0.5
        measured = np.array([center_x, center_y], dtype=np.float32)

        if self.smoothed_position is None:
            self.smoothed_position = measured
        else:
            alpha = 0.38
            self.smoothed_position = self.smoothed_position * (1.0 - alpha) + measured * alpha

    def _detect_with_yolo(self, rgb):

        try:
            results = self.yolo_model.predict(
                source=rgb,
                verbose=False,
                device="cpu",
                classes=None
            )
        except Exception:
            self.yolo_model = None
            return None, 0.0

        best_bbox = None
        best_conf = 0.0

        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                cls_id = int(box.cls.item())
                conf = float(box.conf.item())
                names = result.names
                label = str(names.get(cls_id, "")).lower()
                if label not in ("person", "child", "baby"):
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                w = x2 - x1
                h = y2 - y1
                if w <= 2 or h <= 2:
                    continue
                score = conf * w * h
                if score > best_conf:
                    best_conf = conf
                    best_bbox = [float(x1), float(y1), float(w), float(h)]

        if best_bbox is not None:
            self.model_name = f"YOLO ({os.path.basename(self.model_path)})"

        return best_bbox, best_conf

    def _detect_with_hog(self, rgb):

        if self.hog_detector is None:
            return None, 0.0

        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        boxes, weights = self.hog_detector.detectMultiScale(
            bgr,
            winStride=(8, 8),
            padding=(8, 8),
            scale=1.05
        )

        if len(boxes) == 0:
            return None, 0.0

        best_index = 0
        best_area = 0.0
        for index, box in enumerate(boxes):
            _, _, width, height = box
            area = float(width * height)
            if area > best_area:
                best_area = area
                best_index = index

        x, y, w, h = boxes[best_index]
        weight = float(weights[best_index]) if len(weights) > best_index else 0.0
        confidence = min(max(weight / 2.0, 0.0), 1.0)
        return [float(x), float(y), float(w), float(h)], confidence

    def _map_position_to_game(self):

        if self.homography is None or self.smoothed_position is None:
            return None

        point = np.array([
            [self.smoothed_position[0]],
            [self.smoothed_position[1]],
            [1.0]
        ], dtype=np.float32)

        matrix = np.vstack([self.homography, [0.0, 0.0, 1.0]])
        mapped = matrix @ point
        x = float(mapped[0] / mapped[2])
        y = float(mapped[1] / mapped[2])
        x = min(max(x, 0.0), 1.0)
        y = min(max(y, 0.0), 1.0)
        return [x, y]

    def _draw_debug_overlay(self, frame, aruco_centers, normalized_position, fps):

        for marker_id, center in aruco_centers.items():
            cx, cy = int(center[0]), int(center[1])
            cv2.circle(frame, (cx, cy), 7, (0, 255, 255), -1)
            cv2.putText(
                frame,
                f"ARUCO {marker_id}",
                (cx + 8, cy - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (0, 255, 255),
                1,
                cv2.LINE_AA
            )

        if self.last_bbox is not None:
            x, y, w, h = self.last_bbox
            cv2.rectangle(
                frame,
                (int(x), int(y)),
                (int(x + w), int(y + h)),
                (0, 255, 0),
                2
            )

        y = 24
        debug_lines = [
            f"Baby detected: {'YES' if normalized_position is not None else 'NO'}",
            f"X: {normalized_position[0]:.3f}" if normalized_position is not None else "X: -",
            f"Y: {normalized_position[1]:.3f}" if normalized_position is not None else "Y: -",
            f"Confidence: {self.confidence:.2f}",
            f"FPS: {fps:.1f}",
            f"Inference: {self.inference_ms:.1f} ms",
            f"Model: {self.model_name}",
            f"Calibration: {'OK' if self.homography is not None else 'INVALID'}"
        ]

        for line in debug_lines:
            cv2.putText(
                frame,
                line,
                (10, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1,
                cv2.LINE_AA
            )
            y += 20

    def get_state(self):
        with self.lock:
            state = dict(self.latest_state)
            if state.get("baby_position") is not None:
                state["baby_position"] = list(state["baby_position"])
            if state.get("aruco_centers") is not None:
                state["aruco_centers"] = {
                    int(key): list(value)
                    for key, value in state["aruco_centers"].items()
                }
            return state

    def get_debug_frame(self):
        with self.lock:
            if self.latest_debug_frame is None:
                return None
            return self.latest_debug_frame.copy()
