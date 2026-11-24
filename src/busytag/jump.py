"""Switch to an agent's terminal, for the "Jump to it" button on a touchscreen display.

The Claude Code hook records the Rex session and pane the agent runs in (`hooks.rex_location`).
Jumping selects that session and tab in the Rex app, focuses the pane, and brings Rex to
the front. Selecting a session is a Rex *client* action, which needs Remote Control turned
on in the Rex app; without it the pane is still focused in the session, but the app may stay
on another session.
"""

import json
import os
import shutil
import subprocess
import sys

# `busytag watch` runs from a LaunchAgent, whose PATH is only /usr/bin:/bin:/usr/sbin:/sbin
SEARCH_PATH = os.pathsep.join([
  os.environ.get('PATH', ''),
  os.path.expanduser('~/.local/bin'),
  '/opt/homebrew/bin',
  '/usr/local/bin',
])
TIMEOUT_SECONDS = 5


class JumpError(Exception):
  pass


def rex_command():
  rex = shutil.which('rex', path=SEARCH_PATH)
  if not rex:
    raise JumpError('rex not found on PATH or in ~/.local/bin')
  return rex


def run_rex(args, run=subprocess.run):
  try:
    result = run([rex_command(), *args], capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
  except subprocess.TimeoutExpired as error:
    raise JumpError(f'rex {args[0]} timed out') from error
  if result.returncode != 0:
    message = (result.stderr or result.stdout).strip().splitlines()
    raise JumpError(f'rex {" ".join(args[:2])} failed: {message[-1] if message else result.returncode}')
  return result.stdout


def go(target, run=subprocess.run):
  """Switch to `target` ({'rex_session', 'rex_block'}). Returns a list of warnings for steps
  that failed but didn't stop the jump; raises JumpError if the pane can't be found."""
  if not target or 'rex_session' not in target or 'rex_block' not in target:
    raise JumpError('no terminal recorded for this agent')
  session, block = target['rex_session'], target['rex_block']
  try:
    window = json.loads(run_rex(['block', 'inspect', '-s', session, block, '--json'], run))['block']['window_id']
  except (ValueError, KeyError) as error:
    raise JumpError('rex block inspect returned no window') from error

  warnings = []
  # Show the session and tab in the app (a client action; fails without Remote Control)
  try:
    run_rex(['do', 'session.select', f'session_id={session}', f'window_id={window}'], run)
  except JumpError as error:
    warnings.append(str(error))
  run_rex(['focus', '-s', session, block], run)
  if sys.platform == 'darwin':
    run(['open', '-a', 'Rex'], capture_output=True, timeout=TIMEOUT_SECONDS)
  return warnings
