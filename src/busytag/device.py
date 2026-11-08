"""Serial transport for a Busy Tag running firmware 2.x.

Reply rules, verified on the device (see DEVICE.md):
  - Single-value queries reply with one `+PREFIX:value` line and no `OK`.
  - List queries reply with `+PREFIX:` lines followed by `OK`.
  - Set/action commands reply `OK` or `ERROR:<code>`.
  - `+evn:` / `+log:` lines can arrive at any time, even after `OK`, and are skipped.
"""

import time

import serial
from serial.tools import list_ports

VENDOR_ID = 0x303A
PRODUCT_ID = 0x81DF
BAUD_RATE = 460800

ERROR_MESSAGES = {
  0: 'unknown error',
  1: 'unknown command',
  2: 'invalid argument',
  3: 'file not found',
  4: 'invalid size',
  5: 'storage not mounted',
  6: 'file list error',
  7: 'storage info error',
  8: 'memory allocation error',
  12: 'file delete error',
  13: 'file reception timeout',
}


class BusyTagError(Exception):
  pass


class DeviceError(BusyTagError):
  def __init__(self, command, code):
    self.command = command
    self.code = code
    message = ERROR_MESSAGES.get(code, 'unrecognized error')
    super().__init__(f'{command} failed: ERROR:{code} ({message})')


def find_port():
  for port in list_ports.comports():
    if port.vid == VENDOR_ID and port.pid == PRODUCT_ID:
      # macOS lists both tty.* and cu.*; cu.* doesn't wait for carrier detect
      return port.device.replace('/dev/tty.', '/dev/cu.')
  raise BusyTagError('No Busy Tag found. Is it plugged in with a data cable?')


class Device:
  def __init__(self, port=None, connection=None):
    if connection is not None:
      self.conn = connection
      return
    port = port or find_port()
    try:
      self.conn = serial.Serial(port, BAUD_RATE, timeout=0.1, exclusive=True)
    except serial.SerialException as error:
      if 'busy' in str(error).lower() or 'lock' in str(error).lower():
        raise BusyTagError(
          f'{port} is in use by another program. Quit the Busy Tag app and try again.'
        ) from error
      raise BusyTagError(f'Cannot open {port}: {error}') from error

  def __enter__(self):
    return self

  def __exit__(self, *exc):
    self.close()

  def close(self):
    self.conn.close()

  # --- low level -------------------------------------------------------------

  def _send(self, command):
    # Drop late events from the previous command so they can't be read as replies
    self.conn.reset_input_buffer()
    self.conn.write(f'{command}\r\n'.encode())

  def _read_line(self, deadline):
    buffer = b''
    while time.monotonic() < deadline:
      byte = self.conn.read(1)
      if not byte:
        continue
      if byte == b'\n':
        return buffer.decode(errors='replace').strip()
      buffer += byte
      # The upload prompt `>` may not be followed by a newline
      if buffer == b'>':
        return '>'
    raise BusyTagError('Timed out waiting for the device to reply')

  def _replies(self, command, timeout):
    """Yield meaningful reply lines; raise on ERROR."""
    deadline = time.monotonic() + timeout
    while True:
      line = self._read_line(deadline)
      if not line or line.startswith(('+evn:', '+log:')):
        continue
      if line.startswith('ERROR:'):
        raise DeviceError(command, int(line.split(':', 1)[1] or 0))
      yield line

  # --- command forms ---------------------------------------------------------

  def run(self, command, timeout=3.0):
    """Send a set/action command and wait for OK."""
    self._send(command)
    for line in self._replies(command, timeout):
      if line == 'OK':
        return

  def query(self, command, timeout=3.0):
    """Send a single-value query; return the text after `+PREFIX:`."""
    self._send(command)
    for line in self._replies(command, timeout):
      if line.startswith('+'):
        return line.split(':', 1)[1]

  def query_list(self, command, timeout=5.0):
    """Send a list query; return the value of every `+PREFIX:` line before OK."""
    self._send(command)
    values = []
    for line in self._replies(command, timeout):
      if line == 'OK':
        return values
      if line.startswith('+'):
        values.append(line.split(':', 1)[1])

  def raw(self, command, quiet=0.5, timeout=5.0):
    """Send anything; return every line (events included) until OK, ERROR or silence."""
    self._send(command)
    lines = []
    deadline = time.monotonic() + timeout
    while True:
      try:
        line = self._read_line(min(deadline, time.monotonic() + quiet))
      except BusyTagError:
        return lines
      if line:
        lines.append(line)
      if line == 'OK' or line.startswith('ERROR:'):
        return lines

  # --- device API ------------------------------------------------------------

  def info(self):
    fields = {
      'name': 'AT+GDN',
      'manufacturer': 'AT+GMN',
      'id': 'AT+GID',
      'firmware': 'AT+GFV',
      'hardware': 'AT+GHV',
      'firmware_built': 'AT+GESPCT',
      'chip': 'AT+GCHI',
      'temperature_c': 'AT+GTEMP',
      'storage_total': 'AT+GTSS',
      'storage_free': 'AT+GFSS',
      'image': 'AT+SP?',
      'brightness': 'AT+DB?',
    }
    return {key: self.query(command) for key, command in fields.items()}

  def files(self):
    """Return [(name, type, size)] for every file on the device."""
    result = []
    for value in self.query_list('AT+GFL'):
      name, kind, size = value.rsplit(',', 2)
      result.append((name, kind, int(size)))
    return result

  def images(self):
    """Return [(name, size)] for every displayable image."""
    result = []
    for value in self.query_list('AT+GPL'):
      name, size = value.rsplit(',', 1)
      result.append((name, int(size)))
    return result

  def storage(self):
    return int(self.query('AT+GTSS')), int(self.query('AT+GFSS'))

  def current_image(self):
    return self.query('AT+SP?')

  def show_image(self, name):
    self.run(f'AT+SP={name}')

  def fill_display(self, color):
    self.run(f'AT+DC={color}')

  def brightness(self):
    return int(self.query('AT+DB?'))

  def set_brightness(self, level):
    self.run(f'AT+DB={level}')

  def solid_color(self, color, leds=127):
    self.run(f'AT+SC={leds},{color}')

  def builtin_patterns(self):
    """Return [(id, name)] of the device's built-in LED patterns."""
    result = []
    for value in self.query_list('AT+GDPL'):
      pattern_id, name = value.split(',', 1)
      result.append((int(pattern_id), name))
    return result

  def play_builtin_pattern(self, pattern_id, repeat=255):
    # AT+DP loads the built-in into the custom-pattern slot; AT+PP plays that slot
    self.run(f'AT+DP={pattern_id}')
    self.run(f'AT+PP=1,{repeat}')

  def custom_pattern(self):
    """Return [(leds, color, speed, delay)] of the stored pattern."""
    steps = []
    for value in self.query_list('AT+CP?'):
      leds, color, speed, delay = value.split(',')
      steps.append((int(leds), color, int(speed), int(delay)))
    return steps

  def set_custom_pattern(self, steps):
    # AT+CP=<n> with a `>` prompt drops steps on fw 2.0; AT+CPD takes them in one
    # line, separated by a literal backslash-r backslash-n (verified on the device)
    body = '\\r\\n'.join(f'+CP:{leds},{color},{speed},{delay}' for leds, color, speed, delay in steps)
    self.run(f'AT+CPD={body}')

  def play_pattern(self, repeat=255):
    self.run(f'AT+PP=1,{repeat}')

  def stop_pattern(self):
    self.run('AT+PP=0,0')

  def upload(self, name, data):
    total, free = self.storage()
    existing = dict(self.images()).get(name, 0)
    if len(data) > free + existing:
      raise BusyTagError(
        f'Not enough space: {name} is {len(data):,} bytes, {free:,} bytes free'
      )
    self._send(f'AT+UF={name},{len(data)}')
    deadline = time.monotonic() + 5.0
    while self._read_line(deadline) != '>':
      pass
    chunk_size = 4096
    for start in range(0, len(data), chunk_size):
      self.conn.write(data[start:start + chunk_size])
    self.conn.flush()
    # Flash writes are slow; allow ~1 s per 20 KB on top of a base wait
    for line in self._replies('AT+UF', 10.0 + len(data) / 20_000):
      if line == 'OK':
        return

  def delete(self, name):
    """Delete a file. Returns the image switched to, if `name` was on screen."""
    # The device refuses (ERROR:0) to delete the image it is showing
    replacement = None
    if self.current_image() == name:
      others = [image for image, _ in self.images() if image != name]
      if others:
        replacement = 'def.png' if 'def.png' in others else others[0]
        self.show_image(replacement)
    self.run(f'AT+DF={name}')
    return replacement
