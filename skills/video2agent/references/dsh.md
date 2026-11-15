# DSH integration

## Skill install

Copy this folder to:

- project: PROJECT/.dsh/skills/video2agent
- global: ~/.dsh/skills/video2agent

Restart or reload the session. The catalog should show video2agent.

## CLI

Ensure video2agent is on PATH:

~~~bash
# PyPI pending: install from the repository or a wheel from Releases
pip install "git+https://github.com/Harm0ny-AI/DSH-Video2Agent.git"
video2agent doctor
~~~

For development from this repo:

~~~bash
set PYTHONPATH=D:\path\to\video2agent\src
python -m video2agent --help
~~~

## Model caveat

The default DSH model may be text-only. In that case, use --images 0 and rely
on transcript/OCR/visual signals. For visual questions, select a vision-capable
model.

## Plugin

The DSH plugin registers no in-chat cards: tool result cards are hidden and the
composer dock (live card + selected-video table) is the only visible surface.
The CLI remains the engine.
