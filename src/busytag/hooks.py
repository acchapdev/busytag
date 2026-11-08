"""Turn Claude Code hook events (JSON on stdin) into status updates.

Hooks are registered with "async": true, so this never blocks Claude. It must never
fail loudly either: problems go to hook.log in the state directory and we exit 0.
"""

import json
import os
import sys
import time
import traceback
from pathlib import Path

from busytag import status as board

# notification_type values that mean the user has to act
ATTENTION_NOTIFICATIONS = {
  'permission_prompt',
  'elicitation_dialog',
  'elicitation_url_dialog',
  'agent_needs_input',
}

# Events that mean Claude is busy again (e.g. after a permission prompt was approved)
WORKING_EVENTS = {'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'PostToolUseFailure'}


def claude_update(event):
  """Return (state, detail) for a Claude Code hook event, or None to ignore it."""
  name = event.get('hook_event_name')
  if name in WORKING_EVENTS:
    return 'working', ''
  if name == 'SessionStart':
    return 'idle', ''
  if name == 'PermissionRequest':
    return 'attention', f'Permission needed: {event.get("tool_name", "a tool")}'
  if name == 'Notification':
    if event.get('notification_type') in ATTENTION_NOTIFICATIONS:
      return 'attention', event.get('message', '')
    # idle_prompt and the rest: the Stop event already marked the session done
    return None
  if name == 'Stop':
    # stop_hook_active means a Stop hook made Claude keep going
    return None if event.get('stop_hook_active') else ('done', '')
  if name == 'StopFailure':
    return 'error', 'Stopped on an API error'
  if name == 'SessionEnd':
    return 'clear', ''
  return None


def claude_label(event):
  project = os.environ.get('CLAUDE_PROJECT_DIR') or event.get('cwd') or ''
  return Path(project).name or 'claude'


def log(message):
  try:
    with open(board.state_dir() / 'hook.log', 'a') as handle:
      handle.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} {message}\n')
  except OSError:
    pass


def run(source='claude'):
  # Taken before any waiting on the lock, so concurrent hooks keep their real order
  started = time.time()
  try:
    if source != 'claude':
      raise ValueError(f"unknown hook source '{source}'")
    event = json.load(sys.stdin)
    update = claude_update(event)
    if update is None:
      return
    state, detail = update
    agent = f'claude:{event.get("session_id", "unknown")}'
    error = board.update(agent, state, claude_label(event), detail, timestamp=started)
    if error:
      log(f'{event.get("hook_event_name")}: device not updated: {error}')
  except Exception:
    log(traceback.format_exc().strip())
