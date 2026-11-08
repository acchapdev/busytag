"""Status board and hook mapping tests (no hardware)."""

import io
import json

import pytest
from PIL import Image

from busytag import config, hooks, status as board
from busytag.device import BusyTagError
from busytag.render import render_status


class FakeDevice:
  def __init__(self, image='plugin1.png', color='0000FE', fail=False):
    self.calls = []
    self.image = image
    self.color = color
    self.fail = fail

  def __call__(self):
    if self.fail:
      raise BusyTagError('port in use')
    return self

  def __enter__(self):
    return self

  def __exit__(self, *exc):
    pass

  def query(self, command):
    return f'127,{self.color}'

  def current_image(self):
    return self.image

  def custom_pattern(self):
    return [[127, '1291AF', 100, 0], [127, 'FF0000', 100, 0]]

  def upload(self, name, data):
    self.calls.append(('upload', name))

  def show_image(self, name):
    self.image = name
    self.calls.append(('show', name))

  def solid_color(self, color, leds=127):
    self.calls.append(('solid', color))

  def set_custom_pattern(self, steps):
    self.calls.append(('pattern', len(steps)))

  def play_pattern(self, repeat=255):
    self.calls.append(('play', repeat))

  def stop_pattern(self):
    self.calls.append(('stop',))


@pytest.fixture(autouse=True)
def state_dir(tmp_path, monkeypatch):
  monkeypatch.setenv('BUSYTAG_STATE_DIR', str(tmp_path))
  monkeypatch.setenv('BUSYTAG_CONFIG', str(tmp_path / 'config.toml'))
  return tmp_path


SETTINGS = {
  'brightness': 100,
  'agent_colors': {'claude': 'FF6000', 'opencode': '0060FF', 'default': 'FFFFFF'},
}


def saved(state_dir):
  return json.loads((state_dir / 'state.json').read_text())


# --- apply_update / summarize ------------------------------------------------

def test_most_urgent_agent_wins():
  state = {'agents': {}}
  board.apply_update(state, 'a', 'working', 'alpha', now=100)
  board.apply_update(state, 'b', 'attention', 'beta', 'Permission needed', now=101)
  board.apply_update(state, 'c', 'done', 'gamma', now=102)
  top, rows = board.summarize(state['agents'], SETTINGS)
  assert top == 'attention'
  assert [row[0] for row in rows] == ['beta', 'gamma', 'alpha']


def test_idle_agents_are_not_shown():
  state = {'agents': {}}
  board.apply_update(state, 'a', 'idle', now=100)
  assert board.summarize(state['agents'], SETTINGS) == ('idle', [])


def test_older_report_does_not_overwrite_newer():
  state = {'agents': {}}
  board.apply_update(state, 'a', 'attention', timestamp=200, now=200)
  assert not board.apply_update(state, 'a', 'working', timestamp=199, now=201)
  assert state['agents']['a']['state'] == 'attention'


def test_clear_removes_agent():
  state = {'agents': {}}
  board.apply_update(state, 'a', 'done', now=100)
  board.apply_update(state, 'a', 'clear', now=101)
  assert state['agents'] == {}


def test_stale_agents_are_pruned():
  state = {'agents': {}}
  board.apply_update(state, 'old', 'done', now=0)
  board.apply_update(state, 'new', 'working', now=board.STALE_SECONDS + 1)
  assert list(state['agents']) == ['new']


def test_label_is_kept_when_not_repeated():
  state = {'agents': {}}
  board.apply_update(state, 'a', 'working', 'alpha', now=100)
  board.apply_update(state, 'a', 'done', now=101)
  assert state['agents']['a']['label'] == 'alpha'


def test_unknown_state_rejected():
  with pytest.raises(ValueError):
    board.apply_update({'agents': {}}, 'a', 'sleeping')


# --- update: device pushes ---------------------------------------------------

def test_first_update_saves_home_and_shows_status(state_dir):
  device = FakeDevice()
  board.update('a', 'working', 'alpha', open_device=device)
  assert device.calls == [
    # Agent 'a' has no listed type, so it gets the default white, dimmed to 25% for working
    ('upload', 'bt_status0.png'), ('show', 'bt_status0.png'), ('stop',), ('solid', '404040'),
  ]
  assert saved(state_dir)['home'] == {
    'image': 'plugin1.png',
    'color': '0000FE',
    'pattern': [[127, '1291AF', 100, 0], [127, 'FF0000', 100, 0]],
  }


def test_same_screen_is_not_pushed_again():
  device = FakeDevice()
  board.update('a', 'working', 'alpha', open_device=device)
  device.calls.clear()
  board.update('a', 'working', 'alpha', open_device=device)
  assert device.calls == []


def test_status_files_alternate():
  device = FakeDevice()
  board.update('a', 'working', 'alpha', open_device=device)
  board.update('a', 'done', open_device=device)
  board.update('a', 'working', open_device=device)
  uploads = [call[1] for call in device.calls if call[0] == 'upload']
  assert uploads == ['bt_status0.png', 'bt_status1.png', 'bt_status0.png']


def test_attention_plays_pulse_pattern():
  device = FakeDevice()
  board.update('a', 'attention', 'alpha', 'Permission needed', open_device=device)
  assert device.calls[-2:] == [('pattern', 2), ('play', 255)]


def test_last_agent_leaving_restores_home(state_dir):
  device = FakeDevice()
  board.update('a', 'attention', 'alpha', open_device=device)
  device.calls.clear()
  board.update('a', 'clear', open_device=device)
  assert device.calls == [('stop',), ('pattern', 2), ('show', 'plugin1.png'), ('solid', '0000FE')]
  assert 'home' not in saved(state_dir)


def test_leftover_status_image_is_not_saved_as_home(state_dir):
  board.update('a', 'working', open_device=FakeDevice(image='bt_status1.png'))
  assert saved(state_dir)['home']['image'] == 'def.png'


def test_device_error_keeps_report_and_retries(state_dir):
  error = board.update('a', 'done', 'alpha', open_device=FakeDevice(fail=True))
  assert 'port in use' in error
  assert saved(state_dir)['agents']['a']['state'] == 'done'
  device = FakeDevice()
  assert board.update('b', 'idle', open_device=device) is None
  assert ('show', 'bt_status0.png') in device.calls


def test_reset_restores_home(state_dir):
  device = FakeDevice()
  board.update('a', 'done', open_device=device)
  board.update('b', 'working', open_device=device)
  board.reset(open_device=device)
  assert saved(state_dir)['agents'] == {}
  assert device.image == 'plugin1.png'


# --- rendering ---------------------------------------------------------------

def test_render_is_display_sized_png():
  rows = [('busytag', 'attention', 'Claude needs your permission to use Bash', 'FF6000')]
  rows += [(f'project-{i}', 'working', '', '0060FF') for i in range(8)]
  image = Image.open(io.BytesIO(render_status('attention', rows)))
  assert (image.format, image.size) == ('PNG', (240, 280))


# --- Claude hook mapping -----------------------------------------------------

@pytest.mark.parametrize('event, expected', [
  ({'hook_event_name': 'UserPromptSubmit'}, ('working', '')),
  ({'hook_event_name': 'PostToolUse'}, ('working', '')),
  ({'hook_event_name': 'Notification', 'notification_type': 'permission_prompt',
    'message': 'Claude needs your permission to use Bash'},
   ('attention', 'Claude needs your permission to use Bash')),
  ({'hook_event_name': 'Notification', 'notification_type': 'idle_prompt'}, None),
  ({'hook_event_name': 'PermissionRequest', 'tool_name': 'Bash'}, ('attention', 'Permission needed: Bash')),
  ({'hook_event_name': 'Stop', 'stop_hook_active': False}, ('done', '')),
  ({'hook_event_name': 'Stop', 'stop_hook_active': True}, None),
  ({'hook_event_name': 'StopFailure'}, ('error', 'Stopped on an API error')),
  ({'hook_event_name': 'SessionEnd', 'reason': 'prompt_input_exit'}, ('clear', '')),
  ({'hook_event_name': 'SubagentStop'}, None),
])
def test_claude_event_mapping(event, expected):
  assert hooks.claude_update(event) == expected


def test_label_prefers_project_dir(monkeypatch):
  monkeypatch.setenv('CLAUDE_PROJECT_DIR', '/Users/me/projects/busytag')
  assert hooks.claude_label({'cwd': '/tmp/elsewhere'}) == 'busytag'


def test_hook_never_raises_on_bad_input(monkeypatch, state_dir):
  monkeypatch.setattr('sys.stdin', io.StringIO('not json'))
  hooks.run('claude')
  assert 'JSONDecodeError' in (state_dir / 'hook.log').read_text()


# --- agent colors and LED brightness ----------------------------------------

def test_rows_carry_agent_type_color():
  state = {'agents': {}}
  board.apply_update(state, 'claude:s1', 'working', 'alpha', now=100)
  board.apply_update(state, 'opencode:s2', 'done', 'beta', now=101)
  board.apply_update(state, 'build', 'working', 'gamma', now=102)
  _, rows = board.summarize(state['agents'], SETTINGS)
  assert [(row[0], row[3]) for row in rows] == [('beta', '0060FF'), ('gamma', 'FFFFFF'), ('alpha', 'FF6000')]


@pytest.mark.parametrize('top, expected', [
  ('done', ('solid', 'FF6000')),
  ('working', ('solid', '401800')),
  ('error', ('solid', 'FF0000')),
  ('attention', ('pattern', [(127, 'FF6000', 150, 10), (127, '1F0C00', 150, 10)])),
])
def test_led_plan_uses_agent_color(top, expected):
  assert board.led_plan(top, 'FF6000', 100) == expected


def test_led_plan_scales_by_brightness():
  assert board.led_plan('done', 'FF6000', 50) == ('solid', '803000')
  assert board.led_plan('error', 'FF6000', 50) == ('solid', '800000')


def test_brightness_change_repushes_status():
  device = FakeDevice()
  board.update('claude:s1', 'done', 'alpha', open_device=device)
  config.set_brightness(50)
  device.calls.clear()
  assert board.apply_brightness(open_device=device) == ('status', None)
  assert device.calls[-1] == ('solid', '803000')


def test_brightness_change_redoes_manual_color_when_idle():
  device = FakeDevice()
  board.remember_led_color('00FF00')
  config.set_brightness(20)
  assert board.apply_brightness(open_device=device) == ('color', None)
  assert device.calls == [('solid', '003300')]


def test_brightness_change_with_nothing_to_redo():
  assert board.apply_brightness(open_device=FakeDevice()) == (None, None)


def test_status_file_avoids_image_on_screen_even_if_state_was_reset():
  # Another process (or a reset state file) left bt_status0.png on screen
  device = FakeDevice(image='bt_status0.png')
  board.update('a', 'working', open_device=device)
  assert ('upload', 'bt_status1.png') in device.calls
