"""`busytag watch` tests: redraw when a display port appears."""

from busytag import watch


def run(port_sets):
  sequence = iter(port_sets)
  redraws = []
  watch.run(
    lambda: redraws.append(1) or None,
    ports=lambda: next(sequence),
    sleep=lambda seconds: None,
    log=lambda line: None,
    polls=len(port_sets),
  )
  return len(redraws)


def test_redraws_when_present_at_start():
  assert run([{'/dev/cu.a'}, {'/dev/cu.a'}]) == 1


def test_redraws_on_each_plug_in():
  assert run([set(), {'/dev/cu.a'}, {'/dev/cu.a'}, set(), {'/dev/cu.a'}]) == 2


def test_redraws_when_a_second_display_appears():
  assert run([{'/dev/cu.a'}, {'/dev/cu.a', '/dev/cu.b'}]) == 2


def test_nothing_plugged_in():
  assert run([set(), set()]) == 0


def test_logs_device_error():
  lines = []
  watch.run(lambda: 'port in use', ports=lambda: {'/dev/cu.a'}, sleep=lambda s: None, log=lines.append, polls=1)
  assert 'not updated: port in use' in lines[0]


def test_expire_runs_about_once_a_minute():
  calls = []
  watch.run(
    lambda: None,
    lambda: calls.append(1) or (0, None),
    ports=lambda: set(),
    sleep=lambda seconds: None,
    log=lambda line: None,
    polls=watch.EXPIRE_EVERY_POLLS * 2,
  )
  assert len(calls) == 2


def test_expire_logs_only_when_agents_dropped():
  lines = []
  results = iter([(0, None), (2, None)])
  watch.run(
    lambda: None,
    lambda: next(results),
    ports=lambda: set(),
    sleep=lambda seconds: None,
    log=lines.append,
    polls=watch.EXPIRE_EVERY_POLLS * 2,
  )
  assert len(lines) == 1 and '2 agent(s) timed out' in lines[0]
