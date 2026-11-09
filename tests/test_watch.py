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
