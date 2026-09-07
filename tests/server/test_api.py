import io

import numpy as np
import soundfile as sf
from conftest import project_with_source, wait_job, wav_bytes


def test_real_upload_peaks_audio_and_revision_history(client):
    samples = np.tile(np.array([-0.5, 0.25, 0.75, -0.125], dtype="float32"), 24_000)
    project = project_with_source(client, samples)
    pid, sid = project["id"], project["sources"][0]["id"]
    peaks = client.get(
        f"/api/projects/{pid}/peaks",
        params={"source_id": sid, "start_frame": 0, "end_frame": 8, "bins": 2},
    )
    assert peaks.status_code == 200, peaks.text
    assert peaks.json()["min"] == [-0.5, -0.5]
    assert peaks.json()["max"] == [0.75, 0.75]
    audio = client.get(f"/api/projects/{pid}/audio?mode=original&start_frame=4&end_frame=12")
    assert audio.status_code == 200
    pcm, rate = sf.read(io.BytesIO(audio.content))
    np.testing.assert_array_equal(pcm, samples[4:12])
    assert rate == 48_000
    assert audio.headers["X-CleanTake-Start-Frame"] == "4"
    assert audio.headers["X-CleanTake-Revision"] == str(project["revision"])
    edit = client.patch(
        f"/api/projects/{pid}", json={"name": "Saved", "expected_revision": project["revision"]}
    )
    assert edit.status_code == 200
    revision = edit.json()["revision"]
    conflict = client.patch(
        f"/api/projects/{pid}", json={"name": "Lost", "expected_revision": project["revision"]}
    )
    assert conflict.status_code == 409
    undo = client.post(f"/api/projects/{pid}/undo", json={"expected_revision": revision}).json()
    assert undo["name"] == "Interview Ω" and undo["can_redo"]
    redo = client.post(
        f"/api/projects/{pid}/redo", json={"expected_revision": undo["revision"]}
    ).json()
    assert redo["name"] == "Saved"


def test_analysis_manual_repair_audition_transcript_export_and_scoped_ranges(client):
    rng = np.random.default_rng(42)
    donor = rng.normal(0, 0.1, 288_000).astype("float32")
    main = donor.copy()
    main[120_000:144_000] = 0
    project = project_with_source(client, main)
    pid = project["id"]
    imported = client.post(
        f"/api/projects/{pid}/sources", files={"file": ("Backup.wav", wav_bytes(donor))}
    )
    assert wait_job(client, imported.json())["status"] == "completed"
    project = client.get(f"/api/projects/{pid}").json()
    sid = project["sources"][1]["id"]
    assert (
        client.get(
            f"/api/projects/{pid}/audio?mode=source&source_id={sid}&end_frame=48000"
        ).status_code
        == 422
    )
    own = client.get(f"/api/projects/{pid}/peaks?source_id={sid}&end_frame=48000&bins=1").json()
    assert own["aligned"] is False
    analyzed = client.post(
        f"/api/projects/{pid}/analyze", json={"expected_revision": project["revision"]}
    )
    assert analyzed.status_code == 202
    assert wait_job(client, analyzed.json())["status"] == "completed"
    project = client.get(f"/api/projects/{pid}").json()
    # Explicit review of an independently specified donor interval.
    manual = client.post(
        f"/api/projects/{pid}/repairs",
        json={
            "start_frame": 120_000,
            "end_frame": 144_000,
            "source_id": sid,
            "kind": "manual",
            "gain_db": 0,
            "fade_ms": 0,
            "expected_revision": project["revision"],
        },
    )
    assert manual.status_code == 200, manual.text
    project = manual.json()
    repair = project["repairs"][-1]
    project = client.patch(
        f"/api/projects/{pid}/repairs/{repair['id']}",
        json={"status": "accepted", "expected_revision": project["revision"]},
    ).json()
    audio = client.get(
        f"/api/projects/{pid}/audio?mode=repaired&start_frame=121000&end_frame=122000"
    )
    assert audio.status_code == 200, audio.text
    pcm, _ = sf.read(io.BytesIO(audio.content))
    np.testing.assert_allclose(pcm, donor[121000:122000], atol=1e-5)
    transcript = client.post(
        f"/api/projects/{pid}/transcript",
        json={
            "text": "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<script>hello</script>\n",
            "source_id": sid,
            "filename": "words.vtt",
            "expected_revision": project["revision"],
        },
    )
    assert transcript.status_code == 200, transcript.text
    project = transcript.json()
    assert "<script>hello</script>" in project["transcripts"][0]["raw_text"]
    exported = client.post(
        f"/api/projects/{pid}/exports",
        json={"format": "wav", "finish": False, "expected_revision": project["revision"]},
    )
    job = wait_job(client, exported.json())
    assert job["status"] == "completed", job
    result = job["result"]
    assert result["revision"] == project["revision"]
    artifact = next(item["name"] for item in result["artifacts"] if item["name"].endswith(".wav"))
    path = f"/api/projects/{pid}/exports/{result['export_id']}/{artifact}"
    full = client.get(path)
    assert full.status_code == 200
    part = client.get(path, headers={"Range": "bytes=0-15"})
    assert part.status_code == 206
    assert part.content == full.content[:16]
    assert client.get(path, headers={"Range": "bytes=999999999-"}).status_code == 416
    ticket = client.post(path + "/ticket").json()
    client.headers.pop("X-CleanTake-Token")
    assert client.get(path).status_code == 401
    assert client.get(ticket["url"]).content == full.content
    query = ticket["url"].split("?", 1)[1]
    assert client.get("/api/projects?" + query).status_code == 401
    other = path.rsplit("/", 1)[0] + "/source-map.json?" + query
    assert client.get(other).status_code == 401


def test_invalid_audio_parameters_and_broken_media_fail_clearly(client):
    project = project_with_source(client)
    pid = project["id"]
    for query in (
        "mode=surprise",
        "start_frame=-1",
        "start_frame=1.5",
        "end_frame=0",
        "end_frame=96001",
        "mode=source",
        "source_id=unknown",
    ):
        result = client.get(f"/api/projects/{pid}/audio?{query}")
        assert result.status_code == 422, (query, result.text)
    for query in ("bins=0", "bins=4097", "bins=2.5", "source_id=unknown"):
        result = client.get(f"/api/projects/{pid}/peaks?{query}")
        assert result.status_code == 422
    response = client.post(
        f"/api/projects/{pid}/sources", files={"file": ("bad.mp4", b"not media")}
    )
    job = wait_job(client, response.json())
    assert job["status"] == "failed"
    assert "readable audio" in job["error"]
    assert "/" not in job["error"]
    assert client.get(f"/api/projects/{pid}").json()["revision"] == project["revision"]


def test_portable_archive_round_trip_and_nested_artifact_tickets(client):
    original = project_with_source(client)
    pid = original["id"]
    response = client.post(
        f"/api/projects/{pid}/archive", json={"expected_revision": original["revision"]}
    )
    job = wait_job(client, response.json())
    assert job["status"] == "completed", job
    archive = job["result"]["artifacts"][0]
    path = f"/api/projects/{pid}/exports/{job['result']['export_id']}/{archive['name']}"
    data = client.get(path).content
    imported = client.post("/api/projects/import", files={"file": ("portable.zip", data)})
    reopened = wait_job(client, imported.json())
    assert reopened["status"] == "completed", reopened
    new_pid = reopened["result"]["project_id"]
    assert new_pid != pid
    saved = client.get(f"/api/projects/{new_pid}").json()
    assert saved["sources"][0]["sha256"] == original["sources"][0]["sha256"]
    exported = wait_job(
        client,
        client.post(
            f"/api/projects/{pid}/exports", json={"expected_revision": original["revision"]}
        ).json(),
    )
    result = exported["result"]
    stem = next(item for item in result["artifacts"] if item["name"].startswith("stems/"))
    path = f"/api/projects/{pid}/exports/{result['export_id']}/{stem['name']}"
    full = client.get(path)
    ticket = client.post(path + "/ticket")
    assert ticket.status_code == 200
    client.headers.pop("X-CleanTake-Token")
    assert client.get(ticket.json()["url"]).content == full.content


def test_artifact_range_errors_keep_json_envelope(client):
    project = project_with_source(client)
    pid = project["id"]
    job = wait_job(
        client,
        client.post(
            f"/api/projects/{pid}/exports", json={"expected_revision": project["revision"]}
        ).json(),
    )
    path = f"/api/projects/{pid}/exports/{job['result']['export_id']}/dialogue.wav"
    for header in ("bytes=999999999-", "bytes=20-3", "nonsense", "bytes=0-2,4-8"):
        response = client.get(path, headers={"Range": header})
        assert response.status_code in {400, 416}
        assert response.json()["error"]["code"] == "invalid_range"


def test_manual_source_transform_drives_peaks_and_audio_and_null_is_invalid(client):
    main = np.tile(np.array([0.1, 0.2, 0.3, 0.4], dtype="float32"), 24_000)
    donor = np.tile(np.array([-0.2, -0.4, -0.6, -0.8], dtype="float32"), 24_000)
    project = project_with_source(client, main)
    pid = project["id"]
    uploaded = client.post(
        f"/api/projects/{pid}/sources", files={"file": ("donor.wav", wav_bytes(donor))}
    )
    assert wait_job(client, uploaded.json())["status"] == "completed"
    project = client.get(f"/api/projects/{pid}").json()
    sid = project["sources"][1]["id"]
    patched = client.patch(
        f"/api/projects/{pid}/sources/{sid}",
        json={
            "alignment": {"offset_seconds": 0.0000625, "drift_ppm": 0, "polarity": -1},
            "expected_revision": project["revision"],
        },
    )
    assert patched.status_code == 200, patched.text
    project = patched.json()
    assert project["sources"][1]["alignment"]["status"] == "manual"
    response = client.get(
        f"/api/projects/{pid}/audio?mode=source&source_id={sid}&start_frame=0&end_frame=4"
    )
    pcm, _ = sf.read(io.BytesIO(response.content))
    np.testing.assert_array_equal(pcm, -donor[3:7])
    peaks = client.get(
        f"/api/projects/{pid}/peaks?source_id={sid}&start_frame=0&end_frame=4&bins=1"
    ).json()
    assert peaks["aligned"] is True
    assert peaks["coverage"] == [0, 95997]
    np.testing.assert_allclose(peaks["min"], [0.2])
    np.testing.assert_allclose(peaks["max"], [0.8])
    invalid = client.patch(
        f"/api/projects/{pid}/sources/{sid}",
        json={"alignment": None, "expected_revision": project["revision"]},
    )
    assert invalid.status_code == 422


def test_recording_limit_rejects_before_publishing_import(client):
    client.app.state.limits.max_recording_seconds = 1
    project = client.post("/api/projects", json={"name": "Duration limit"}).json()
    response = client.post(
        f"/api/projects/{project['id']}/sources", files={"file": ("two-seconds.wav", wav_bytes())}
    )
    job = wait_job(client, response.json())
    assert job["status"] == "failed"
    assert "duration limit" in job["error"]
    assert client.get(f"/api/projects/{project['id']}").json()["sources"] == []
