"""Redraw the status screen when a display is plugged in.

Hooks only push when an agent reports, so a display plugged in between reports keeps
showing an old status (the Busy Tag keeps its last image) or its boot screen (the ESP32).
`busytag watch` polls the USB port list, which is cheap and never opens a port, and
redraws when a display port appears. A LaunchAgent keeps it running (see integrations).
"""

import time

from serial.tools import list_ports

from busytag.device import PRODUCT_ID, VENDOR_ID

# Busy Tag, and the USB ID shared by every ESP32 with built-in USB (ours answers `hello`)
DISPLAY_IDS = {(VENDOR_ID, PRODUCT_ID), (VENDOR_ID, 0x1001)}
POLL_SECONDS = 2.0
# Give a freshly enumerated device a moment before opening its port
SETTLE_SECONDS = 1.0


def display_ports():
  return {
    port.device for port in list_ports.comports()
    if (port.vid, port.pid) in DISPLAY_IDS and not port.device.startswith('/dev/tty.')
  }


def run(redraw, ports=display_ports, sleep=time.sleep, log=print, polls=None):
  """Call `redraw()` whenever a display port appears, including one present at start.

  `polls` limits the loop (for tests); None runs forever.
  """
  seen = set()
  while polls is None or polls > 0:
    current = ports()
    if current - seen:
      sleep(SETTLE_SECONDS)
      error = redraw()
      log(f'{time.strftime("%Y-%m-%d %H:%M:%S")} display connected ({", ".join(sorted(current - seen))}): '
          + (f'not updated: {error}' if error else 'screen redrawn'))
    seen = current
    if polls is not None:
      polls -= 1
    sleep(POLL_SECONDS)
