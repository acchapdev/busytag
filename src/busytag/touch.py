"""Act on taps from a touchscreen display (firmware/esp32-cyd), polled by `busytag watch`.

The board can't reach the laptop on its own (each busytag command opens the serial port only
for a moment), so taps that need the laptop are queued on the board. `busytag watch` asks
for them every couple of seconds, under the same lock as the hooks.
"""

from serial.tools import list_ports

from busytag import jump
from busytag import status as board
from busytag.device import PRODUCT_ID, VENDOR_ID, BusyTagError

# Replies that mean the port has no touchscreen busytag firmware, so polling it is pointless
NOT_TOUCH = ('unknown command', 'Timed out', 'not running the busytag')


def is_busy_tag(port):
  return any(
    p.vid == VENDOR_ID and p.pid == PRODUCT_ID and p.device.replace('/dev/tty.', '/dev/cu.') == port
    for p in list_ports.comports()
  )


def read_events(port):
  """([events], fresh) from the board on `port`, or None if it has no touch support."""
  from busytag.esp32 import Esp32Device

  if is_busy_tag(port):
    return None
  try:
    with board.device_lock(), Esp32Device(port) as device:
      return device.events()
  except BusyTagError as error:
    if any(text in str(error) for text in NOT_TOUCH):
      return None
    raise


def check(port, redraw=board.redraw, go=jump.go, read=read_events):
  """Poll `port` once and act on its taps. Returns log lines, or None if the port has no
  touch support. Device errors (port in use by a serial monitor, unplugged) raise."""
  result = read(port)
  if result is None:
    return None
  events, fresh = result
  lines = []
  agents = board.peek()['agents']
  # A board that reset (or was flashed) shows its boot screen; put the agents back
  if fresh and board.ranked(agents):
    error = redraw()
    lines.append(f'display on {port} restarted: ' + (f'not updated: {error}' if error else 'screen redrawn'))
  for event in events:
    if event.get('type') != 'jump':
      continue
    agent = event.get('agent', '')
    entry = agents.get(agent)
    label = entry['label'] if entry else agent
    try:
      warnings = go((entry or {}).get('jump'))
      lines.append(f'jumped to {label}' + ''.join(f' (warning: {w})' for w in warnings))
    except jump.JumpError as error:
      lines.append(f'could not jump to {label}: {error}')
  return lines
