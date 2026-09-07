"""Guarded transcript import built around :mod:`turnchunk`.

Transcript times are navigation hints. They never define audio edit bounds.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterator
from copy import deepcopy
from pathlib import PurePath
from typing import Any

import turnchunk
from turnchunk.parsers.asr import _identify as _identify_json

_MAX_TIME_MS = 2**53 - 1
_GENERIC_KINDS = {"generic_list", "generic_dict"}
_GENERIC_CONTAINERS = ("utterances", "turns", "transcript", "items", "entries")
_START_KEYS = ("start", "startTime", "ts", "begin")
_END_KEYS = ("end", "endTime", "end_ts", "stop")
_ESTIMATE_KEYS = ("time_estimated", "timing_estimated", "estimated")
_UNITS = {
    "s": "seconds",
    "sec": "seconds",
    "second": "seconds",
    "seconds": "seconds",
    "ms": "milliseconds",
    "millisecond": "milliseconds",
    "milliseconds": "milliseconds",
}
_FORMAT_HINTS = {
    ".json": "json",
    ".jsonl": "json",
    ".srt": "srt",
    ".vtt": "vtt",
    ".md": "plain",
    ".txt": "plain",
}
_VENDOR_TIMING = {
    "whisper": ("start", "end", "seconds", False),
    "assemblyai": ("start", "end", "milliseconds", False),
    "deepgram": ("start", "end", "seconds", False),
    "rev": ("ts", "end_ts", "seconds", False),
    "speechmatics": ("start_time", "end_time", "seconds", False),
    "aws": ("start_time", "end_time", "seconds", True),
}


def import_transcript(
    text: str,
    source_id: str,
    filename: str,
    *,
    time_unit: str | None = None,
) -> dict:
    """Import transcript content as a finite, JSON-safe project record.

    ``time_unit`` applies only to ambiguous generic JSON fields. Explicit
    ``*_ms`` fields and recognized vendor formats retain their declared units.
    """
    _validate_inputs(text, source_id, filename)
    declared_unit = _normalise_unit(time_unit)
    format_name = turnchunk.detect_format(text) or _FORMAT_HINTS.get(
        PurePath(filename).suffix.lower()
    )
    if format_name is None:
        raise ValueError(
            "Could not detect transcript format; use a .json, .vtt, .srt, or .txt filename."
        )

    words: list[dict[str, Any]] = []
    estimate_flags: list[bool] = []
    timing_overrides: list[tuple[int | None, int | None]] = []
    if format_name == "json":
        data = _load_json(text)
        vendor = _identify_json(data)
        if vendor is None:
            raise ValueError("Unrecognized transcript JSON structure.")
        _validate_text_fields(data)
        if vendor in _GENERIC_KINDS:
            entries = _generic_entries(data, vendor)
            shadow, estimate_flags = _normalise_generic(entries, declared_unit)
            parsed = _parse(
                json.dumps({"segments": shadow}, allow_nan=False),
                "json",
                vendor="whisper",
            )
            parsed.format = f"json:{vendor}"
        else:
            _validate_recognized_json(data, vendor)
            explicit_entries = _explicit_ms_vendor_entries(data, vendor)
            if explicit_entries is not None:
                unit = "milliseconds" if vendor == "assemblyai" else "seconds"
                shadow, estimate_flags = _normalise_generic(explicit_entries, unit)
                parsed = _parse(
                    json.dumps({"segments": shadow}, allow_nan=False),
                    "json",
                    vendor="whisper",
                )
                parsed.format = f"json:{vendor}"
            else:
                parsed = _parse(text, "json")
            estimate_flags = _source_estimate_flags(data, vendor)
            timing_overrides = _source_timing_overrides(data, vendor)
        words = _extract_words(data, vendor, declared_unit)
    else:
        parsed = (
            _parse_subtitle_cues(text, format_name)
            if format_name in {"vtt", "srt"}
            else _parse(text, format_name)
        )

    if not parsed.turns:
        raise ValueError("Transcript contains no importable turns.")
    if parsed.format in {"vtt", "srt"} and any(
        turn.start_ms is None or turn.end_ms is None for turn in parsed.turns
    ):
        raise ValueError(f"Invalid {parsed.format.upper()} cue timing.")

    turns = []
    for index, turn in enumerate(parsed.turns):
        raw_start, raw_end = (
            timing_overrides[index]
            if index < len(timing_overrides)
            else (turn.start_ms, turn.end_ms)
        )
        start_ms, end_ms = _validate_pair(raw_start, raw_end, f"turn {index + 1}")
        turns.append(
            {
                "text": turn.text,
                "speaker": turn.speaker,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "time_estimated": estimate_flags[index]
                if len(estimate_flags) == len(parsed.turns)
                else False,
            }
        )

    _apply_word_estimates(turns, words)

    digest = hashlib.sha256()
    for value in (source_id, filename, text):
        digest.update(value.encode())
        digest.update(b"\0")
    digest.update(
        json.dumps(
            {"format": parsed.format, "turns": turns},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    record = {
        "id": f"transcript-{digest.hexdigest()[:24]}",
        "source_id": source_id,
        "format": parsed.format,
        "raw_text": text,
        "turns": turns,
        "words": words,
        "warnings": _warnings(turns),
    }
    json.dumps(record, allow_nan=False)
    return record


def _validate_inputs(text: Any, source_id: Any, filename: Any) -> None:
    for value, name in ((text, "text"), (source_id, "source_id"), (filename, "filename")):
        if not isinstance(value, str):
            raise TypeError(f"{name} must be a string.")
    if not source_id.strip() or not filename.strip():
        raise ValueError("source_id and filename must not be empty.")


def _normalise_unit(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("time_unit must be a string or None.")
    unit = _UNITS.get(value.strip().lower())
    if unit is None:
        raise ValueError("time_unit must be 'seconds' or 'milliseconds'.")
    return unit


def _load_json(text: str) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"Transcript JSON contains non-finite value {value}.")

    try:
        return json.loads(text.lstrip("\ufeff"), parse_constant=reject_constant)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid transcript JSON at line {exc.lineno}, column {exc.colno}."
        ) from exc


def _parse(text: str, format_name: str, **kwargs: Any) -> turnchunk.Transcript:
    try:
        return turnchunk.parse(text, format=format_name, merge=False, **kwargs)
    except (AttributeError, OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"Could not parse {format_name.upper()} transcript: {exc}") from exc


def _parse_subtitle_cues(text: str, format_name: str) -> turnchunk.Transcript:
    """Run each subtitle cue through turnchunk without cross-cue deduplication."""
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    turns = []
    for block in re.split(r"\n\s*\n", normalized.strip()):
        if "-->" not in block:
            continue
        cue_text = block if format_name == "srt" else f"WEBVTT\n\n{block}"
        turns.extend(_parse(cue_text, format_name).turns)
    return turnchunk.Transcript(turns=turns, format=format_name)


def _validate_text_fields(data: Any) -> None:
    text_keys = {
        "text",
        "transcript",
        "word",
        "punctuated_word",
        "content",
        "display",
        "lexical",
        "value",
    }
    for path, item in _walk_dicts(data):
        for key in text_keys.intersection(item):
            if path == "root" and key in _GENERIC_CONTAINERS and isinstance(item[key], list):
                continue
            if item[key] is not None and not isinstance(item[key], str):
                raise ValueError(f"{path}.{key} must be text.")


def _explicit_ms_vendor_entries(data: Any, vendor: str) -> list[dict[str, Any]] | None:
    if not isinstance(data, dict) or vendor not in {"whisper", "assemblyai"}:
        return None
    entries = data.get("segments" if vendor == "whisper" else "utterances")
    if not isinstance(entries, list):
        return None
    typed = [entry for entry in entries if isinstance(entry, dict)]
    return typed if any("start_ms" in entry or "end_ms" in entry for entry in typed) else None


def _generic_entries(data: Any, vendor: str) -> list[dict[str, Any]]:
    if vendor == "generic_list":
        entries = data
    elif isinstance(data, dict):
        entries = next(
            (data[key] for key in _GENERIC_CONTAINERS if isinstance(data.get(key), list)),
            [],
        )
    else:
        entries = []
    if not isinstance(entries, list):
        raise ValueError("Generic transcript entries must be a list.")
    return [entry for entry in entries if isinstance(entry, dict)]


def _normalise_generic(
    entries: list[dict[str, Any]], unit: str | None
) -> tuple[list[dict[str, Any]], list[bool]]:
    shadow = []
    flags = []
    for index, entry in enumerate(entries):
        body = _first(entry, "text", "transcript", "value", "content")
        if not isinstance(body, str) or not body.strip():
            continue
        start_ms = _generic_time(entry, "start_ms", _START_KEYS, unit, index)
        end_ms = _generic_time(entry, "end_ms", _END_KEYS, unit, index)
        start_ms, end_ms = _validate_pair(start_ms, end_ms, f"generic entry {index + 1}")
        shadow.append(
            {
                "text": str(body),
                "speaker": _first(entry, "speaker", "speaker_label", "speakerId", "spk"),
                "start": start_ms / 1000 if start_ms is not None else None,
                "end": end_ms / 1000 if end_ms is not None else None,
            }
        )
        flags.append(_estimate_flag(entry, f"generic entry {index + 1}"))
    return shadow, flags


def _generic_time(
    item: dict[str, Any],
    explicit_key: str,
    generic_keys: tuple[str, ...],
    unit: str | None,
    index: int,
) -> int | None:
    explicit = item.get(explicit_key)
    generic_key = next((key for key in generic_keys if item.get(key) not in (None, "")), None)
    if explicit not in (None, "") and generic_key is not None:
        raise ValueError(
            f"Generic entry {index + 1} declares both {explicit_key} and {generic_key}."
        )
    if explicit not in (None, ""):
        return _to_ms(explicit, "milliseconds", f"entry {index + 1}.{explicit_key}")
    if generic_key is None:
        return None
    if unit is None:
        raise ValueError(
            "Generic transcript timing is ambiguous; declare time_unit as "
            "'seconds' or 'milliseconds'."
        )
    return _to_ms(item[generic_key], unit, f"entry {index + 1}.{generic_key}")


def _validate_recognized_json(data: Any, vendor: str) -> None:
    if vendor == "google":
        for path, item in _walk_dicts(data):
            start_key = "startTime" if "startTime" in item else "start_time"
            end_key = "endTime" if "endTime" in item else "end_time"
            if start_key not in item and end_key not in item:
                continue
            start = _google_ms(item.get(start_key), f"{path}.{start_key}")
            end = _google_ms(item.get(end_key), f"{path}.{end_key}")
            _validate_pair(start, end, path)
        return
    if vendor == "azure":
        for path, item in _walk_dicts(data):
            if "offsetInTicks" not in item and "durationInTicks" not in item:
                continue
            start = _ticks_ms(item.get("offsetInTicks"), f"{path}.offsetInTicks")
            duration = _ticks_ms(item.get("durationInTicks"), f"{path}.durationInTicks")
            end = start + duration if start is not None and duration is not None else None
            _validate_pair(start, end, path)
        return
    timing = _VENDOR_TIMING.get(vendor)
    if timing is None:
        return
    start_key, end_key, unit, strings_allowed = timing
    for path, item in _walk_dicts(data):
        if start_key not in item and end_key not in item:
            continue
        start = _to_ms(item.get(start_key), unit, f"{path}.{start_key}", strings_allowed)
        end = _to_ms(item.get(end_key), unit, f"{path}.{end_key}", strings_allowed)
        _validate_pair(start, end, path)


def _extract_words(data: Any, vendor: str, generic_unit: str | None) -> list[dict[str, Any]]:
    output = []
    for path, item in _word_items(data):
        if vendor in _GENERIC_KINDS:
            start = _generic_time(item, "start_ms", _START_KEYS, generic_unit, 0)
            end = _generic_time(item, "end_ms", _END_KEYS, generic_unit, 0)
        elif vendor in {"whisper", "assemblyai"}:
            unit = "milliseconds" if vendor == "assemblyai" else "seconds"
            start = _generic_time(item, "start_ms", _START_KEYS, unit, 0)
            end = _generic_time(item, "end_ms", _END_KEYS, unit, 0)
        elif vendor == "google":
            start = _google_ms(item.get("startTime") or item.get("start_time"), f"{path}.start")
            end = _google_ms(item.get("endTime") or item.get("end_time"), f"{path}.end")
        elif vendor == "azure":
            start = _ticks_ms(item.get("offsetInTicks"), f"{path}.offsetInTicks")
            duration = _ticks_ms(item.get("durationInTicks"), f"{path}.durationInTicks")
            end = start + duration if start is not None and duration is not None else None
        else:
            start = _to_ms(item.get("start"), "seconds", f"{path}.start")
            end = _to_ms(item.get("end"), "seconds", f"{path}.end")
        start, end = _validate_pair(start, end, path)
        output.append(
            {
                "text": str(_first(item, "word", "text", "punctuated_word", "content") or ""),
                "speaker": _first(item, "speaker", "speaker_label", "speakerTag", "speaker_tag"),
                "start_ms": start,
                "end_ms": end,
                "time_estimated": _estimate_flag(item, path),
                "provenance": {"vendor": vendor, "path": path},
                "raw": deepcopy(item),
            }
        )
    return output


def _word_items(data: Any) -> Iterator[tuple[list[str | int], dict[str, Any]]]:
    def visit(
        value: Any, path: list[str | int]
    ) -> Iterator[tuple[list[str | int], dict[str, Any]]]:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "words" and isinstance(child, list):
                    for index, word in enumerate(child):
                        if isinstance(word, dict):
                            yield path + [key, index], word
                else:
                    yield from visit(child, path + [key])
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from visit(child, path + [index])

    yield from visit(data, [])


def _walk_dicts(data: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    stack = [("root", data)]
    while stack:
        path, value = stack.pop()
        if isinstance(value, dict):
            yield path, value
            stack.extend((f"{path}.{key}", child) for key, child in value.items())
        elif isinstance(value, list):
            stack.extend((f"{path}[{index}]", child) for index, child in enumerate(value))


def _source_estimate_flags(data: Any, vendor: str) -> list[bool]:
    if not isinstance(data, dict):
        return []
    if vendor == "whisper":
        entries = data.get("segments")
    elif vendor == "assemblyai":
        entries = data.get("utterances") or data.get("words")
    elif vendor == "deepgram":
        entries = (data.get("results") or {}).get("utterances")
    else:
        entries = None
    return [
        _estimate_flag(item, f"{vendor} entry {index + 1}")
        for index, item in enumerate(entries or [])
        if isinstance(item, dict)
        and isinstance(_first(item, "text", "transcript", "content"), str)
        and _first(item, "text", "transcript", "content").strip()
    ]


def _source_timing_overrides(data: Any, vendor: str) -> list[tuple[int | None, int | None]]:
    if vendor != "azure" or not isinstance(data, dict):
        return []
    overrides = []
    for index, phrase in enumerate(data.get("recognizedPhrases") or []):
        if not isinstance(phrase, dict):
            continue
        alternatives = phrase.get("nBest") or []
        best = alternatives[0] if alternatives and isinstance(alternatives[0], dict) else {}
        body = best.get("display") or best.get("lexical")
        if not isinstance(body, str) or not body.strip():
            continue
        start = _ticks_ms(phrase.get("offsetInTicks"), f"recognizedPhrases[{index}].offset")
        duration = _ticks_ms(phrase.get("durationInTicks"), f"recognizedPhrases[{index}].duration")
        end = start + duration if start is not None and duration is not None else None
        overrides.append((start, end))
    return overrides


def _apply_word_estimates(turns: list[dict[str, Any]], words: list[dict[str, Any]]) -> None:
    for word in words:
        if not word["time_estimated"]:
            continue
        word_start = word["start_ms"]
        word_end = word["end_ms"]
        for turn in turns:
            turn_start = turn["start_ms"]
            turn_end = turn["end_ms"]
            if (
                word_start is not None
                and word_end is not None
                and turn_start is not None
                and turn_end is not None
                and word_start <= turn_end
                and word_end >= turn_start
            ):
                turn["time_estimated"] = True


def _to_ms(value: Any, unit: str, path: str, strings_allowed: bool = False) -> int | None:
    if value in (None, ""):
        return None
    if strings_allowed and isinstance(value, str):
        try:
            value = float(value)
        except ValueError as exc:
            raise ValueError(f"{path} must contain a numeric time.") from exc
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a number.")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{path} must be finite.")
    milliseconds = number * 1000 if unit == "seconds" else number
    if milliseconds < 0:
        raise ValueError(f"{path} must be non-negative.")
    if milliseconds > _MAX_TIME_MS:
        raise ValueError(f"{path} is outside the supported range.")
    return round(milliseconds)


def _google_ms(value: Any, path: str) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, dict):
        try:
            value = float(value.get("seconds", 0)) + float(value.get("nanos", 0)) / 1e9
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{path} must be a Google duration.") from exc
    elif isinstance(value, str) and value.endswith("s"):
        try:
            value = float(value[:-1])
        except ValueError as exc:
            raise ValueError(f"{path} must be a Google duration.") from exc
    else:
        raise ValueError(f"{path} must be a Google duration ending in 's'.")
    return _to_ms(value, "seconds", path)


def _ticks_ms(value: Any, path: str) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a number of 100-nanosecond ticks.")
    ticks = float(value)
    if not math.isfinite(ticks):
        raise ValueError(f"{path} must be finite.")
    return _to_ms(ticks / 10_000, "milliseconds", path)


def _validate_pair(start: Any, end: Any, path: str) -> tuple[int | None, int | None]:
    for value, name in ((start, "start"), (end, "end")):
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            or value > _MAX_TIME_MS
        ):
            raise ValueError(f"{path} has invalid {name} timing.")
    if start is not None and end is not None and end < start:
        raise ValueError(f"{path} ends before start.")
    return start, end


def _estimate_flag(item: dict[str, Any], path: str) -> bool:
    for key in _ESTIMATE_KEYS:
        if key in item:
            if not isinstance(item[key], bool):
                raise ValueError(f"{path}.{key} must be true or false.")
            return item[key]
    return False


def _warnings(turns: list[dict[str, Any]]) -> list[str]:
    output = []
    unknown = sum(turn["start_ms"] is None or turn["end_ms"] is None for turn in turns)
    estimated = sum(turn["time_estimated"] for turn in turns)
    if unknown:
        output.append(f"{unknown} turn(s) have unknown timing; no timestamps were inferred.")
    if estimated:
        output.append(f"{estimated} turn(s) use source-marked estimated timing.")
    return output


def _first(item: dict[str, Any], *keys: str) -> Any:
    return next((item[key] for key in keys if item.get(key) not in (None, "")), None)
