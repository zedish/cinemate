import logging
import threading
import time
import evdev

LOGICAL_W = 800
LOGICAL_H = 480
REF_W = 1920
REF_H = 1080


def _scale_x(x):
    return int(x * LOGICAL_W / REF_W)


def _scale_y(y):
    return int(y * LOGICAL_H / REF_H)


class TouchController:
    def __init__(self, cinepi_controller, settings=None):
        self.cinepi_controller = cinepi_controller
        self.settings = settings or {}
        self.device = None
        self._running = threading.Event()
        self._thread = None

        # Touch coordinate state
        self._x = 0
        self._y = 0

        # Coordinate mapping (from evdev caps)
        self.touch_min_x = 0
        self.touch_max_x = 800
        self.touch_min_y = 0
        self.touch_max_y = 480
        self._swap_xy = None   # None = auto, True/False = forced

        swp = self.settings.get("swap_xy", None)
        if swp is not None:
            self._swap_xy = bool(swp)

        # Build tap zones (in logical 800x480 space)
        self.zones = self._build_zones()

        self._find_device()
        if self.device:
            logging.info("Touch: found %s on %s", self.device.name, self.device.path)
            self._parse_caps()
            self.start()
        else:
            logging.info("Touch: no touch device found")

    # ── device detection ──────────────────────────────────────────
    def _find_device(self):
        for fn in evdev.list_devices():
            try:
                dev = evdev.InputDevice(fn)
                caps = dev.capabilities()
                has_abs = evdev.ecodes.EV_ABS in caps
                has_touch = False
                if evdev.ecodes.EV_KEY in caps:
                    for key, _ in caps[evdev.ecodes.EV_KEY]:
                        if key == evdev.ecodes.BTN_TOUCH:
                            has_touch = True
                            break
                if has_abs and has_touch:
                    self.device = dev
                    return
                dev.close()
            except Exception:
                continue

    def _parse_caps(self):
        try:
            xi = self.device.absinfo(evdev.ecodes.ABS_X)
            yi = self.device.absinfo(evdev.ecodes.ABS_Y)
            self.touch_min_x, self.touch_max_x = xi.min, xi.max
            self.touch_min_y, self.touch_max_y = yi.min, yi.max
            tw = self.touch_max_x - self.touch_min_x + 1
            th = self.touch_max_y - self.touch_min_y + 1
            if self._swap_xy is None:
                self._swap_xy = th > tw
            logging.info("Touch: range %dx%d swap=%s", tw, th, self._swap_xy)
        except Exception as e:
            logging.warning("Touch: failed to read caps: %s", e)

    # ── coordinate mapping ────────────────────────────────────────
    def _map_to_logical(self, tx, ty):
        if self._swap_xy:
            tx, ty = ty, tx
        nx = (tx - self.touch_min_x) / max(1, self.touch_max_x - self.touch_min_x)
        ny = (ty - self.touch_min_y) / max(1, self.touch_max_y - self.touch_min_y)
        return int(nx * LOGICAL_W), int(ny * LOGICAL_H)

    # ── tap zones ─────────────────────────────────────────────────
    def _build_zones(self):
        zones = []
        cc = self.cinepi_controller

        params = [
            ("FPS",     60,   230,  cc.dec_fps,          cc.inc_fps),
            ("SHTR",    300,  250,  cc.dec_shutter_a,     cc.inc_shutter_a),
            ("ISO",     920,  200,  cc.dec_iso,           cc.inc_iso),
            ("WB",      1150, 200,  None,                 None),
            ("RES",     1450, 200,  cc.switch_resolution, None),
        ]

        row_y = _scale_y(0)
        row_h = _scale_y(55)

        for name, ref_x, ref_w, on_dec, on_inc in params:
            x = _scale_x(ref_x)
            w = _scale_x(ref_w)
            mid = w // 2
            if on_dec:
                zones.append((x, row_y, mid, row_h, on_dec, name + "_dec"))
            if on_inc:
                zones.append((x + mid, row_y, w - mid, row_h, on_inc, name + "_inc"))

        # EXP area (between SHTR and ISO)
        exp_x = _scale_x(660)
        exp_w = _scale_x(190)
        exp_y = _scale_y(0)
        exp_h = _scale_y(50)

        # Bottom row: REC and PHOTO
        rec_y = _scale_y(1000)
        rec_h = _scale_y(80)

        zones.append((_scale_x(80),  rec_y, _scale_x(250), rec_h, cc.rec,          "REC"))
        zones.append((_scale_x(400), rec_y, _scale_x(200), rec_h, cc.take_photo,   "PHOTO"))

        return zones

    def _find_zone(self, lx, ly):
        for x, y, w, h, cb, name in self.zones:
            if x <= lx <= x + w and y <= ly <= y + h:
                return cb, name
        return None, None

    # ── event handling ────────────────────────────────────────────
    def _handle_tap(self, tx, ty):
        lx, ly = self._map_to_logical(tx, ty)
        cb, name = self._find_zone(lx, ly)
        if cb:
            logging.info("Touch tap: %s at logical (%d, %d)", name, lx, ly)
            try:
                cb()
            except Exception as exc:
                logging.warning("Touch: %s callback failed: %s", name, exc)

    def _reader(self):
        if not self.device:
            return
        self._running.set()
        tx = ty = 0
        try:
            for event in self.device.read_loop():
                if not self._running.is_set():
                    break
                if event.type == evdev.ecodes.EV_ABS:
                    if event.code == evdev.ecodes.ABS_X:
                        tx = event.value
                    elif event.code == evdev.ecodes.ABS_Y:
                        ty = event.value
                elif event.type == evdev.ecodes.EV_KEY and event.code == evdev.ecodes.BTN_TOUCH:
                    if event.value == 1:
                        self._handle_tap(tx, ty)
        except OSError:
            logging.error("Touch: device disconnected")
        except Exception as e:
            logging.error("Touch: reader error: %s", e)

    # ── lifecycle ─────────────────────────────────────────────────
    def start(self):
        if not self._running.is_set():
            self._thread = threading.Thread(target=self._reader, daemon=True)
            self._thread.start()

    def stop(self):
        self._running.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)
