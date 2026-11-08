"""Draw the 240x280 status screen."""

import io

from PIL import Image, ImageDraw, ImageFont

WIDTH = 240
HEIGHT = 280
MAX_ROWS = 5

# (background, headline) for the most urgent state; state word colors for the agent list
HEADLINES = {
  'attention': ('#C2410C', 'NEEDS YOU'),
  'error': ('#B91C1C', 'ERROR'),
  'done': ('#15803D', 'DONE'),
  'working': ('#1D4ED8', 'WORKING'),
}
STATE_COLORS = {
  'attention': '#FB923C',
  'error': '#F87171',
  'done': '#4ADE80',
  'working': '#60A5FA',
}


def font(size):
  return ImageFont.load_default(size=size)


def fit(draw, text, max_width, size):
  """Shorten text with an ellipsis until it fits."""
  if draw.textlength(text, font=font(size)) <= max_width:
    return text
  while text and draw.textlength(text + '…', font=font(size)) > max_width:
    text = text[:-1]
  return text + '…'


def wrap(draw, text, max_width, size, max_lines):
  lines, current = [], ''
  for word in text.split():
    candidate = f'{current} {word}'.strip()
    if draw.textlength(candidate, font=font(size)) <= max_width:
      current = candidate
      continue
    if current:
      lines.append(current)
    current = word
  if current:
    lines.append(current)
  if len(lines) > max_lines:
    lines = lines[:max_lines]
    lines[-1] = fit(draw, lines[-1] + ' …', max_width, size)
  return [fit(draw, line, max_width, size) for line in lines]


def render_status(top, rows):
  """rows: [(label, state, detail, RRGGBB agent color)] most urgent first. Returns PNG bytes."""
  background, headline = HEADLINES[top]
  image = Image.new('RGB', (WIDTH, HEIGHT), background)
  draw = ImageDraw.Draw(image)
  margin = 14
  inner = WIDTH - 2 * margin

  draw.text((WIDTH / 2, 30), headline, font=font(34), fill='white', anchor='mm')

  # Most urgent agent's name, and what it is waiting for
  label, _, detail, _ = rows[0]
  draw.text((WIDTH / 2, 66), fit(draw, label, inner, 22), font=font(22), fill='white', anchor='mm')
  y = 86
  for line in wrap(draw, detail, inner, 15, 2):
    draw.text((WIDTH / 2, y), line, font=font(15), fill='#F5F5F4', anchor='mt')
    y += 18

  # Every active agent, as a list on a dark panel
  panel_top = 128
  draw.rounded_rectangle((8, panel_top, WIDTH - 8, HEIGHT - 8), radius=10, fill='#111827')
  row_height = 26
  shown = rows[:MAX_ROWS] if len(rows) <= MAX_ROWS else rows[:MAX_ROWS - 1]
  y = panel_top + 10
  for label, state, _, color in shown:
    center = y + row_height / 2
    draw.ellipse((20, center - 6, 32, center + 6), fill=f'#{color}')
    draw.text((42, center), fit(draw, label, 120, 17), font=font(17), fill='white', anchor='lm')
    draw.text((WIDTH - 20, center), state, font=font(14), fill=STATE_COLORS[state], anchor='rm')
    y += row_height
  if len(rows) > len(shown):
    draw.text((42, y + row_height / 2), f'+{len(rows) - len(shown)} more', font=font(15), fill='#9CA3AF', anchor='lm')

  output = io.BytesIO()
  image.save(output, format='PNG', optimize=True)
  return output.getvalue()
