from __future__ import annotations

import json
from pathlib import Path

import pytest

from cleantake.transcripts import import_transcript


def test_explicit_millisecond_fields_bypass_turnchunk_magnitude_guess() -> None:
    record = import_transcript(
        '[{"start_ms": 1000, "end_ms": 2000, "text": "hello"}]',
        "source-a",
        "transcript.json",
    )

    assert record["format"] == "json:generic_list"
    assert record["turns"] == [
        {
            "text": "hello",
            "speaker": None,
            "start_ms": 1000,
            "end_ms": 2000,
            "time_estimated": False,
        }
    ]


def test_generic_time_fields_require_a_declared_unit() -> None:
    raw = '[{"start": 1, "end": 2, "text": "hello"}]'

    with pytest.raises(ValueError, match="time_unit"):
        import_transcript(raw, "source-a", "transcript.json")

    seconds = import_transcript(
        raw,
        "source-a",
        "transcript.json",
        time_unit="seconds",
    )
    assert seconds["turns"][0]["start_ms"] == 1000
    assert seconds["turns"][0]["end_ms"] == 2000


def test_declared_milliseconds_work_for_small_and_large_generic_values() -> None:
    record = import_transcript(
        json.dumps(
            [
                {"start": 1, "end": 2, "text": "first"},
                {"start": 12_000, "end": 13_500, "text": "second"},
            ]
        ),
        "source-a",
        "transcript.json",
        time_unit="milliseconds",
    )

    assert [(turn["start_ms"], turn["end_ms"]) for turn in record["turns"]] == [
        (1, 2),
        (12_000, 13_500),
    ]


def test_recognized_vendor_units_are_authoritative() -> None:
    whisper = import_transcript(
        '{"segments":[{"start":1,"end":2,"text":"hello"}]}',
        "source-a",
        "whisper.json",
        time_unit="milliseconds",
    )
    assembly = import_transcript(
        ('{"id":"job","utterances":[{"start":1000,"end":2000,"text":"hello"}],"words":[]}'),
        "source-a",
        "assembly.json",
        time_unit="seconds",
    )

    assert whisper["format"] == "json:whisper"
    assert (whisper["turns"][0]["start_ms"], whisper["turns"][0]["end_ms"]) == (
        1000,
        2000,
    )
    assert assembly["format"] == "json:assemblyai"
    assert (assembly["turns"][0]["start_ms"], assembly["turns"][0]["end_ms"]) == (
        1000,
        2000,
    )


@pytest.mark.parametrize(
    ("filename", "raw", "expected_format", "speaker"),
    [
        (
            "captions.vtt",
            "WEBVTT\n\n00:00:01.000 --> 00:00:02.250\n<v Speaker A>Hello there\n",
            "vtt",
            "Speaker A",
        ),
        (
            "captions.srt",
            "1\n00:00:01,000 --> 00:00:02,250\nSpeaker A: Hello there\n",
            "srt",
            "Speaker A",
        ),
    ],
)
def test_subtitle_parsers_retain_declared_cue_timing(
    filename: str, raw: str, expected_format: str, speaker: str
) -> None:
    record = import_transcript(raw, "source-a", filename)

    assert record["format"] == expected_format
    assert record["turns"] == [
        {
            "text": "Hello there",
            "speaker": speaker,
            "start_ms": 1000,
            "end_ms": 2250,
            "time_estimated": False,
        }
    ]


def test_whisper_words_retain_raw_values_provenance_and_estimate_flags() -> None:
    raw = json.dumps(
        {
            "segments": [
                {
                    "id": 7,
                    "start": 1.25,
                    "end": 2.5,
                    "text": " hello world",
                    "speaker": "Guest",
                    "time_estimated": True,
                    "words": [
                        {
                            "word": " hello",
                            "start": 1.25,
                            "end": 1.7,
                            "probability": 0.98,
                            "time_estimated": True,
                        },
                        {
                            "word": " world",
                            "start": 1.8,
                            "end": 2.5,
                            "probability": 0.91,
                        },
                    ],
                }
            ]
        }
    )

    record = import_transcript(raw, "source-a", "whisper.json")

    assert record["turns"][0]["time_estimated"] is True
    assert record["words"] == [
        {
            "text": " hello",
            "speaker": None,
            "start_ms": 1250,
            "end_ms": 1700,
            "time_estimated": True,
            "provenance": {
                "vendor": "whisper",
                "path": ["segments", 0, "words", 0],
            },
            "raw": {
                "word": " hello",
                "start": 1.25,
                "end": 1.7,
                "probability": 0.98,
                "time_estimated": True,
            },
        },
        {
            "text": " world",
            "speaker": None,
            "start_ms": 1800,
            "end_ms": 2500,
            "time_estimated": False,
            "provenance": {
                "vendor": "whisper",
                "path": ["segments", 0, "words", 1],
            },
            "raw": {
                "word": " world",
                "start": 1.8,
                "end": 2.5,
                "probability": 0.91,
            },
        },
    ]
    assert any("estimated" in warning for warning in record["warnings"])
    json.dumps(record, allow_nan=False)


def test_unknown_timing_stays_unknown_and_content_stays_literal() -> None:
    literal = '<script>alert("transcript")</script> is spoken content'
    record = import_transcript(literal, "source-a", "notes.txt")

    assert record["raw_text"] == literal
    assert record["turns"] == [
        {
            "text": literal,
            "speaker": None,
            "start_ms": None,
            "end_ms": None,
            "time_estimated": False,
        }
    ]
    assert any("unknown timing" in warning for warning in record["warnings"])


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ('[{"start_ms":-1,"end_ms":2,"text":"bad"}]', "non-negative"),
        ('[{"start_ms":3,"end_ms":2,"text":"bad"}]', "before start"),
        ('[{"start_ms":true,"end_ms":2,"text":"bad"}]', "number"),
        ('[{"start_ms":"1","end_ms":2,"text":"bad"}]', "number"),
        ('[{"start_ms":NaN,"end_ms":2,"text":"bad"}]', "finite"),
        (
            '[{"start_ms":9007199254740992,"end_ms":9007199254740992,"text":"bad"}]',
            "supported range",
        ),
    ],
)
def test_invalid_generic_timing_is_rejected(raw: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        import_transcript(raw, "source-a", "transcript.json")


@pytest.mark.parametrize(
    "payload",
    [
        {"segments": [{"text": "hello", "start_ms": 1000, "end_ms": 2000}]},
        {
            "utterances": [{"text": "hello", "start_ms": 1000, "end_ms": 2000}],
            "words": [],
        },
    ],
)
def test_explicit_milliseconds_survive_vendor_shaped_envelopes(payload: dict) -> None:
    record = import_transcript(json.dumps(payload), "source-a", "transcript.json")

    assert (record["turns"][0]["start_ms"], record["turns"][0]["end_ms"]) == (
        1000,
        2000,
    )


def test_ignored_blank_segment_does_not_shift_estimated_status() -> None:
    record = import_transcript(
        json.dumps(
            {
                "segments": [
                    {"text": "  ", "start": 0, "end": 1},
                    {
                        "text": "hello",
                        "start": 1,
                        "end": 2,
                        "time_estimated": True,
                    },
                ]
            }
        ),
        "source-a",
        "whisper.json",
    )

    assert record["turns"][0]["time_estimated"] is True
    assert any("estimated" in warning for warning in record["warnings"])


@pytest.mark.parametrize(
    ("filename", "raw"),
    [
        (
            "captions.srt",
            ("1\n00:00:01,000 --> 00:00:02,000\nYes.\n\n2\n00:00:05,000 --> 00:00:06,000\nYes.\n"),
        ),
        (
            "captions.vtt",
            (
                "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nYes.\n\n"
                "00:00:05.000 --> 00:00:06.000\nYes.\n"
            ),
        ),
    ],
)
def test_repeated_subtitle_text_at_distinct_times_remains_two_cues(filename: str, raw: str) -> None:
    record = import_transcript(raw, "source-a", filename)

    assert [(turn["text"], turn["start_ms"], turn["end_ms"]) for turn in record["turns"]] == [
        ("Yes.", 1000, 2000),
        ("Yes.", 5000, 6000),
    ]


@pytest.mark.parametrize(
    "segment",
    [
        {"text": {"unexpected": "object"}, "start": 1, "end": 2},
        {"text": "hello", "start": 1e308, "end": 1e308},
    ],
)
def test_malformed_vendor_fields_raise_validation_errors(segment: dict) -> None:
    with pytest.raises(ValueError):
        import_transcript(
            json.dumps({"segments": [segment]}),
            "source-a",
            "whisper.json",
        )


def test_azure_missing_duration_stays_unknown_and_word_ticks_are_preserved() -> None:
    record = import_transcript(
        json.dumps(
            {
                "recognizedPhrases": [
                    {
                        "offsetInTicks": 10_000_000,
                        "nBest": [
                            {
                                "display": "hello",
                                "words": [
                                    {
                                        "word": "hello",
                                        "offsetInTicks": 10_000_000,
                                        "durationInTicks": 2_000_000,
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        ),
        "source-a",
        "azure.json",
    )

    assert (record["turns"][0]["start_ms"], record["turns"][0]["end_ms"]) == (
        1000,
        None,
    )
    assert (record["words"][0]["start_ms"], record["words"][0]["end_ms"]) == (
        1000,
        1200,
    )
    assert any("unknown timing" in warning for warning in record["warnings"])


def test_generic_time_interpretation_is_part_of_record_identity() -> None:
    raw = '[{"text":"hello","start":1,"end":2}]'
    seconds = import_transcript(raw, "source-a", "transcript.json", time_unit="seconds")
    milliseconds = import_transcript(raw, "source-a", "transcript.json", time_unit="milliseconds")

    assert seconds["id"] != milliseconds["id"]


def test_output_identity_is_stable_and_bound_to_source_and_content() -> None:
    first = import_transcript("Speaker: hello", "source-a", "notes.txt")
    repeated = import_transcript("Speaker: hello", "source-a", "notes.txt")
    other_source = import_transcript("Speaker: hello", "source-b", "notes.txt")

    assert first["id"] == repeated["id"]
    assert first["id"] != other_source["id"]
    assert first["source_id"] == "source-a"
    assert set(first) == {
        "id",
        "source_id",
        "format",
        "raw_text",
        "turns",
        "words",
        "warnings",
    }


def test_public_transcript_examples_remain_importable() -> None:
    examples = Path(__file__).parents[1] / "examples" / "transcripts"

    for path in sorted(examples.iterdir()):
        record = import_transcript(path.read_text(), "example-source", path.name)
        assert record["turns"], path.name


def test_generic_transcript_envelope_imports_timed_turns_and_validates_leaf_text() -> None:
    raw = json.dumps({"transcript": [{"transcript": "Hello", "start_ms": 1000, "end_ms": 2000}]})
    record = import_transcript(raw, "source-a", "captions.json")
    assert record["format"] == "json:generic_dict"
    assert [(turn["text"], turn["start_ms"], turn["end_ms"]) for turn in record["turns"]] == [
        ("Hello", 1000, 2000)
    ]
    assert record["raw_text"] == raw
    with pytest.raises(ValueError, match="must be text"):
        import_transcript(
            json.dumps({"transcript": [{"transcript": ["bad leaf"]}]}),
            "source-a",
            "captions.json",
        )


@pytest.mark.parametrize("container", ["segments", "utterances"])
def test_vendor_envelope_preserves_explicit_word_milliseconds(container: str) -> None:
    word = {"word": "Hello", "start_ms": 1100, "end_ms": 1800, "time_estimated": True}
    payload = {container: [{"text": "Hello", "start_ms": 1000, "end_ms": 2000, "words": [word]}]}
    if container == "utterances":
        payload["words"] = []
    record = import_transcript(json.dumps(payload), "source-a", "captions.json")
    assert (record["words"][0]["start_ms"], record["words"][0]["end_ms"]) == (1100, 1800)
    assert record["words"][0]["raw"] == word
    assert record["words"][0]["provenance"]["path"] == [container, 0, "words", 0]
    assert record["turns"][0]["time_estimated"] is True


@pytest.mark.parametrize("field,value", [("start", 1.1), ("end", 1.8)])
def test_conflicting_explicit_and_vendor_word_times_are_rejected(field: str, value: float) -> None:
    word = {"word": "Hello", "start_ms": 1100, "end_ms": 1800, field: value}
    with pytest.raises(ValueError, match="declares both"):
        import_transcript(
            json.dumps({"segments": [{"text": "Hello", "start": 1, "end": 2, "words": [word]}]}),
            "source-a",
            "captions.json",
        )


@pytest.mark.parametrize("estimate_key", ["time_estimated", "timing_estimated", "estimated"])
@pytest.mark.parametrize("vendor", ["azure", "deepgram", "assemblyai"])
def test_source_estimated_timing_survives_audited_vendor_layouts(vendor, estimate_key):
    if vendor == "azure":
        payload = {
            "recognizedPhrases": [
                {
                    "offsetInTicks": 10_000_000,
                    "durationInTicks": 10_000_000,
                    estimate_key: True,
                    "nBest": [{"display": "hello"}],
                }
            ]
        }
        expected = ("hello", 1000, 2000)
    elif vendor == "deepgram":
        payload = {
            "results": {
                "channels": [
                    {
                        "alternatives": [
                            {
                                "transcript": "hello",
                                "paragraphs": {
                                    "transcript": "hello",
                                    "paragraphs": [
                                        {
                                            "start": 1,
                                            "end": 2,
                                            estimate_key: True,
                                            "sentences": [{"text": "hello", "start": 1, "end": 2}],
                                        }
                                    ],
                                },
                            }
                        ]
                    }
                ]
            }
        }
        expected = ("hello", 1000, 2000)
    else:
        payload = {
            "id": "a",
            "utterances": [],
            "words": [
                {"text": "hello", "start": 1000, estimate_key: True},
                {"text": "there", "start": 2000, "end": 3000},
            ],
        }
        expected = ("hello there", 1000, 3000)
    raw = json.dumps(payload)
    record = import_transcript(raw, "audit-recording", vendor + ".json")
    assert [(t["text"], t["start_ms"], t["end_ms"]) for t in record["turns"]] == [expected]
    assert [t["time_estimated"] for t in record["turns"]] == [True]
    assert any("estimated" in warning for warning in record["warnings"])
    assert record["raw_text"] == raw
    assert record["source_id"] == "audit-recording"
    if vendor == "assemblyai":
        assert record["words"][0]["end_ms"] is None
        assert record["words"][0]["raw"] == payload["words"][0]


@pytest.mark.parametrize("precise_start", [1, 2])
@pytest.mark.parametrize("word_bounds", [{}, {"start": 1}, {"end": 2}, {"start": 1, "end": 2}])
def test_nested_word_estimates_belong_only_to_their_source_turn(precise_start, word_bounds):
    payload = {
        "segments": [
            {
                "text": "estimated",
                "speaker": "A",
                "start": 1,
                "end": 2,
                "words": [{"word": "estimated", "time_estimated": True, **word_bounds}],
            },
            {"text": "precise", "speaker": "B", "start": precise_start, "end": 3},
        ]
    }
    record = import_transcript(json.dumps(payload), "source-a", "whisper.json")
    assert [t["time_estimated"] for t in record["turns"]] == [True, False]
    assert [(t["start_ms"], t["end_ms"]) for t in record["turns"]] == [
        (1000, 2000),
        (precise_start * 1000, 3000),
    ]


def test_word_group_estimates_follow_parser_selection_and_normalized_speakers():
    payload = {
        "id": "a",
        "utterances": [],
        "words": [
            {"text": " ", "speaker": "skipped", "start": 0, "end": 100, "estimated": True},
            {"text": "hello", "speaker": 0, "start": 1000, "estimated": True},
            {"text": "", "speaker": "ignored", "start": 1500, "end": 1600},
            {"text": "there", "speaker": "00", "start": 2000, "end": 3000},
            {"text": "precise", "speaker": 1, "start": 1000, "end": 3000},
        ],
    }
    record = import_transcript(json.dumps(payload), "source-a", "assembly.json")
    assert record["turns"] == [
        {
            "text": "hello there",
            "speaker": "SPEAKER_00",
            "start_ms": 1000,
            "end_ms": 3000,
            "time_estimated": True,
        },
        {
            "text": "precise",
            "speaker": "SPEAKER_01",
            "start_ms": 1000,
            "end_ms": 3000,
            "time_estimated": False,
        },
    ]


def test_azure_estimates_skip_empty_phrases_and_keep_missing_duration():
    payload = {
        "recognizedPhrases": [
            {
                "offsetInTicks": 0,
                "durationInTicks": 1_000_000,
                "estimated": True,
                "nBest": [{"display": " "}],
            },
            {
                "offsetInTicks": 10_000_000,
                "timing_estimated": True,
                "nBest": [{"lexical": "uncertain"}],
            },
            {
                "offsetInTicks": 20_000_000,
                "durationInTicks": 10_000_000,
                "nBest": [{"display": "precise"}],
            },
        ]
    }
    record = import_transcript(json.dumps(payload), "source-a", "azure.json")
    assert [
        (t["text"], t["start_ms"], t["end_ms"], t["time_estimated"]) for t in record["turns"]
    ] == [("uncertain", 1000, None, True), ("precise", 2000, 3000, False)]


def test_deepgram_selected_paragraphs_preserve_sentence_estimates_only():
    payload = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "paragraphs": {
                                "paragraphs": [
                                    {
                                        "start": 0,
                                        "end": 0.5,
                                        "estimated": True,
                                        "sentences": [{"text": " "}],
                                    },
                                    {
                                        "sentences": [
                                            {
                                                "text": "uncertain",
                                                "start": 1,
                                                "end": 2,
                                                "estimated": True,
                                            }
                                        ]
                                    },
                                    {"start": 2, "end": 3, "sentences": [{"text": "precise"}]},
                                ]
                            }
                        },
                        {"words": [{"word": "discarded", "start": 2, "end": 3, "estimated": True}]},
                    ]
                }
            ]
        }
    }
    record = import_transcript(json.dumps(payload), "source-a", "deepgram.json")
    assert [
        (t["text"], t["start_ms"], t["end_ms"], t["time_estimated"]) for t in record["turns"]
    ] == [("uncertain", 1000, 2000, True), ("precise", 2000, 3000, False)]
    assert record["words"][0]["raw"]["estimated"] is True


def test_explicit_unit_shadow_keeps_its_estimate_association():
    payload = {
        "segments": [
            {"text": " ", "content": "unused", "start_ms": 0, "end_ms": 100, "estimated": False},
            {"content": "estimated", "start_ms": 1000, "end_ms": 2000, "estimated": True},
            {"text": "precise", "start_ms": 2000, "end_ms": 3000},
        ]
    }
    record = import_transcript(json.dumps(payload), "source-a", "whisper.json")
    assert [(t["text"], t["time_estimated"]) for t in record["turns"]] == [
        ("estimated", True),
        ("precise", False),
    ]


@pytest.mark.parametrize("extra", [{"estimated": True}, {"timing_estimated": True}])
def test_positive_estimate_alias_is_not_hidden_by_another_false_alias(extra):
    record = import_transcript(
        json.dumps(
            [
                {
                    "text": "uncertain",
                    "start_ms": 1000,
                    "end_ms": 2000,
                    "time_estimated": False,
                    **extra,
                }
            ]
        ),
        "source-a",
        "generic.json",
    )
    assert record["turns"][0]["time_estimated"] is True


@pytest.mark.parametrize("estimate_key", ["time_estimated", "timing_estimated", "estimated"])
def test_azure_estimate_alias_requires_a_boolean(estimate_key):
    with pytest.raises(ValueError, match="true or false"):
        import_transcript(
            json.dumps(
                {
                    "recognizedPhrases": [
                        {
                            "offsetInTicks": 10_000_000,
                            "durationInTicks": 10_000_000,
                            estimate_key: "true",
                            "nBest": [{"display": "hello"}],
                        }
                    ]
                }
            ),
            "source-a",
            "azure.json",
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "results": {
                "channels": [
                    {
                        "alternatives": [
                            {"words": [{"word": "hello", "start": 1, "end": 2, "estimated": True}]}
                        ]
                    }
                ]
            }
        },
        {
            "results": [
                {
                    "alternatives": [
                        {
                            "words": [
                                {
                                    "word": "hello",
                                    "startTime": "1s",
                                    "endTime": "2s",
                                    "estimated": True,
                                }
                            ]
                        }
                    ]
                }
            ]
        },
        {
            "results": [
                {
                    "start_time": 1,
                    "end_time": 2,
                    "estimated": True,
                    "alternatives": [{"content": "hello"}],
                }
            ]
        },
        {
            "results": {
                "items": [
                    {
                        "type": "pronunciation",
                        "start_time": "1",
                        "end_time": "2",
                        "estimated": True,
                        "alternatives": [{"content": "hello"}],
                    }
                ]
            }
        },
        {
            "monologues": [
                {
                    "speaker": 0,
                    "elements": [{"value": "hello", "ts": 1, "end_ts": 2, "estimated": True}],
                }
            ]
        },
    ],
)
def test_other_selected_vendor_word_sources_preserve_estimates(payload):
    record = import_transcript(json.dumps(payload), "source-a", "vendor.json")
    assert record["turns"][0]["time_estimated"] is True
    assert (record["turns"][0]["start_ms"], record["turns"][0]["end_ms"]) == (1000, 2000)


def test_google_last_cumulative_result_owns_its_estimated_status():
    payload = {
        "results": [
            {
                "alternatives": [
                    {
                        "words": [
                            {"word": "old", "startTime": "1s", "endTime": "2s", "estimated": True}
                        ]
                    }
                ]
            },
            {
                "alternatives": [
                    {"words": [{"word": "precise", "startTime": "1s", "endTime": "2s"}]}
                ]
            },
        ]
    }
    record = import_transcript(json.dumps(payload), "source-a", "google.json")
    assert record["turns"] == [
        {
            "text": "precise",
            "speaker": None,
            "start_ms": 1000,
            "end_ms": 2000,
            "time_estimated": False,
        }
    ]
    assert record["words"][0]["time_estimated"] is True


@pytest.mark.parametrize("key", ["words", "sentences"])
@pytest.mark.parametrize("invalid", [1, True, "invalid", {}])
def test_selected_annotations_reject_non_list_containers(key, invalid):
    payload = {"segments": [{"text": "hello", "start": 1, "end": 2, key: invalid}]}
    with pytest.raises(ValueError, match=f"{key} must be a list"):
        import_transcript(json.dumps(payload), "source-a", "whisper.json")
