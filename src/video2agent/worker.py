"""JSON-lines worker for read-only Video2Agent commands.

The Host keeps one of these processes while a DSH session is active. It avoids
paying the Python import/start cost on every tool call. This module deliberately
does not preload ASR or OCR: heavy modules are imported by the command that
needs them, and the Host stops the worker after an idle period.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from typing import Any


def _error(message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": "E_WORKER", "message": message}}


def serve() -> int:
    from . import cli

    # The Host speaks UTF-8 JSON lines even when the Windows console code page is
    # not UTF-8. Reconfigure stdin explicitly so Chinese queries survive the pipe.
    try:
        sys.stdin.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request_id = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            request_id = request.get("id")
            argv = request.get("argv")
            if not isinstance(argv, list) or not all(isinstance(x, str) for x in argv):
                raise ValueError("argv must be a list of strings")
            out = io.StringIO()
            err = io.StringIO()
            code = 0
            try:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = int(cli.main(argv))
            except SystemExit as exc:
                code = int(exc.code or 0) if isinstance(exc.code, int) else 1
            except Exception as exc:  # noqa: BLE001 - protocol must stay alive
                code = 1
                err.write(f"{type(exc).__name__}: {exc}")
            response = {
                "id": request_id,
                "code": code,
                "out": out.getvalue(),
                "err": err.getvalue(),
            }
        except Exception as exc:  # noqa: BLE001 - malformed request must not kill the worker
            response = {
                "id": request_id,
                "code": 1,
                "out": "",
                "err": f"{type(exc).__name__}: {exc}",
            }
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
