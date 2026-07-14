#!/usr/bin/env python3
"""
Touch coordinate transform daemon.
Grabs the real touch device and forwards transformed events to a virtual
uinput device. Run with sudo (needs /dev/uinput access).
"""

import sys
import time
import signal
import argparse
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s: %(message)s',
)
log = logging.getLogger('touch_transform')

from evdev import UInput, InputDevice, list_devices, ecodes as e, AbsInfo


def find_touch_device(name_contains='Goodix'):
    for path in list_devices():
        dev = InputDevice(path)
        if name_contains in dev.name:
            log.info('Found device: %s at %s', dev.name, path)
            return path
    log.error('No touch device found')
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', help='Input device path (auto)')
    parser.add_argument('--transform', choices=['270', '90', '180', 'none'],
                        default='270')
    parser.add_argument('--phys-x', type=int, default=799)
    parser.add_argument('--phys-y', type=int, default=479)
    parser.add_argument('--virt-x', type=int, default=479)
    parser.add_argument('--virt-y', type=int, default=799)
    args = parser.parse_args()

    dev_path = args.device or find_touch_device()
    phys = InputDevice(dev_path)
    log.info('Device info: %s', phys)

    # Grab the physical device
    try:
        phys.grab()
        log.info('Grabbed device successfully')
    except Exception as exc:
        log.error('Failed to grab device: %s', exc)
        sys.exit(1)

    # Build virtual device
    ax = AbsInfo(0, 0, args.virt_x, 0, 0, 0)
    ay = AbsInfo(0, 0, args.virt_y, 0, 0, 0)

    cap = {
        e.EV_KEY: [e.BTN_TOUCH, e.BTN_TOOL_FINGER],
        e.EV_ABS: [
            (e.ABS_X, ax), (e.ABS_Y, ay),
            (e.ABS_MT_SLOT, AbsInfo(0, 0, 9, 0, 0, 0)),
            (e.ABS_MT_TRACKING_ID, AbsInfo(0, 0, 65535, 0, 0, 0)),
            (e.ABS_MT_POSITION_X, ax), (e.ABS_MT_POSITION_Y, ay),
            (e.ABS_MT_TOUCH_MAJOR, AbsInfo(0, 0, 255, 0, 0, 0)),
            (e.ABS_MT_WIDTH_MAJOR, AbsInfo(0, 0, 255, 0, 0, 0)),
        ],
    }

    try:
        ui = UInput(cap, name='Transformed TouchScreen', version=0x1060,
                    bustype=0x0018, vendor=0x0416, product=0x038f)
        log.info('Created virtual device')
    except Exception as exc:
        log.error('Failed to create virtual device: %s', exc)
        log.error('Need write access to /dev/uinput — run with sudo')
        phys.ungrab()
        sys.exit(1)

    # Transform: for wlr-randr 270, map physical (800×480) to logical (480×800)
    px, py = args.phys_x, args.phys_y
    transforms = {
        '270':  lambda x, y: (y, px - x),
        '90':   lambda x, y: (py - y, x),
        '180':  lambda x, y: (px - x, py - y),
        'none': lambda x, y: (x, y),
    }
    xf = transforms[args.transform]

    buf_x = None
    mt_slot = 0
    mt_x = {}

    running = True
    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    log.info('Daemon running (transform=%s). Waiting for events...', args.transform)

    ev_count = 0
    try:
        for event in phys.read_loop():
            if not running:
                break

            t, c, v = event.type, event.code, event.value
            ev_count += 1

            if t == e.EV_KEY:
                ui.write(t, c, v)
                continue

            if t == e.EV_SYN:
                if buf_x is not None:
                    buf_x = None  # unmatched X — flush
                ui.write(t, c, v)
                ui.syn()
                continue

            if t == e.EV_ABS:
                if c == e.ABS_MT_SLOT:
                    mt_slot = v
                    ui.write(t, c, v)
                    continue
                if c == e.ABS_MT_TRACKING_ID:
                    mt_x[mt_slot] = None
                    ui.write(t, c, v)
                    continue
                if c == e.ABS_X:
                    buf_x = v
                    continue
                if c == e.ABS_Y:
                    if buf_x is not None:
                        tx, ty = xf(buf_x, v)
                        ui.write(e.EV_ABS, e.ABS_X, tx)
                        ui.write(e.EV_ABS, e.ABS_Y, ty)
                        buf_x = None
                    continue
                if c == e.ABS_MT_POSITION_X:
                    mt_x[mt_slot] = v
                    continue
                if c == e.ABS_MT_POSITION_Y:
                    xv = mt_x.get(mt_slot)
                    if xv is not None:
                        tx, ty = xf(xv, v)
                        ui.write(e.EV_ABS, e.ABS_MT_POSITION_X, tx)
                        ui.write(e.EV_ABS, e.ABS_MT_POSITION_Y, ty)
                        mt_x[mt_slot] = None
                    continue
                if c in (e.ABS_MT_TOUCH_MAJOR, e.ABS_MT_WIDTH_MAJOR):
                    ui.write(t, c, v)
                    continue

    except Exception as exc:
        log.error('Error: %s', exc)
        raise
    finally:
        ui.close()
        phys.ungrab()
        phys.close()
        log.info('Stopped (processed %d events)', ev_count)


if __name__ == '__main__':
    main()
