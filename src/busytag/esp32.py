"""Serial transport for an ESP32 display running the busytag firmware (firmware/esp32-c6-lcd).

One JSON object per line each way; every request gets one `{"ok": ...}` reply line.
The firmware draws the status screen itself, so there are no image uploads, and the
board has a single RGB LED instead of the Busy Tag's 7.
"""

import json
import time
import unicodedata

import serial

from busytag.device import BusyTagError

DEVICE_NAME = 'busytag-esp32'
MAX_ROWS = 12
MAX_TEXT = 120

# Busy Tag features this display doesn't have (no image storage, no LED patterns)
UNSUPPORTED = {
  'files', 'images', 'storage', 'current_image', 'show_image', 'upload', 'delete',
  'builtin_patterns', 'play_builtin_pattern', 'custom_pattern', 'set_custom_pattern',
  'play_pattern',
}


def ascii_text(text, limit=MAX_TEXT):
  """The firmware's fonts cover printable ASCII only; '…' becomes '...', 'é' becomes 'e'."""
  text = unicodedata.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode()
  return ' '.join(text.split())[:limit]


class Esp32Device:
  name = 'ESP32 display'
  # status.push lets the firmware draw instead of uploading a rendered PNG
  draws_status = True

  def __init__(self, port=None, connection=None):
    self.port = port
    if connection is not None:
      self.conn = connection
      return
    try:
      # Keep pyserial's default DTR/RTS: lowering DTR before RTS briefly holds RTS high
      # with DTR low, which resets a chip on its built-in USB-Serial/JTAG port
      self.conn = serial.Serial(port, 115200, timeout=0.1, exclusive=True)
    except serial.SerialException as error:
      if 'busy' in str(error).lower() or 'lock' in str(error).lower():
        raise BusyTagError(f'{port} is in use by another program (a serial monitor?).') from error
      raise BusyTagError(f'Cannot open {port}: {error}') from error

  def __enter__(self):
    return self

  def __exit__(self, *exc):
    self.close()

  def __getattr__(self, attribute):
    if attribute in UNSUPPORTED:
      def unsupported(*args, **kwargs):
        raise BusyTagError(f'The ESP32 display has no {attribute.replace("_", " ")} support.')
      return unsupported
    raise AttributeError(attribute)

  def close(self):
    self.conn.close()

  # --- low level -------------------------------------------------------------

  def _lines(self, deadline):
    """Yield complete lines until the deadline."""
    buffer = b''
    while time.monotonic() < deadline:
      buffer += self.conn.readline()
      if buffer.endswith(b'\n'):
        yield buffer.decode(errors='replace').strip()
        buffer = b''

  def request(self, cmd, timeout=3.0, **fields):
    """Send one command; return its reply dict, or raise BusyTagError."""
    self.conn.reset_input_buffer()
    self.conn.write((json.dumps({'cmd': cmd, **fields}) + '\n').encode())
    for line in self._lines(time.monotonic() + timeout):
      # Boot messages from the ROM are plain text; replies are JSON objects
      if not line.startswith('{'):
        continue
      try:
        reply = json.loads(line)
      except ValueError:
        continue
      if not reply.get('ok'):
        raise BusyTagError(f'{cmd} failed: {reply.get("error", "unknown error")}')
      return reply
    raise BusyTagError('Timed out waiting for the ESP32 display to reply')

  def raw(self, command, quiet=0.5, timeout=5.0):
    """Send a raw line (a JSON command); return every line until a reply or silence."""
    self.conn.reset_input_buffer()
    self.conn.write(f'{command}\n'.encode())
    lines = []
    deadline = time.monotonic() + timeout
    while True:
      line = next(self._lines(min(deadline, time.monotonic() + quiet)), None)
      if line is None:
        return lines
      lines.append(line)
      if line.startswith('{"ok"'):
        return lines

  # --- device API ------------------------------------------------------------

  def hello(self, timeout=3.0):
    reply = self.request('hello', timeout)
    if reply.get('device') != DEVICE_NAME:
      raise BusyTagError(f'{self.port} is not running the busytag ESP32 firmware')
    return reply

  def info(self):
    reply = self.hello()
    return {
      'name': reply['device'],
      'board': reply.get('board', ''),
      'firmware': reply.get('fw', ''),
      'screen': f'{reply.get("width")}x{reply.get("height")}',
      'rotation': reply.get('rotation'),
      'brightness': reply.get('brightness'),
      'uptime': f'{reply.get("uptime_ms", 0) // 1000}s',
      'port': self.port,
    }

  def brightness(self):
    return self.request('brightness')['brightness']

  def set_brightness(self, level):
    self.request('brightness', value=level)

  def rotate(self, value=None):
    fields = {} if value is None else {'value': value}
    return self.request('rotate', **fields)['rotation']

  def fill_display(self, color):
    self.request('fill', color=color)

  def solid_color(self, color, leds=127):
    # One LED, so `leds` is ignored
    self.request('led', effect='solid', color=color)

  def stop_pattern(self):
    self.request('led', effect='off')

  def show_status(self, top, rows, led):
    """rows: [(label, state, detail, RRGGBB)] most urgent first; led: {'effect', 'color', 'low'}."""
    rows = [
      [ascii_text(label, 40), state, ascii_text(detail), color]
      for label, state, detail, color in rows[:MAX_ROWS]
    ]
    self.request('status', top=top, rows=rows, led=led)

  def show_idle(self):
    self.request('idle')

  def current_screen(self):
    """What is shown now: {'screen': {'cmd': ..., ...}, 'led': {'effect', 'color', 'low'}}."""
    try:
      reply = self.request('screen')
    except BusyTagError as error:
      # Firmware 0.1.0 has no `screen` command; treat its screen as the idle one
      if 'unknown command' not in str(error):
        raise
      return {'screen': {'cmd': 'idle'}, 'led': {'effect': 'off'}}
    return {'screen': reply['screen'], 'led': reply['led']}

  def restore_screen(self, home):
    """Show a screen saved by current_screen(): the screen first, since `idle` turns the LED off."""
    screen = dict(home['screen'])
    self.request(screen.pop('cmd'), **screen)
    self.request('led', **home['led'])
