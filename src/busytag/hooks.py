"""Turn agent events (JSON on stdin) into status updates.

Sources: Claude Code hooks (registered with "async": true) and the OpenCode plugin in
busytag/integrations/opencode.ts, which forwards OpenCode 2 events. This never blocks the agent. It must never
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


def opencode_update(event):
  """Return (state, detail) for an OpenCode 2 event forwarded by the plugin, or None.

  The plugin sends {type, created, sessionID, directory, data}. Subagent sessions are
  folded into their root session by the plugin, and only their prompts are forwarded.
  """
  name = event.get('type')
  data = event.get('data') or {}
  if name == 'session.execution.started':
    return 'working', ''
  if name == 'session.execution.succeeded':
    return 'done', ''
  if name == 'session.execution.failed':
    return 'error', 'Run failed'
  if name == 'session.execution.interrupted':
    # The user pressed Esc, so they are already looking at it
    return 'idle', ''
  if name == 'permission.asked':
    resources = data.get('resources') or []
    target = f' {resources[0]}' if resources else ''
    return 'attention', f'Permission needed: {data.get("action", "a tool")}{target}'
  if name == 'form.created':
    return 'attention', data.get('title') or 'Question waiting'
  if name in ('permission.replied', 'form.replied', 'form.cancelled'):
    return 'working', ''
  if name == 'session.deleted':
    return 'clear', ''
  return None


def claude_event(event, started):
  """(agent, state, label, detail, timestamp) for a Claude Code hook event, or None."""
  update = claude_update(event)
  if update is None:
    return None
  state, detail = update
  return f'claude:{event.get("session_id", "unknown")}', state, claude_label(event), detail, started


def opencode_event(event, started):
  """(agent, state, label, detail, timestamp) for an OpenCode event, or None."""
  update = opencode_update(event)
  if update is None:
    return None
  state, detail = update
  # The event's own time (ms) orders reports even if the plugin's processes race
  created = event.get('created')
  timestamp = created / 1000 if isinstance(created, (int, float)) else started
  label = Path(event.get('directory') or '').name or 'opencode'
  return f'opencode:{event.get("sessionID", "unknown")}', state, label, detail, timestamp


SOURCES = {'claude': claude_event, 'opencode': opencode_event}


def run(source='claude'):
  # Taken before any waiting on the lock, so concurrent hooks keep their real order
  started = time.time()
  try:
    if source not in SOURCES:
      raise ValueError(f"unknown hook source '{source}'; use one of {', '.join(SOURCES)}")
    event = json.load(sys.stdin)
    report = SOURCES[source](event, started)
    if report is None:
      return
    agent, state, label, detail, timestamp = report
    error = board.update(agent, state, label, detail, timestamp=timestamp)
    if error:
      log(f'{source} {event.get("hook_event_name") or event.get("type")}: device not updated: {error}')
  except Exception:
    log(traceback.format_exc().strip())
