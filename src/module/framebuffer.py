#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# From https://github.com/robertmuth/Pytorinox

"""Framebuffer helper that makes lots of simpifying assumptions
bits_per_pixel    assumed memory layout
16                rgb565
24                rgb
32                argb
"""

from PIL import Image
import glob
import os
import numpy


def _read_and_convert_to_ints(filename):
    with open(filename, "r") as fp:
        content = fp.read()
        tokens = content.strip().split(",")
        return [int(t) for t in tokens if t]


def _converter_argb(image: Image):
    return bytes([x for r, g, b in image.getdata() for x in (255, r, g, b)])


def _converter_rgb565(image: Image):
    return bytes([x for r, g, b in image.getdata()
                  for x in ((g & 0x1c) << 3 | (b >> 3), r & 0xf8 | (g >> 3))])


def _converter_1_argb(image: Image):
    return bytes([x for p in image.getdata()
                  for x in (255, p, p, p)])


def _converter_1_rgb(image: Image):
    return bytes([x for p in image.getdata()
                  for x in (p, p, p)])


def _converter_1_rgb565(image: Image):
    return bytes([(255 if x else 0) for p in image.getdata()
                  for x in (p, p)])


def _converter_rgba_rgb565_numpy(image: Image):
    flat = numpy.frombuffer(image.tobytes(), dtype=numpy.uint32)
    # note,  this is assumes little endian byteorder and results in
    # the following packing of an integer:
    # bits 0-7: red, 8-15: green, 16-23: blue, 24-31: alpha
    flat = ((flat & 0xf8) << 8) | ((flat & 0xfc00) >> 5) | ((flat & 0xf80000) >> 19)
    return flat.astype(numpy.uint16).tobytes()


def _converter_no_change(image: Image):
    return image.tobytes()


def _converter_rgba_xrgb8888(image: Image):
    """Convert RGBA PIL image to XRGB8888 (byte order B, G, R, X)."""
    flat = numpy.frombuffer(image.tobytes(), dtype=numpy.uint32)
    r = flat & 0xff
    g = flat & 0xff00
    b = flat & 0xff0000
    xrgb = (b >> 16) | g | (r << 16) | numpy.uint32(0xff000000)
    return xrgb.astype(numpy.uint32).tobytes()


def _converter_rgba_rgb(image: Image):
    return image.convert("RGB").tobytes()

# anything that does not use numpy is hopelessly slow
_CONVERTER = {
    ("RGBA", 16): _converter_rgba_rgb565_numpy,
    ("RGBA", 24): _converter_rgba_rgb,
    ("RGB", 16): _converter_rgb565,
    ("RGB", 24): _converter_no_change,
    ("RGB", 32): _converter_argb,
    ("RGBA", 32): _converter_rgba_xrgb8888,
    # note numpy does not work well with mode="1" images as
    # image.tobytes() loses pixel color info
    ("1", 16): _converter_1_rgb565,
    ("1", 24): _converter_1_rgb,
    ("1", 32): _converter_1_argb,
}


class Framebuffer(object):

    def __init__(self, device_no: int):
        self.path = f"/dev/fb{device_no}"
        config_dir = f"/sys/class/graphics/fb{device_no}"
        try:
            self.size = tuple(_read_and_convert_to_ints(
                config_dir + "/virtual_size"))
            self.stride = _read_and_convert_to_ints(config_dir + "/stride")[0]
            self.bits_per_pixel = _read_and_convert_to_ints(
                config_dir + "/bits_per_pixel")[0]
            assert self.stride == self.bits_per_pixel // 8 * self.size[0]
        except (AssertionError, FileNotFoundError, OSError, ValueError):
            self.size = (0, 0)
            self.stride = 0
            self.bits_per_pixel = 0

    # def __init__(self, device_no: int):
    #     self.path = f"/dev/fb{device_no}"
    #     config_dir = f"/sys/class/graphics/fb{device_no}"
    #     self.size = tuple(_read_and_convert_to_ints(
    #         config_dir + "/virtual_size"))
    #     self.stride = _read_and_convert_to_ints(config_dir + "/stride")[0]
    #     self.bits_per_pixel = _read_and_convert_to_ints(
    #         config_dir + "/bits_per_pixel")[0]
    #     assert self.stride == self.bits_per_pixel // 8 * self.size[0]

    def __str__(self):
        args = (self.path, self.size, self.stride, self.bits_per_pixel)
        return "%s  size:%s  stride:%s  bits_per_pixel:%s" % args

    @property
    def usable(self) -> bool:
        return (
            os.path.exists(self.path)
            and self.size[0] > 0
            and self.size[1] > 0
            and self.stride > 0
            and self.bits_per_pixel in (16, 24, 32)
        )

    # Note: performance is terrible even for medium resolutions
    def show(self, image: Image):
        if not self.usable:
            raise RuntimeError(f"Framebuffer {self.path} is not available")
        converter = _CONVERTER.get((image.mode, self.bits_per_pixel))
        if converter is None:
            raise RuntimeError(
                f"Unsupported framebuffer format: mode={image.mode}, bpp={self.bits_per_pixel}"
            )
        if image.size != self.size:
            raise ValueError(
                f"Framebuffer image size mismatch: expected {self.size}, got {image.size}"
            )
        out = converter(image)
        with open(self.path, "wb") as fp:
            fp.write(out)

    def on(self):
        pass

    def off(self):
        pass


def drm_hdmi_connected():
    status_paths = sorted(glob.glob("/sys/class/drm/card*-HDMI-A-*/status"))
    if not status_paths:
        return None

    for path in status_paths:
        try:
            with open(path, "r") as fp:
                if fp.read().strip().lower() == "connected":
                    return True
        except OSError:
            continue

    return False


def acquire_framebuffer(device_no: int):
    fb = Framebuffer(device_no)
    if not fb.usable:
        return None

    return fb


def acquire_any_framebuffer(max_devices: int = 3, preferred: int | None = None):
    """Return a usable framebuffer.

    If *preferred* is set (e.g. from a ``gui_display.fb_device``
    setting), that device is tried first.  Otherwise connected displays
    are preferred over disconnected HDMI.
    """
    order: list[int] = []
    if preferred is not None:
        order.append(preferred)

    connected = None
    try:
        connected = drm_hdmi_connected()
    except Exception:
        pass

    for dev in range(max_devices):
        if dev != preferred:
            # when HDMI has no cable, skip fb0 so a DPI display (fb1+) wins
            if dev == 0 and connected is False:
                continue
            order.append(dev)

    # if HDMI was skipped and nothing found, try fb0 as last resort
    if 0 not in order and connected is False:
        order.append(0)

    for dev_no in order:
        fb = acquire_framebuffer(dev_no)
        if fb is not None:
            return fb
    return None

# if __name__ == "__main__":
#     import time
#     from PIL import ImageDraw


#     def TestFrameBuffer(i):
#         fb = Framebuffer(i)
#         print(fb)
#         image = Image.new("RGBA", fb.size)
#         draw = ImageDraw.Draw(image)
#         draw.rectangle(((0, 0), fb.size), fill="green")
#         draw.ellipse(((0, 0), fb.size), fill="blue", outline="red")
#         draw.line(((0, 0), fb.size), fill="green", width=2)
#         start = time.time()
#         for i in range(5):
#             fb.show(image)
#         stop = time.time()
#         print("fps: %.2f" % (10 / (stop - start)))


#     for i in [0]:
#         TestFrameBuffer(i)
