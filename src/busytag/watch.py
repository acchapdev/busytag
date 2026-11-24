"""Redraw the status screen when a display is plugged in.

Hooks only push when an agent reports, so a display plugged in between reports keeps
showing an old status (the Busy Tag keeps its last image) or its boot screen (the ESP32).
`busytag watch` polls the USB port list, which is cheap and never opens a port, and
redraws when a display port appears. It also drops agents past their timeout (a finished agent
after `done_timeout`), since nothing else runs then, and polls touchscreen displays for taps
(see touch.py). A LaunchAgent keeps it running.
"""

import time

from serial.tools import list_ports

from busytag.device import PRODUCT_ID, VENDOR_ID

# Busy Tag, the USB ID shared by every ESP32 with built-in USB, and the WCH USB-serial
# bridges (CH340, CH9102) on boards like the Cheap Yellow Display (ours answer `hello`)
DISPLAY_IDS = {(VENDOR_ID, PRODUCT_ID), (VENDOR_ID, 0x1001), (0x1A86, 0x7523), (0x1A86, 0x55D4)}
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


def run(redraw, expire=None, ports=display_ports, sleep=time.sleep, log=print, polls=None, touch=None):
  """Call `redraw()` whenever a display port appears, including one present at start,
  `expire()` about once a minute, and `touch(port)` on every poll for each port that may be
  a touchscreen display.

  `touch(port)` returns log lines, or None when the port has no touch support; that port
  isn't asked again until it is plugged in again. `polls` limits the loop (for tests);
  None runs forever.
  """
  seen = set()
  no_touch = set()
  touch_errors = {}
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
    no_touch &= current
    if touch:
      for port in sorted(current - no_touch):
        try:
          lines = touch(port)
        except Exception as error:
          # e.g. a serial monitor holds the port; say so once, not every poll
          if touch_errors.get(port) != str(error):
            log(f'{stamp()} touch poll on {port} failed: {error}')
          touch_errors[port] = str(error)
          continue
        touch_errors.pop(port, None)
        if lines is None:
          no_touch.add(port)
          continue
        for line in lines:
          log(f'{stamp()} {line}')
    if polls is not None:
      polls -= 1
    sleep(POLL_SECONDS)
