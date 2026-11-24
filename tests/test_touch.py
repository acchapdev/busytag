"""Touchscreen display tests: rows with agent IDs, the events command, jump targets from
the hook, tap handling in `busytag watch`, and the Rex jump itself (no hardware)."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from busytag import device as device_module, esp32, hooks, jump, status as board, touch, watch
from busytag.device import BusyTagError

from test_esp32 import make


@pytest.fixture(autouse=True)
def state_dir(tmp_path, monkeypatch):
  monkeypatch.setenv('BUSYTAG_STATE_DIR', str(tmp_path))
  monkeypatch.setenv('BUSYTAG_CONFIG', str(tmp_path / 'config.toml'))
  return tmp_path


REX = {'rex_session': 'session:1', 'rex_block': 'block:1'}


# --- transport ---------------------------------------------------------------

def test_show_status_keeps_id_age_and_jump_fields():
  device = make({'ok': True})
  device.show_status('working', [('café', 'working', '', 'FF6000', 'claude:s1', 75, True)], {'effect': 'off'})
  assert device.conn.sent[0]['rows'] == [['cafe', 'working', '', 'FF6000', 'claude:s1', 75, True]]


def test_events_returns_taps_and_fresh_flag():
  device = make({'ok': True, 'events': [{'type': 'jump', 'agent': 'claude:s1'}], 'fresh': True})
  assert device.events() == ([{'type': 'jump', 'agent': 'claude:s1'}], True)


def test_events_is_none_without_touch_firmware():
  device = make({'ok': False, 'error': 'unknown command'})
  assert device.events() is None


def test_ch340_port_is_asked_hello(monkeypatch):
  opened = []

  class StubEsp32:
    def __init__(self, port):
      self.port = port
      opened.append(port)

    def hello(self, timeout):
      pass

  monkeypatch.setattr(esp32, 'Esp32Device', StubEsp32)
  monkeypatch.setattr(device_module.list_ports, 'comports', lambda: [
    SimpleNamespace(device='/dev/tty.wchusbserial110', vid=0x1A86, pid=0x7523),
    SimpleNamespace(device='/dev/cu.wchusbserial110', vid=0x1A86, pid=0x7523),
  ])
  assert device_module.open_device().port == '/dev/cu.wchusbserial110'
  assert opened == ['/dev/cu.wchusbserial110']


# --- state and push ----------------------------------------------------------

class RowRecorder:
  draws_status = True

  def __init__(self):
    self.rows = []

  def __call__(self):
    return self

  def __enter__(self):
    return self

  def __exit__(self, *exc):
    pass

  def current_screen(self):
    return {'screen': {'cmd': 'idle'}, 'led': {'effect': 'off'}}

  def show_status(self, top, rows, led):
    self.rows.append(rows)


def test_push_sends_agent_id_age_and_jump(monkeypatch):
  monkeypatch.setattr(board.time, 'time', lambda: 1000.0)
  device = RowRecorder()
  board.update('claude:a', 'working', 'alpha', timestamp=900.0, open_device=device, jump=REX)
  board.update('claude:b', 'attention', 'beta', timestamp=990.0, open_device=device)
  assert [row[4:] for row in device.rows[-1]] == [('claude:b', 10, False), ('claude:a', 100, True)]


def test_report_without_jump_keeps_earlier_target():
  state = {'agents': {}}
  board.apply_update(state, 'claude:a', 'working', 'alpha', now=1.0, jump=REX)
  board.apply_update(state, 'claude:a', 'done', now=2.0)
  assert state['agents']['claude:a']['jump'] == REX


def test_hook_records_rex_location(monkeypatch):
  monkeypatch.setenv('REX_SESSION', 'session:1')
  monkeypatch.setenv('REX_BLOCK', 'block:1')
  event = {'hook_event_name': 'Stop', 'session_id': 's1', 'cwd': '/x/proj'}
  assert hooks.claude_event(event, started=5)[5] == REX


def test_hook_outside_rex_has_no_jump(monkeypatch):
  monkeypatch.delenv('REX_SESSION', raising=False)
  monkeypatch.delenv('REX_BLOCK', raising=False)
  assert hooks.rex_location() is None


# --- touch.check -------------------------------------------------------------

def test_jump_event_calls_go_with_target():
  board.update('claude:a', 'attention', 'alpha', open_device=lambda: (_ for _ in ()).throw(BusyTagError('x')), jump=REX)
  targets = []
  lines = touch.check(
    '/dev/cu.x', read=lambda port: ([{'type': 'jump', 'agent': 'claude:a'}], False),
    go=lambda target: targets.append(target) or [],
  )
  assert targets == [REX]
  assert lines == ['jumped to alpha']


def test_jump_failure_is_logged():
  def fail(target):
    raise jump.JumpError('no terminal recorded for this agent')

  lines = touch.check('/dev/cu.x', read=lambda port: ([{'type': 'jump', 'agent': 'gone'}], False), go=fail)
  assert lines == ['could not jump to gone: no terminal recorded for this agent']


def test_fresh_board_is_redrawn_only_with_active_agents():
  redraws = []
  read = lambda port: ([], True)
  assert touch.check('/dev/cu.x', read=read, redraw=lambda: redraws.append(1)) == []
  board.update('claude:a', 'working', 'alpha', open_device=lambda: (_ for _ in ()).throw(BusyTagError('x')))
  lines = touch.check('/dev/cu.x', read=read, redraw=lambda: redraws.append(1))
  assert redraws == [1] and 'restarted' in lines[0]


def test_port_without_touch_returns_none():
  assert touch.check('/dev/cu.x', read=lambda port: None) is None


# --- watch -------------------------------------------------------------------

def run_watch(touch_fn, port_sets):
  lines = []
  sequence = iter(port_sets)
  watch.run(
    lambda: None, ports=lambda: next(sequence), sleep=lambda s: None,
    log=lines.append, polls=len(port_sets), touch=touch_fn,
  )
  return lines


def test_watch_polls_every_loop_and_logs_lines():
  calls = []
  lines = run_watch(lambda port: calls.append(port) or ['jumped to alpha'], [{'/dev/cu.a'}] * 3)
  assert calls == ['/dev/cu.a'] * 3
  assert sum('jumped to alpha' in line for line in lines) == 3


def test_watch_stops_polling_a_port_without_touch_until_replugged():
  calls = []
  run_watch(lambda port: calls.append(port) or None, [{'/dev/cu.a'}, {'/dev/cu.a'}, set(), {'/dev/cu.a'}])
  assert calls == ['/dev/cu.a', '/dev/cu.a']


def test_watch_logs_the_same_poll_error_once():
  def busy(port):
    raise BusyTagError('/dev/cu.a is in use by another program')

  lines = run_watch(busy, [{'/dev/cu.a'}] * 3)
  assert sum('touch poll' in line for line in lines) == 1


# --- jump.go -----------------------------------------------------------------

def fake_rex(fail=()):
  calls = []

  def run(args, **kwargs):
    calls.append(args)
    name = args[1] if args[0].endswith('rex') else args[0]
    if name in fail:
      return subprocess.CompletedProcess(args, 1, '', f'{name}: Remote Control is off')
    if args[1:3] == ['block', 'inspect']:
      return subprocess.CompletedProcess(args, 0, json.dumps({'block': {'window_id': 'window:1'}}), '')
    return subprocess.CompletedProcess(args, 0, '', '')

  return calls, run


@pytest.fixture
def rex_on_path(monkeypatch):
  monkeypatch.setattr(jump.shutil, 'which', lambda name, path=None: '/bin/rex')


def test_go_selects_session_and_focuses_pane(rex_on_path):
  calls, run = fake_rex()
  assert jump.go(REX, run=run) == []
  # The pane is looked up in its own session; without -s, rex searches only the caller's session
  assert ['/bin/rex', 'block', 'inspect', '-s', 'session:1', 'block:1', '--json'] in calls
  assert ['/bin/rex', 'do', 'session.select', 'session_id=session:1', 'window_id=window:1'] in calls
  assert ['/bin/rex', 'focus', '-s', 'session:1', 'block:1'] in calls


def test_go_still_focuses_when_client_action_is_refused(rex_on_path):
  calls, run = fake_rex(fail=('do',))
  warnings = jump.go(REX, run=run)
  assert 'Remote Control is off' in warnings[0]
  assert ['/bin/rex', 'focus', '-s', 'session:1', 'block:1'] in calls


def test_go_without_target_raises():
  with pytest.raises(jump.JumpError, match='no terminal'):
    jump.go(None)
