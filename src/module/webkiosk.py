#!/usr/bin/env python3
import os, sys, time, signal, subprocess, argparse, logging, pathlib

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
log = logging.getLogger('webkiosk')

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
            if 'dpi' in (r.stdout + r.stderr).lower() or 'rp1' in (r.stdout + r.stderr).lower():
                log.info('Found DPI display on %s', card_path)
                return card_path
        except Exception:
            continue
    log.info('DPI display not found, trying /dev/dri/card2')
    return '/dev/dri/card2'

def main():
    parser = argparse.ArgumentParser(description='Cinemate Web UI Kiosk')
    parser.add_argument('--url', default='http://localhost:5000')
    parser.add_argument('--drm-card', default=None)
    args = parser.parse_args()

    drm_card = args.drm_card or find_drm_card()

    subprocess.run(['pkill', '-9', '-f', 'cage'], capture_output=True)
    subprocess.run(['pkill', '-9', '-f', 'chromium-browser'], capture_output=True)
    time.sleep(1)
    t0 = time.monotonic()

    kms_cards = []
    for p in pathlib.Path('/dev/dri').glob('card*'):
        cd = pathlib.Path(f'/sys/class/drm/{p.name}')
        has_connectors = cd.exists() and any(
            e.name.startswith(p.name + '-') for e in cd.iterdir()
        )
        if has_connectors and str(p) != drm_card:
            kms_cards.append(str(p))
    drm_devices = ':'.join([drm_card] + kms_cards)

    # Set output rotation via KMS before cage starts
    for card in [drm_card] + kms_cards:
        card_name = os.path.basename(card)
        try:
            connector_dir = pathlib.Path(f'/sys/class/drm/{card_name}')
            for entry in connector_dir.iterdir():
                if entry.name.startswith(card_name + '-') and 'DPI' in entry.name:
                    conn_id_path = entry / 'connector_id'
                    if conn_id_path.exists():
                        conn_id = conn_id_path.read_text().strip()
                        subprocess.run(
                            ['modetest', '-M', card_name, '-w', conn_id,
                             ':rotation:4'],
                            capture_output=True, timeout=5,
                        )
                        log.info('Set rotation 270 on %s connector %s',
                                 entry.name, conn_id)
        except Exception:
            pass

    runtime_dir = pathlib.Path(f'/tmp/.cinemate-{os.getuid()}')
    runtime_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(runtime_dir, 0o700)

    env = {
        **os.environ,
        'WLR_DRM_DEVICES': drm_devices,
        'XDG_RUNTIME_DIR': str(runtime_dir),
    }
    wayland_socket = str(runtime_dir / 'wayland-0')

    log.info('Starting cage on %s (WLR_DRM_DEVICES=%s)', drm_card, drm_devices)
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
    log.info('Kiosk started: %s (%.1fs)', args.url, time.monotonic() - t0)

    def cleanup(*_):
        log.info('Shutting down...')
        cage_proc.terminate()
        try:
            cage_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cage_proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
    cage_proc.wait()
    log.info('cage exited')

if __name__ == '__main__':
    main()
