"""Redraw the status screen when a display is plugged in.

Hooks only push when an agent reports, so a display plugged in between reports keeps
showing an old status (the Busy Tag keeps its last image) or its boot screen (the ESP32).
`busytag watch` polls the USB port list, which is cheap and never opens a port, and
redraws when a display port appears. It also drops agents past their timeout (a finished agent
after `done_timeout`), since nothing else runs then. A LaunchAgent keeps it running.
"""

import time

from serial.tools import list_ports

from busytag.device import PRODUCT_ID, VENDOR_ID

# Busy Tag, and the USB ID shared by every ESP32 with built-in USB (ours answers `hello`)
DISPLAY_IDS = {(VENDOR_ID, PRODUCT_ID), (VENDOR_ID, 0x1001)}
POLL_SECONDS = 2.0
# Give a freshly enumerated device a moment before opening its port
SETTLE_SECONDS = 1.0
# Check for agents past their timeout about once a minute
EXPIRE_EVERY_POLLS = 30


def display_ports():
  return {
    port.device for port in list_ports.comports()
    if (port.vid, port.pid) in DISPLAY_IDS and not port.device.startswith('/dev/tty.')
  }


def stamp():
  return time.strftime('%Y-%m-%d %H:%M:%S')


def run(redraw, expire=None, ports=display_ports, sleep=time.sleep, log=print, polls=None):
  """Call `redraw()` whenever a display port appears, including one present at start,
  and `expire()` about once a minute.

  `polls` limits the loop (for tests); None runs forever.
  """
  seen = set()
  count = 0
  while polls is None or polls > 0:
    count += 1
    if expire and count % EXPIRE_EVERY_POLLS == 0:
      dropped, error = expire()
      if dropped:
        log(f'{stamp()} {dropped} agent(s) timed out: ' + (f'not updated: {error}' if error else 'screen updated'))
    current = ports()
    if current - seen:
      sleep(SETTLE_SECONDS)
      error = redraw()
      log(f'{stamp()} display connected ({", ".join(sorted(current - seen))}): '
          + (f'not updated: {error}' if error else 'screen redrawn'))
    seen = current
    if polls is not None:
      polls -= 1
    sleep(POLL_SECONDS)
