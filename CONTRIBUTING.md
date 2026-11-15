# Contributing

## Setup

~~~bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
video2agent doctor
~~~

## Checks

~~~bash
python -m unittest discover -s tests -v
pytest
~~~

## Rules

- Keep evidence timestamps in milliseconds.
- Search returns text; evidence returns images.
- Never silently turn a failure into an empty success.
- Do not add a heavy model to the default install without measuring startup,
  disk, and CPU cost.
- Add a test for every new parser or scoring rule.
- Keep the Skill instructions and the CLI flags in sync.
- Use DCO sign-off in commits.

## Scope

The project is an evidence layer, not a video editor or a note-template
collection. If a feature belongs in a downstream agent, keep it there.
