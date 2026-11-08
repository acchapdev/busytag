"""Device tests against a fake serial port that replays real fw 2.0 replies."""

import pytest

from busytag.colors import parse_color, parse_leds
from busytag.device import BusyTagError, Device, DeviceError

# Replies captured from the real device (firmware 2.0), including late events
REPLIES = {
  'AT+GFV': b'+FV:2.0\r\n',
  'AT+GTSS': b'+TSS:3080192\r\n',
  'AT+GFSS': b'+FSS:942080\r\n',
  'AT+SP?': b'+SP:plugin1.png\r\n',
  'AT+DB=50': b'OK\r\n',
  'AT+SC=127,00FF00': b'+evn:PP,0\r\nOK\r\n',
  'AT+SP=def.png': b'OK\r\n+evn:SP,def.png\r\n\r\n',
  'AT+SP=nope.png': b'ERROR:3\r\n',
  'AT+XYZZY': b'ERROR:1\r\n',
  'AT+GPL': b"+PL:plugin1.png,14699\r\n+PL:Let's_talk_7zgg4pkr.png,2073\r\nOK\r\n",
  'AT+GFL': b'+FL:readme.txt,txt,120\r\n+FL:a,b.png,png,5\r\nOK\r\n',
  'AT+GDPL': b'+DPL:0,Default\r\n+DPL:17,Red Pulses\r\nOK\r\n',
  'AT+DP=17': b'OK\r\n',
  'AT+PP=1,3': b'+evn:PP,1\r\nOK\r\n',
  'AT+CP?': b'+CP:127,1291AF,100,0\r\n+CP:127,FF0000,100,0\r\nOK\r\n',
  'AT+UF=x.png,10': b'>\r\n',
  'AT+CPD=+CP:127,1291AF,100,0\\r\\n+CP:127,FF0000,100,0': b'+evn:PP,0\r\nOK\r\n',
  'AT+DF=Let\'s_talk_7zgg4pkr.png': b'OK\r\n',
  'AT+DF=plugin1.png': b'OK\r\n',
  'AT+SP=Let\'s_talk_7zgg4pkr.png': b'OK\r\n+evn:SP,Let\'s_talk_7zgg4pkr.png\r\n',
}


class FakeSerial:
  def __init__(self, replies):
    self.replies = replies
    self.buffer = b''
    self.written = []
    self.pending = b''
    self.upload_remaining = 0

  def reset_input_buffer(self):
    self.buffer = b''

  def write(self, data):
    self.written.append(data)
    if self.upload_remaining:
      self.upload_remaining -= len(data)
      if self.upload_remaining <= 0:
        self.buffer += b'\r\nOK\r\n'
      return
    self.pending += data
    while b'\r\n' in self.pending:
      line, self.pending = self.pending.split(b'\r\n', 1)
      self._handle(line.decode())

  def _handle(self, line):
    self.buffer += self.replies.get(line, b'ERROR:1\r\n')
    if line.startswith('AT+UF='):
      self.upload_remaining = int(line.rsplit(',', 1)[1])

  def read(self, size=1):
    data, self.buffer = self.buffer[:size], self.buffer[size:]
    return data

  def flush(self):
    pass

  def close(self):
    pass


@pytest.fixture
def device():
  return Device(connection=FakeSerial(REPLIES))


def test_single_value_query_has_no_ok(device):
  assert device.query('AT+GFV') == '2.0'


def test_list_query_skips_events_and_ends_at_ok(device):
  assert device.images() == [('plugin1.png', 14699), ("Let's_talk_7zgg4pkr.png", 2073)]


def test_file_names_containing_commas(device):
  assert device.files() == [('readme.txt', 'txt', 120), ('a,b.png', 'png', 5)]


def test_set_command_skips_event_before_ok(device):
  device.solid_color('00FF00')


def test_late_event_is_not_read_as_next_reply(device):
  device.show_image('def.png')
  assert device.current_image() == 'plugin1.png'


def test_error_code_raises_with_meaning(device):
  with pytest.raises(DeviceError, match='file not found') as error:
    device.show_image('nope.png')
  assert error.value.code == 3


def test_unknown_command_raises(device):
  with pytest.raises(DeviceError):
    device.run('AT+XYZZY')


def test_builtin_pattern_loads_then_plays(device):
  device.play_builtin_pattern(17, repeat=3)
  assert device.conn.written[-2:] == [b'AT+DP=17\r\n', b'AT+PP=1,3\r\n']


def test_custom_pattern_round_trip(device):
  steps = device.custom_pattern()
  assert steps == [(127, '1291AF', 100, 0), (127, 'FF0000', 100, 0)]
  device.set_custom_pattern(steps)


def test_delete_other_image_keeps_screen(device):
  assert device.delete("Let's_talk_7zgg4pkr.png") is None


def test_delete_image_on_screen_switches_first(device):
  assert device.delete('plugin1.png') == "Let's_talk_7zgg4pkr.png"
  sent = [data for data in device.conn.written if data.startswith(b'AT+SP=') or data.startswith(b'AT+DF=')]
  assert sent == [b"AT+SP=Let's_talk_7zgg4pkr.png\r\n", b'AT+DF=plugin1.png\r\n']


def test_upload_sends_bytes_after_prompt(device):
  device.upload('x.png', b'0123456789')
  assert b''.join(device.conn.written).endswith(b'AT+UF=x.png,10\r\n0123456789')


def test_upload_refuses_when_storage_full(device):
  with pytest.raises(BusyTagError, match='Not enough space'):
    device.upload('big.gif', b'x' * 1_000_000)


def test_raw_returns_all_lines(device):
  assert device.raw('AT+SC=127,00FF00') == ['+evn:PP,0', 'OK']


@pytest.mark.parametrize('value, expected', [
  ('red', 'FF0000'), ('#00ff00', '00FF00'), ('abc', 'AABBCC'), ('Off', '000000'),
])
def test_parse_color(value, expected):
  assert parse_color(value) == expected


def test_parse_color_rejects_garbage():
  with pytest.raises(ValueError):
    parse_color('chartreuse-ish')


@pytest.mark.parametrize('value, expected', [
  ('all', 127), ('1', 1), ('7', 64), ('1,4,7', 73), ('96', 96),
])
def test_parse_leds(value, expected):
  assert parse_leds(value) == expected


def test_parse_leds_rejects_out_of_range():
  with pytest.raises(ValueError):
    parse_leds('8,9')
