"""ESP32 display tests: JSON-lines transport, status push, and device detection (no hardware)."""

import json
from types import SimpleNamespace

import pytest

from busytag import device as device_module, esp32, status as board
from busytag.device import BusyTagError
from busytag.esp32 import Esp32Device, ascii_text

HELLO = {'ok': True, 'device': 'busytag-esp32', 'fw': '0.1.0', 'width': 320, 'height': 172,
         'rotation': 3, 'brightness': 80, 'uptime_ms': 5000}


class FakeSerial:
  """Replies to each written command with the next queued line(s)."""

  def __init__(self, *replies):
    self.replies = list(replies)
    self.sent = []
    self.pending = []
    self.closed = False

  def reset_input_buffer(self):
    pass

  def write(self, data):
    self.sent.append(json.loads(data))
    reply = self.replies.pop(0) if self.replies else []
    self.pending += reply if isinstance(reply, list) else [reply]

  def readline(self):
    if not self.pending:
      return b''
    line = self.pending.pop(0)
    return (line if isinstance(line, str) else json.dumps(line)).encode() + b'\n'

  def close(self):
    self.closed = True


def make(*replies):
  return Esp32Device('/dev/cu.fake', connection=FakeSerial(*replies))


# --- transport ---------------------------------------------------------------

def test_request_skips_boot_log_lines():
  device = make(['ESP-ROM:esp32c6-20220919', 'entry 0x4086b910', HELLO])
  assert device.hello()['fw'] == '0.1.0'


def test_error_reply_raises():
  device = make({'ok': False, 'error': 'unknown command'})
  with pytest.raises(BusyTagError, match='unknown command'):
    device.request('nope')


def test_silence_times_out():
  device = make([])
  with pytest.raises(BusyTagError, match='Timed out'):
    device.request('hello', timeout=0.2)


def test_hello_rejects_other_firmware():
  device = make({'ok': True, 'device': 'something-else'})
  with pytest.raises(BusyTagError, match='not running'):
    device.hello()


def test_busy_tag_only_features_say_so():
  with pytest.raises(BusyTagError, match='no upload support'):
    make().upload('a.png', b'')


def test_ascii_text_keeps_fonts_happy():
  assert ascii_text('Café … done\n now') == 'Cafe ... done now'
  assert len(ascii_text('x' * 500)) == esp32.MAX_TEXT


def test_show_status_sends_ascii_rows_and_led():
  device = make({'ok': True})
  device.show_status('attention', [('café', 'attention', 'Bash(rm …)', 'FF6000')], {'effect': 'pulse'})
  sent = device.conn.sent[0]
  assert sent['cmd'] == 'status'
  assert sent['rows'] == [['cafe', 'attention', 'Bash(rm ...)', 'FF6000']]
  assert sent['led'] == {'effect': 'pulse'}


# --- status push -------------------------------------------------------------

class FakeDrawnDevice:
  draws_status = True

  def __init__(self, home=None):
    self.calls = []
    self.home = home or {'screen': {'cmd': 'idle'}, 'led': {'effect': 'off'}}

  def __call__(self):
    return self

  def __enter__(self):
    return self

  def __exit__(self, *exc):
    pass

  def show_status(self, top, rows, led):
    self.calls.append(('status', top, led))

  def show_idle(self):
    self.calls.append(('idle',))

  def current_screen(self):
    return self.home

  def restore_screen(self, home):
    self.calls.append(('restore', home))


@pytest.fixture(autouse=True)
def state_dir(tmp_path, monkeypatch):
  monkeypatch.setenv('BUSYTAG_STATE_DIR', str(tmp_path))
  monkeypatch.setenv('BUSYTAG_CONFIG', str(tmp_path / 'config.toml'))


def test_working_sends_dimmed_solid_led():
  device = FakeDrawnDevice()
  board.update('claude:s1', 'working', 'alpha', open_device=device)
  assert device.calls == [('status', 'working', {'effect': 'solid', 'color': '401800'})]


def test_attention_pulses_between_full_and_low():
  device = FakeDrawnDevice()
  board.update('claude:s1', 'attention', 'alpha', open_device=device)
  _, _, led = device.calls[0]
  assert led['effect'] == 'pulse'
  assert led['color'] == 'FF6000'
  assert led['low'] != led['color']


def test_same_screen_is_not_pushed_twice_and_idle_returns():
  device = FakeDrawnDevice()
  board.update('a', 'working', 'alpha', open_device=device)
  board.update('a', 'working', 'alpha', open_device=device)
  board.update('a', 'clear', open_device=device)
  board.update('b', 'idle', open_device=device)
  assert [call[0] for call in device.calls] == ['status', 'restore']


def test_home_screen_and_led_come_back():
  home = {'screen': {'cmd': 'fill', 'color': '003366'}, 'led': {'effect': 'solid', 'color': '00FF00', 'low': '000000'}}
  device = FakeDrawnDevice(home)
  board.update('a', 'working', 'alpha', open_device=device)
  device.home = {'screen': {'cmd': 'status'}, 'led': {'effect': 'solid', 'color': '401800'}}
  board.update('b', 'attention', 'beta', open_device=device)
  board.update('a', 'clear', open_device=device)
  board.update('b', 'clear', open_device=device)
  assert device.calls[-1] == ('restore', home)


def test_leftover_status_screen_is_not_home():
  device = FakeDrawnDevice({'screen': {'cmd': 'status'}, 'led': {'effect': 'pulse', 'color': 'FF6000'}})
  board.update('a', 'working', 'alpha', open_device=device)
  board.update('a', 'clear', open_device=device)
  assert device.calls[-1] == ('restore', {'screen': {'cmd': 'idle'}, 'led': {'effect': 'off'}})


def test_state_without_home_falls_back_to_idle():
  device = FakeDrawnDevice()
  with board.locked_state() as state:
    state['drawn'] = True
  board.update('a', 'idle', open_device=device)
  assert device.calls == [('idle',)]


def test_current_screen_and_restore():
  reply = {'ok': True, 'screen': {'cmd': 'fill', 'color': '003366'},
           'led': {'effect': 'solid', 'color': '00FF00', 'low': '000000'}}
  device = make(reply, {'ok': True}, {'ok': True})
  home = device.current_screen()
  device.restore_screen(home)
  assert device.conn.sent[1:] == [
    {'cmd': 'fill', 'color': '003366'},
    {'cmd': 'led', 'effect': 'solid', 'color': '00FF00', 'low': '000000'},
  ]


def test_old_firmware_home_is_idle():
  device = make({'ok': False, 'error': 'unknown command'})
  assert device.current_screen() == {'screen': {'cmd': 'idle'}, 'led': {'effect': 'off'}}


# --- detection ---------------------------------------------------------------

def port(device, vid, pid):
  return SimpleNamespace(device=device, vid=vid, pid=pid)


@pytest.fixture
def opened(monkeypatch):
  """Record which class open_device builds, for which port."""
  calls = []

  class StubDevice:
    def __init__(self, port):
      calls.append(('busytag', port))

  class StubEsp32:
    def __init__(self, port):
      self.port = port
      calls.append(('esp32', port))

    def hello(self, timeout):
      if self.port != '/dev/cu.good':
        raise BusyTagError('no reply')

    def close(self):
      calls.append(('closed', self.port))

  monkeypatch.setattr(device_module, 'Device', StubDevice)
  monkeypatch.setattr(esp32, 'Esp32Device', StubEsp32)
  return calls


def test_busy_tag_wins_when_present(monkeypatch, opened):
  monkeypatch.setattr(device_module.list_ports, 'comports', lambda: [
    port('/dev/cu.good', 0x303A, 0x1001), port('/dev/tty.tag', 0x303A, 0x81DF),
  ])
  device_module.open_device()
  assert opened == [('busytag', '/dev/cu.tag')]


def test_esp32_found_by_hello(monkeypatch, opened):
  monkeypatch.setattr(device_module.list_ports, 'comports', lambda: [
    port('/dev/cu.other', 0x303A, 0x1001), port('/dev/cu.good', 0x303A, 0x1001),
    port('/dev/cu.usbserial', 0x10C4, 0xEA60),
  ])
  device = device_module.open_device()
  assert device.port == '/dev/cu.good'
  assert opened == [('esp32', '/dev/cu.other'), ('closed', '/dev/cu.other'), ('esp32', '/dev/cu.good')]


def test_nothing_found(monkeypatch, opened):
  monkeypatch.setattr(device_module.list_ports, 'comports', lambda: [])
  with pytest.raises(BusyTagError, match='No Busy Tag or busytag ESP32'):
    device_module.open_device()
