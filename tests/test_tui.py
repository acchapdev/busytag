"""`busytag tui` tests: driven headless with Textual's pilot and a fake device."""

import asyncio
import time

import pytest
from textual.widgets import DataTable, OptionList

from busytag import config, status as board, tui
from busytag.device import BusyTagError


class FakeDevice:
  name = 'Busy Tag'
  port = '/dev/cu.fake'

  def __init__(self, fail=False):
    self.calls = []
    self.fail = fail
    self.level = 50

  def __call__(self):
    if self.fail:
      raise BusyTagError('port in use')
    return self

  def __enter__(self):
    return self

  def __exit__(self, *exc):
    pass

  def info(self):
    return {'firmware': '2.0', 'image': 'plugin1.png', 'brightness': self.level}

  def current_image(self):
    return 'plugin1.png'

  def images(self):
    return [('plugin1.png', 4096), ('cat.gif', 900_000), ('bt_status0.png', 2048)]

  def show_image(self, name):
    self.calls.append(('show', name))

  def fill_display(self, color):
    self.calls.append(('fill', color))

  def solid_color(self, color, leds=127):
    self.calls.append(('solid', color))

  def builtin_patterns(self):
    return [(0, 'Red Pulses'), (5, 'Rainbow')]

  def play_builtin_pattern(self, pattern_id, repeat=255, brightness=100):
    self.calls.append(('pattern', pattern_id, brightness))

  def brightness(self):
    return self.level

  def set_brightness(self, level):
    self.level = level
    self.calls.append(('brightness', level))

  # Used by status pushes after clearing agents
  def query(self, command):
    return '127,0000FE'

  def custom_pattern(self):
    return []

  def stop_pattern(self):
    self.calls.append(('stop',))

  def upload(self, name, data):
    self.calls.append(('upload', name))

  def set_custom_pattern(self, steps):
    pass

  def play_pattern(self, repeat=255):
    pass


@pytest.fixture(autouse=True)
def state_dir(tmp_path, monkeypatch):
  monkeypatch.setenv('BUSYTAG_STATE_DIR', str(tmp_path))
  monkeypatch.setenv('BUSYTAG_CONFIG', str(tmp_path / 'config.toml'))
  return tmp_path


def drive(device, steps):
  """Run the app with `device`, apply `steps(app, pilot)`, return the app."""
  async def main():
    app = tui.BusyTagApp(open_device=device, poll=0.1)
    async with app.run_test() as pilot:
      await app.workers.wait_for_complete()
      await pilot.pause()
      await steps(app, pilot)
      await app.workers.wait_for_complete()
      await pilot.pause()
    return app
  return asyncio.run(main())


async def nothing(app, pilot):
  pass


def test_agents_listed_most_urgent_first():
  device = FakeDevice()
  board.update('claude:a', 'done', 'alpha', open_device=device)
  board.update('opencode:b', 'attention', 'beta', open_device=device)

  async def check(app, pilot):
    table = app.query_one(DataTable)
    assert [table.get_row_at(row)[1] for row in range(table.row_count)] == ['beta', 'alpha']

  drive(device, check)


def test_new_reports_appear_without_restart():
  device = FakeDevice()

  async def check(app, pilot):
    assert app.query_one(DataTable).row_count == 0
    board.update('claude:a', 'working', 'alpha', open_device=device)
    await pilot.pause(0.3)
    assert app.query_one(DataTable).row_count == 1

  drive(device, check)


def test_device_panel_shows_display():
  app = drive(FakeDevice(), nothing)
  assert 'Busy Tag' in app.device_text and 'firmware 2.0' in app.device_text


def test_missing_display_is_reported():
  app = drive(FakeDevice(fail=True), nothing)
  assert 'No display connected' in app.device_text


def test_clear_selected_agent():
  device = FakeDevice()
  board.update('claude:a', 'done', 'alpha', open_device=device)
  board.update('claude:b', 'working', 'beta', open_device=device)

  async def clear(app, pilot):
    await pilot.press('x')

  drive(device, clear)
  assert list(board.peek()['agents']) == ['claude:b']


def test_clear_all_agents():
  device = FakeDevice()
  board.update('claude:a', 'done', 'alpha', open_device=device)

  async def reset(app, pilot):
    await pilot.press('R')

  drive(device, reset)
  assert board.peek()['agents'] == {}


def test_image_picker_hides_status_images_and_shows_choice():
  device = FakeDevice()

  async def pick(app, pilot):
    await pilot.press('i')
    await app.workers.wait_for_complete()
    await pilot.pause()
    options = app.screen.query_one(OptionList)
    assert [options.get_option_at_index(i).id for i in range(options.option_count)] == ['plugin1.png', 'cat.gif']
    await pilot.press('down', 'enter')

  drive(device, pick)
  assert ('show', 'cat.gif') in device.calls


def test_led_color_is_scaled_and_remembered():
  device = FakeDevice()
  config.set_brightness(50)

  async def color(app, pilot):
    await pilot.press('c')
    await pilot.pause()
    await pilot.press(*'FF0000', 'enter')

  drive(device, color)
  assert ('solid', '800000') in device.calls
  assert board.peek()['manual_color'] == 'FF0000'


def test_bad_color_is_rejected():
  device = FakeDevice()

  async def color(app, pilot):
    await pilot.press('f')
    await pilot.pause()
    await pilot.press(*'nope', 'enter')

  drive(device, color)
  assert not [call for call in device.calls if call[0] == 'fill']


def test_pattern_played_at_led_brightness():
  device = FakeDevice()
  config.set_brightness(20)

  async def pick(app, pilot):
    await pilot.press('p')
    await app.workers.wait_for_complete()
    await pilot.pause()
    await pilot.press('down', 'enter')

  drive(device, pick)
  assert ('pattern', 5, 20) in device.calls


def test_brightness_keys():
  device = FakeDevice()

  async def keys(app, pilot):
    await pilot.press('right_square_bracket')
    await app.workers.wait_for_complete()
    await pilot.press('minus')

  drive(device, keys)
  assert ('brightness', 60) in device.calls
  assert config.load()['brightness'] == 90


def test_age():
  assert tui.age(5) == '5s'
  assert tui.age(125) == '2m'
  assert tui.age(3 * 3600 + 7 * 60) == '3h07m'
