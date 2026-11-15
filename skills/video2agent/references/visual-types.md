# Visual labels

These labels are routing hints, not facts.

- slide_like: static, text-heavy, slide/document layout.
- table_like: static with grid-like OCR alignment and/or many long lines.
- chart_like: static, high edge/color structure, sparse text.
- screencast: UI/code/terminal, many short text lines.
- talking_head: static, low text, optional face.
- animation: high motion, low text, high color change.
- static_low_info: static, low text, low structure.
- unknown: not enough signal.

Always expose the raw signals (motion, text_coverage, line_score, grid_score)
so the host can judge. A low-motion video is not automatically a table; text
and structure must support that claim.
