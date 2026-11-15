from __future__ import annotations

import math
import os
import re
import threading
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

from .util import Video2AgentError, human_bytes

_TS = r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[.,](?P<ms>\d{3})"
_TS_SHORT = r"(?P<m>\d{1,2}):(?P<s>\d{2})[.,](?P<ms>\d{3})"
_ARROW = re.compile(r"^\s*(.+?)\s*-->\s*(.+?)(?:\s+.*)?$")
_TAG = re.compile(r"<[^>]+>")
_CJK = re.compile(r"[\u3400-\u9fff]")
_WORD = re.compile(r"[a-zA-Z0-9_]+")
# Every script outside Latin and CJK used to be dropped by the tokenizer: a
# Russian video's transcript carried 4,751 Cyrillic characters but indexed zero
# tokens, and its own queries came back EMPTY_QUERY. Whole words from other
# scripts (Cyrillic, Greek, Arabic, kana, Hangul, Thai, …) become tokens; CJK
# keeps the bigram/trigram path below, and Latin stays byte-identical.
_SCRIPT_WORD = re.compile(r"[^\W\d_A-Za-z\u3400-\u9fff]+", re.UNICODE)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s*[%％]")
_PERCENT_ZH = re.compile(r"百分之\s*([零〇一二三四五六七八九十百千万两0-9]+)")
_QUERY_TIMECODE = re.compile(
    r"^\s*(?:(?P<h>\d{1,2}):)?(?P<m>\d{1,2}):(?P<s>\d{2})(?:[.,](?P<ms>\d{1,3}))?(?P<rest>\s+\S.*)?$"
)

_ZH_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_ZH_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\u200b", "").replace("\ufeff", "")
    text = _TAG.sub(" ", text)
    text = re.sub(r"\[[^\]]{1,80}\]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


_KANA = re.compile(r"[\u3040-\u30ff]")


def has_kana(text: str) -> bool:
    """True when the text carries Japanese kana (hiragana/katakana)."""
    return bool(text and _KANA.search(text))


def language_hint(text: str) -> str:
    if not text:
        return "unknown"
    cjk = len(_CJK.findall(text))
    latin = len(re.findall(r"[a-zA-Z]", text))
    if cjk and cjk >= latin * 0.25:
        return "zh"
    if latin:
        return "en"
    return "unknown"


def _parse_ts(value: str) -> int:
    value = value.strip().replace(",", ".")
    m = re.match(r"^(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?$", value)
    if not m:
        raise ValueError(value)
    h = int(m.group(1) or 0)
    mi = int(m.group(2))
    s = int(m.group(3))
    ms = int((m.group(4) or "0").ljust(3, "0")[:3])
    return ((h * 60 + mi) * 60 + s) * 1000 + ms


def parse_subtitle_text(text: str, source: str = "caption") -> list[dict[str, Any]]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", text)
    out: list[dict[str, Any]] = []
    for block in blocks:
        lines = [ln.strip("\ufeff").strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        if lines[0].upper().startswith("WEBVTT") or lines[0].upper().startswith("NOTE"):
            continue
        idx = None
        for i, line in enumerate(lines):
            if "-->" in line:
                idx = i
                break
        if idx is None:
            continue
        m = _ARROW.match(lines[idx])
        if not m:
            continue
        try:
            start = _parse_ts(m.group(1))
            end = _parse_ts(m.group(2))
        except Exception:
            continue
        body = " ".join(lines[idx + 1:])
        body = normalize_text(body)
        if not body:
            continue
        if end <= start:
            end = start + 1000
        out.append({"start_ms": start, "end_ms": end, "text": body, "source": source, "confidence": None})
    return out


def _merge_short_segments(segments: list[dict[str, Any]], max_gap_ms: int = 120, max_chars: int = 220) -> list[dict[str, Any]]:
    if not segments:
        return []
    merged: list[dict[str, Any]] = [dict(segments[0])]
    for seg in segments[1:]:
        prev = merged[-1]
        if seg["start_ms"] - prev["end_ms"] <= max_gap_ms and len(prev["text"]) + len(seg["text"]) <= max_chars:
            prev["end_ms"] = max(prev["end_ms"], seg["end_ms"])
            prev["text"] = normalize_text(prev["text"] + " " + seg["text"])
        else:
            merged.append(dict(seg))
    return merged


def parse_subtitle_file(path: str | Path, source: str = "caption") -> list[dict[str, Any]]:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise Video2AgentError("E_SUBTITLE_ENCODING", f"Cannot decode subtitle: {path}", "Convert it to UTF-8.")
    return parse_subtitle_text(text, source=source)


def find_sidecar(video_path: str | Path) -> Path | None:
    p = Path(video_path)
    stem = p.with_suffix("")
    candidates: list[Path] = []
    for ext in (".vtt", ".srt", ".ass", ".ssa"):
        candidates.append(Path(str(stem) + ext))
        candidates.append(Path(str(stem) + ".zh" + ext))
        candidates.append(Path(str(stem) + ".en" + ext))
    for c in candidates:
        if c.exists():
            return c
    if p.parent.exists():
        for c in sorted(p.parent.glob(p.stem + "*.vtt")) + sorted(p.parent.glob(p.stem + "*.srt")):
            if c.exists():
                return c
    return None


_STOP = {
    "the", "and", "for", "that", "with", "this", "from", "you", "are", "was", "were",
    "但是", "然后", "就是", "这个", "那个", "我们", "你们", "他们", "可以", "一个",
}

# Traditional -> Simplified for the common high-frequency set. ASR sometimes
# emits Traditional while OCR of the same video is Simplified, so the two
# modalities could not find each other ("點積" vs "点积"). A char map covers the
# common set without adding a dependency.
_T2S_PAIRS = """
還还 沒没 後后 這这 說说 時时 間间 學学 習习 數数 據据 結结 論论 圖图 點点 積积
陣阵 們们 個个 為为 對对 過过 進进 來来 開开 關关 門门 問问 題题 麼么 樣样 種种
實实 現现 應应 該该 會会 與与 從从 內内 兩两 產产 業业 務务 員员 體体 係系 統统
線线 質质 變变 計计 機机 訓训 練练 試试 驗验 顯显 視视 覺觉 語语 詞词 彙汇 編编
碼码 檔档 標标 記记 錄录 轉转 換换 讀读 寫写 輸输 網网 頁页 鏈链 節节 擊击 權权
隨随 嗎吗 將将 經经 於于 並并 卻却 讓让 給给 錯错 誤误 劃划 畫画 頻频 幀帧 聲声
響响 麥麦 講讲 話话 聽听 見见 資资 庫库 儲储 尋寻 檢检 構构 層层 組组 織织 專专
東东 車车 馬马 鳥鸟 魚鱼 龍龙 萬万 臺台 傳传 處处 認认 義义 師师 總总 報报 確确
規规 則则 範范 圍围 軸轴 衛卫 護护 優优 勢势 幾几 邊边 緣缘 覺觉 習习 樣样
廣广 測测 準准 際际 複复 雜杂 訊讯 邏逻 輯辑 額额 預预 領领 難难 陽阳 場场
廠厂 燈灯 錄录 鐘钟 鍵键 盤盘 螢萤 幕幕 頻频 寬宽 鬆松 緊紧 縮缩 擴扩 張张
"""

_T2S = {}
for _pair in _T2S_PAIRS.split():
    if len(_pair) != 2:
        raise RuntimeError(f"bad T2S pair: {_pair!r}")
    _T2S[ord(_pair[0])] = _pair[1]


def to_simplified(text: str) -> str:
    """Fold Traditional Chinese characters to Simplified for retrieval."""
    if not text:
        return text
    return text.translate(_T2S)


def _singular(word: str) -> str:
    """Crude plural folding for mixed CJK/Latin retrieval.

    FTS5 has no stemming, so ``timestamp`` and ``timestamps`` were different
    tokens; fold the common English plural on both index and query sides.
    """
    w = word.lower()
    if len(w) > 4 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def chinese_to_int(text: str) -> int | None:
    """Parse 0-9999 in Chinese numerals ("三十五" -> 35). None if not numeric."""
    if not text:
        return None
    if text.isdigit():
        return int(text)
    total = 0
    section = 0
    number = 0
    for ch in text:
        if ch in _ZH_DIGITS:
            number = _ZH_DIGITS[ch]
        elif ch in _ZH_UNITS:
            unit = _ZH_UNITS[ch]
            if unit == 10000:
                section = (section + number) * unit
                total += section
                section = 0
            else:
                if number == 0:
                    number = 1
                section += number * unit
            number = 0
        else:
            return None
    return total + section + number


def _pct_value(raw: str) -> str:
    raw = raw.strip().replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return ""
    if value.is_integer():
        return f"pct{int(value)}"
    return f"pct{value:g}"


def number_tokens(text: str) -> list[str]:
    """Canonical numeric tokens so 3.5 / 3,5 / 85% / 百分之八十五 agree.

    ``85%`` and ``百分之八十五`` both emit ``pct85``; decimals emit their
    dot-canonical form (``3,5`` -> ``3.5``); integer numbers of 2+ digits and
    Chinese numerals in a 百分之 phrase are kept.
    """
    out: list[str] = []
    percent_spans: list[tuple[int, int]] = []
    for m in _PERCENT.finditer(text):
        percent_spans.append(m.span())
        tok = _pct_value(m.group(1))
        if tok:
            out.append(tok)
    for m in _PERCENT_ZH.finditer(text):
        value = chinese_to_int(m.group(1))
        if value is not None:
            out.append(f"pct{value}")
    for m in _NUMBER.finditer(text):
        # A number inside "85%" is that percentage, not a bare 85: keeping both made
        # a 85mm lens measurement look like a match for the query "85%".
        if any(start <= m.start() and m.end() <= end for start, end in percent_spans):
            continue
        raw = m.group(0).replace(",", ".")
        if "." in raw:
            out.append(raw)
        elif len(raw) >= 2:
            out.append(raw)
    seen: set[str] = set()
    unique: list[str] = []
    for t in out:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def _script_words(text: str) -> list[str]:
    """Letter runs from scripts other than Latin/CJK, lowercased."""
    return [w.lower() for w in _SCRIPT_WORD.findall(text)]


def tokens_for_search(text: str) -> str:
    text = to_simplified(normalize_text(text))
    tokens: list[str] = []
    for word in _WORD.findall(text.lower()):
        w = _singular(word)
        if not w.isdigit() and len(w) >= 2 and w not in _STOP:
            tokens.append(w)
            # The query side folds plurals, so the index must carry that form too.
            if w != word and word not in _STOP:
                tokens.append(word)
    tokens.extend(number_tokens(text))
    cjk_chars = _CJK.findall(text)
    if cjk_chars:
        cjk_text = "".join(cjk_chars)
        if len(cjk_text) <= 2:
            tokens.append(cjk_text)
        else:
            for n in (2, 3):
                for i in range(len(cjk_text) - n + 1):
                    tokens.append(cjk_text[i:i + n])
            if len(cjk_text) <= 12:
                tokens.append(cjk_text)
    for word in _script_words(text):
        if len(word) >= 2 and word not in _STOP:
            tokens.append(word)
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return " ".join(out[:180])


def _is_script_token(token: str) -> bool:
    """A whole word from a script outside Latin/CJK (Cyrillic, kana, Hangul…)."""
    return any(ord(ch) > 127 for ch in token) and _CJK.search(token) is None


def fts_match_query(text: str) -> str:
    toks = tokens_for_search(text).split()
    if not toks:
        return ""
    # Other scripts inflect ("промокод" vs "промокоду"), so their tokens are
    # prefix queries. Latin keeps its plural folding and CJK its n-grams, so
    # existing behaviour is unchanged.
    parts = []
    for t in toks:
        escaped = t.replace('"', '""')
        if len(t) >= 3 and _is_script_token(t):
            parts.append(f'"{escaped}"*')
        else:
            parts.append(f'"{escaped}"')
    return " OR ".join(parts)


def query_units(text: str, *, max_units: int = 32) -> list[str]:
    """Content units used to re-rank hits by how much of the query they cover.

    Letters: word tokens (plural-folded). CJK: trigrams when the run is long
    enough (a 2-char run falls back to the bigram). Numbers: canonical forms.
    """
    text = to_simplified(normalize_text(text))
    units: list[str] = []
    for word in _WORD.findall(text.lower()):
        w = _singular(word)
        if len(w) >= 2 and w not in _STOP and not w.isdigit():
            units.append(w)
    units.extend(t for t in number_tokens(text) if not t.startswith("pct"))
    cjk = "".join(_CJK.findall(text))
    if len(cjk) >= 3:
        units.extend(cjk[i:i + 3] for i in range(len(cjk) - 2))
    elif cjk:
        units.append(cjk)
    for word in _script_words(text):
        if len(word) >= 2 and word not in _STOP:
            units.append(word)
    seen: set[str] = set()
    out: list[str] = []
    for u in units:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out[:max_units]


def _numeric_hit(unit: str, hay: str, hay_numbers: set[str]) -> bool:
    """A numeric unit matches a real number, not a substring of a longer one.

    `3.5` used to match `43.5`, `85%` matched `6.85`, and `v1.2` matched `3.1`/`2.55` —
    all of them ranked above the actual hit.
    """
    if unit in hay_numbers:
        return True
    return re.search(rf"(?<![\d.]){re.escape(unit)}(?![\d])", hay) is not None


def count_unit_matches(text: str, units: list[str]) -> int:
    """How many query units literally occur in ``text``."""
    if not units:
        return 0
    hay = to_simplified(normalize_text(text)).lower()
    hay_words = {_singular(w) for w in _WORD.findall(hay)}
    hay_numbers = set(number_tokens(hay))
    hits = 0
    for u in units:
        if u.isascii() and not any(ch.isdigit() for ch in u):
            if _singular(u) in hay_words:
                hits += 1
        elif any(ch.isdigit() for ch in u):
            if _numeric_hit(u, hay, hay_numbers):
                hits += 1
        elif u in hay:
            hits += 1
    return hits


def coverage_score(text: str, units: list[str]) -> float:
    """Fraction of query units that literally occur in ``text``."""
    if not units:
        return 0.0
    return round(count_unit_matches(text, units) / len(units), 4)


def numeric_overlap(query: str, text: str) -> float:
    """Fraction of the query's canonical numbers that the text also has."""
    q = set(number_tokens(to_simplified(normalize_text(query))))
    if not q:
        return 0.0
    h = set(number_tokens(to_simplified(normalize_text(text))))
    return round(len(q & h) / len(q), 4)


def literal_terms(text: str, *, max_terms: int = 8) -> list[str]:
    """Fallback terms for queries FTS cannot tokenise (e.g. "秩", "Q K V").

    Latin/alnum groups keep their exact spelling; each CJK character is a term.
    A hit must contain *all* terms, so a nonsense query still returns nothing.
    Decimals, percentages and version numbers stay whole: splitting "3.5" into "3"
    and "5" matched "3项(2025" and "85%" and returned pages that never contained the
    number. A lone digit is not a term either — it matches almost everything.
    """
    text = to_simplified(normalize_text(text))
    terms: list[str] = [
        w.lower() for w in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*|\d+(?:[.,]\d+)+%?|\d+%?", text)
    ]
    terms += re.findall(r"[\u3400-\u9fff]", text)
    # Other scripts are whole words: splitting Cyrillic into single letters would
    # make the literal fallback match almost anything.
    terms += _script_words(text)
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    # A lone Latin letter is a term only when the query is plain shorthand
    # ("Q K V"); in "C++" the 'C' would match every C tutorial (reproduced).
    singles = [t for t in out if len(t) == 1 and t.isascii() and t.isalnum()]
    cjk_terms = [t for t in out if not t.isascii()]
    if singles and not cjk_terms and not any(len(t) > 1 for t in out):
        compact = re.sub(r"\s+", "", text)
        if not re.fullmatch(r"[A-Za-z0-9]+", compact):
            out = [t for t in out if t not in singles]
    return out[:max_terms]


def leading_timecode(text: str) -> tuple[int | None, str]:
    """Split a leading ``00:00:12`` / ``1:30`` off a query.

    Returns ``(ms, rest)``. ``ms`` is None when the query does not start with a
    timecode. ``rest`` keeps the remaining words (``说了什么`` ...).
    """
    m = _QUERY_TIMECODE.match(text or "")
    if not m:
        return None, (text or "").strip()
    h = int(m.group("h") or 0)
    mi = int(m.group("m"))
    s = int(m.group("s"))
    ms = int((m.group("ms") or "0").ljust(3, "0")[:3])
    total = ((h * 60 + mi) * 60 + s) * 1000 + ms
    rest = (m.group("rest") or "").strip()
    return total, rest


def text_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def align_captions_to_asr(captions: list[dict[str, Any]], asr_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not captions or not asr_segments:
        return captions
    out: list[dict[str, Any]] = []
    for cap in captions:
        mid = (cap["start_ms"] + cap["end_ms"]) // 2
        best = None
        best_score = 0.0
        for seg in asr_segments:
            if seg["end_ms"] < mid - 5000 or seg["start_ms"] > mid + 5000:
                continue
            score = text_similarity(cap["text"], seg["text"])
            if score > best_score:
                best_score = score
                best = seg
        item = dict(cap)
        if best and best_score >= 0.42:
            item["start_ms"] = best["start_ms"]
            item["end_ms"] = best["end_ms"]
            item["source"] = "caption_aligned"
            item["confidence"] = round(best_score, 3)
        out.append(item)
    return out


# How often the download watcher reports progress while the weights land.
_DOWNLOAD_WATCH_INTERVAL_S = 1.5


_MODEL_REPOS = {
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
}


def whisper_cache_dir(model_size: str) -> Path:
    """Where faster-whisper keeps the weights it downloads.

    Accepts a local CTranslate2 directory, a full HuggingFace repo ID, or a
    faster-whisper preset name. Presets are not a whitelist.
    """
    raw = Path(str(model_size)).expanduser()
    if raw.is_dir():
        return raw
    base = os.environ.get("HF_HOME")
    if base:
        hub = Path(base) / "hub"
    else:
        hub = Path.home() / ".cache" / "huggingface" / "hub"
    repo = _MODEL_REPOS.get(str(model_size))
    if not repo:
        repo = str(model_size) if "/" in str(model_size) else f"Systran/faster-whisper-{model_size}"
    return hub / f"models--{repo.replace('/', '--')}"


def whisper_cache_state(model_size: str) -> dict[str, Any]:
    """Is the ASR model already complete on disk?

    A directory with only a partial HuggingFace blob (`.incomplete`) is not a
    usable cache: treating it as ready made the next call silently download the
    rest. Require the actual weight file and config, and ignore incomplete blobs.
    """
    path = whisper_cache_dir(model_size)
    total = 0
    has_weights = False
    has_config = False
    if path.is_dir():
        for item in path.rglob("*"):
            try:
                if not item.is_file() or item.name.endswith(".incomplete"):
                    continue
                size = item.stat().st_size
                total += size
                if item.name == "model.bin" and size > 1024 * 1024:
                    has_weights = True
                if item.name == "config.json":
                    has_config = True
            except OSError:
                continue
    return {
        "model": model_size,
        "cached": bool(has_weights and has_config),
        "path": str(path),
        "bytes": total,
    }


def transcribe_with_faster_whisper(
    audio_path: str | Path,
    *,
    model_size: str = "small",
    device: str = "auto",
    compute_type: str = "int8",
    language: str | None = None,
    beam_size: int = 1,
    word_timestamps: bool = False,
    cpu_threads: int = 0,
    progress: Callable[[int], None] | None = None,
    stage: Callable[[str], None] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        from faster_whisper import WhisperModel
    except Exception as e:
        raise Video2AgentError("E_ASR_MISSING", "faster-whisper is not installed.", "pip install faster-whisper") from e
    # The first run downloads ~500MB of weights with no output at all; announce it
    # so the job card does not sit on one frozen percentage for a minute. While it
    # downloads, a watcher reports the bytes landed so far — "still downloading"
    # and "stuck" otherwise look identical on the card.
    cached = whisper_cache_state(model_size)
    stop_watch = threading.Event()
    watcher: threading.Thread | None = None
    if stage is not None and not cached["cached"]:
        stage(f"首次使用：下载语音模型 {model_size}（约 500MB，只需一次）")

        def _watch_download() -> None:
            last = cached["bytes"]
            while not stop_watch.wait(_DOWNLOAD_WATCH_INTERVAL_S):
                now = whisper_cache_state(model_size)["bytes"]
                if now > last:
                    last = now
                    stage(f"下载语音模型 {model_size} · 已下载 {human_bytes(now)}")

        watcher = threading.Thread(target=_watch_download, name="vp-asr-download", daemon=True)
        watcher.start()
    elif stage is not None:
        stage(f"加载语音模型 {model_size}")
    try:
        try:
            model = WhisperModel(model_size, device=device, compute_type=compute_type,
                                 cpu_threads=cpu_threads)
        except Exception as first_error:  # noqa: BLE001
            # faster-whisper asks Hugging Face for the latest revision even when
            # the weights are already cached, so a network outage killed ASR on a
            # machine that had the model on disk. Retry from the local cache.
            try:
                model = WhisperModel(model_size, device=device, compute_type=compute_type,
                                     cpu_threads=cpu_threads, local_files_only=True)
            except Exception:
                raise first_error
        segments_iter, info = model.transcribe(
            str(audio_path),
            language=language,
            vad_filter=True,
            word_timestamps=word_timestamps,
            beam_size=beam_size,
            condition_on_previous_text=False,
        )
    except Exception as e:
        raise Video2AgentError("E_ASR", f"ASR failed: {e}", "Try a smaller model or check the audio track.") from e
    finally:
        # The watcher must not keep writing stages for a model that is no longer
        # loading, whether the load succeeded or failed.
        stop_watch.set()
        if watcher is not None:
            watcher.join(timeout=0.1)
    out: list[dict[str, Any]] = []
    lang = getattr(info, "language", language)
    for seg in segments_iter:
        text = normalize_text(seg.text)
        if not text:
            continue
        words = []
        probs: list[float] = []
        for w in (seg.words or []):
            word = normalize_text(w.word)
            if not word:
                continue
            prob = float(getattr(w, "probability", 0.0) or 0.0)
            probs.append(prob)
            words.append({
                "start_ms": int(round(w.start * 1000)),
                "end_ms": int(round(w.end * 1000)),
                "word": word,
                "probability": round(prob, 4),
            })
        confidence = sum(probs) / len(probs) if probs else math.exp(min(0.0, float(getattr(seg, "avg_logprob", 0.0) or 0.0)))
        out.append({
            "start_ms": int(round(seg.start * 1000)),
            "end_ms": int(round(seg.end * 1000)),
            "text": text,
            "source": "asr",
            "confidence": round(max(0.0, min(1.0, confidence)), 3),
            "words": words,
        })
        if progress is not None:
            progress(int(round(seg.end * 1000)))
    return out, lang


def format_timestamp(ms: int | float | None) -> str:
    if ms is None:
        return "?"
    total = max(0, int(ms))
    h, rem = divmod(total, 3600000)
    m, rem = divmod(rem, 60000)
    s, milli = divmod(rem, 1000)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}.{milli:03d}"
    return f"{m:02d}:{s:02d}.{milli:03d}"
