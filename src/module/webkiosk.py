#!/usr/bin/env python3
"""
Fullscreen web UI kiosk for the DPI display.
Uses cage (wlroots-based kiosk compositor) + chromium-browser.
Optionally starts a touch-transform daemon so display rotation
doesn't break touch tracking.
"""

import os
import sys
import time
import signal
import subprocess
import argparse
import logging
import pathlib

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
log = logging.getLogger('webkiosk')

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent


def find_drm_card():
    for card_path in ['/dev/dri/card2', '/dev/dri/card1', '/dev/dri/card0']:
        if not os.path.exists(card_path):
            continue
        try:
            card = os.path.basename(card_path)
            r = subprocess.run(
                ['modetest', '-M', card, '-c'],
                capture_output=True, text=True, timeout=5,
            )
            output = (r.stdout + r.stderr).lower()
            if 'dpi' in output or 'rp1' in output:
                log.info('Found DPI display on %s', card_path)
                return card_path
        except Exception:
            continue
    log.info('DPI display not found, trying /dev/dri/card2')
    return '/dev/dri/card2'


def find_virtual_touch():
    from evdev import InputDevice, list_devices
    for path in list_devices():
        try:
            if 'Transformed' in InputDevice(path).name:
                return path
        except Exception:
            continue
    return None


def main():
    parser = argparse.ArgumentParser(description='Cinemate Web UI Kiosk')
    parser.add_argument('--url', default='http://localhost:5000')
    parser.add_argument('--drm-card', default=None)
    parser.add_argument('--touch-transform', action='store_true',
                        help='Enable touch coordinate transformation')
    parser.add_argument('--output', default='DPI-1')
    parser.add_argument('--transform', default='270')
    args = parser.parse_args()

    drm_card = args.drm_card or find_drm_card()

    # Kill leftovers
    subprocess.run(['pkill', '-9', '-f', 'touch_transform'], capture_output=True)
    subprocess.run(['pkill', '-9', '-f', 'cage'], capture_output=True)
    subprocess.run(['pkill', '-9', '-f', 'chromium-browser'], capture_output=True)
    time.sleep(1)
    t0 = time.monotonic()

    # Start touch transform daemon if requested
    touch_proc = None
    if args.touch_transform:
        log.info('Starting touch transform daemon...')
        touch_script = SCRIPT_DIR / 'touch_transform.py'
        touch_proc = subprocess.Popen(
            ['sudo', sys.executable, str(touch_script),
             '--transform', args.transform],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for _ in range(30):
            if find_virtual_touch():
                break
            time.sleep(0.5)
        if find_virtual_touch():
            log.info('Virtual touch device ready')
        else:
            log.warning('Virtual touch device not found — continuing anyway')

    env = {
        **os.environ,
        'WLR_DRM_DEVICES': drm_card,
        'XDG_RUNTIME_DIR': os.environ.get('XDG_RUNTIME_DIR',
                                          f'/run/user/{os.getuid()}'),
    }
    wayland_socket = os.path.join(env['XDG_RUNTIME_DIR'], 'wayland-0')

    log.info('Starting cage on %s', drm_card)
    cage_proc = subprocess.Popen(
        ['cage', '--',
         'chromium-browser',
         '--kiosk',
         '--no-sandbox',
         '--disable-partition-alloc',
         '--ozone-platform=wayland',
         '--disable-features=TranslateUI',
         '--disable-sync',
         '--disable-default-apps',
         '--disable-extensions',
         '--disable-background-networking',
         '--no-first-run',
         '--hide-scrollbars',
         '--autoplay-policy=no-user-gesture-required',
         args.url,
        ],
        env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    log.info('Waiting for cage socket...')
    for _ in range(60):
        if os.path.exists(wayland_socket):
            break
        time.sleep(0.5)
    else:
        log.error('cage failed to start')
        cage_proc.terminate()
        sys.exit(1)
    log.info('cage socket ready (%.1fs)', time.monotonic() - t0)

    # Set display rotation
    if args.touch_transform:
        log.info('Setting transform %s on %s', args.transform, args.output)
        transform_env = {**env, 'WAYLAND_DISPLAY': 'wayland-0'}
        for attempt in range(5):
            r = subprocess.run(
                ['wlr-randr', '--output', args.output,
                 '--transform', args.transform],
                env=transform_env, capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                break
            time.sleep(0.5)

    log.info('Kiosk started: %s (%.1fs)', args.url, time.monotonic() - t0)

    def cleanup(*_):
        log.info('Shutting down...')
        cage_proc.terminate()
        try:
            cage_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cage_proc.kill()
        if touch_proc:
            touch_proc.terminate()
            touch_proc.wait()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    cage_proc.wait()
    log.info('cage exited')


if __name__ == '__main__':
    main()
