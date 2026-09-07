import { useEffect, useState } from "react";
import {
  api,
  projectPath,
  type Peaks,
  type Project,
  type Repair,
  type Source,
} from "./api";

interface Props {
  project: Project;
  source?: Source;
  start: number;
  end: number;
  frame: number;
  selected?: Repair;
  onSeek: (frame: number) => void;
  onRepair: (repair: Repair) => void;
  onError: (message: string) => void;
}
export function Waveform({
  project,
  source,
  start,
  end,
  frame,
  selected,
  onSeek,
  onRepair,
  onError,
}: Props) {
  const [peaks, setPeaks] = useState<Peaks>();
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setFailed(false);
    setPeaks(undefined);
    const params = new URLSearchParams({
      start_frame: String(start),
      end_frame: String(end),
      bins: "1200",
    });
    if (source) params.set("source_id", source.id);
    else params.set("mode", "repaired");
    api<Peaks>(
      `${projectPath(project.id)}/peaks?${params}`,
      "GET",
      undefined,
      controller.signal,
    )
      .then((result) => {
        if (controller.signal.aborted) return;
        if (result.revision !== project.revision) {
          setFailed(true);
          onError(
            "The project changed while loading waveforms. Refresh the project.",
          );
          return;
        }
        setPeaks(result);
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setFailed(true);
          onError(error.message);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [project.id, project.revision, source?.id, start, end, retry]);
  const width = end - start;
  const percent = (position: number) => ((position - start) / width) * 100;
  const count = peaks?.min.length || 0;
  const path = peaks?.min
    .map((minimum, i) => {
      const x = (((i + 0.5) / count) * 1200).toFixed(2);
      return `M${x},${(42 - Math.max(-1, Math.min(1, peaks.max[i])) * 35).toFixed(2)}V${(42 - Math.max(-1, Math.min(1, minimum)) * 35).toFixed(2)}`;
    })
    .join(" ");
  const ownClock =
    peaks?.aligned === false || source?.alignment.status === "uncertain";
  return (
    <div className={`waveform ${ownClock ? "own-clock" : ""}`}>
      <button
        className="wave-seek"
        aria-label={`Seek in ${source?.name || "repaired output"} waveform`}
        onClick={(event) => {
          if (ownClock) return;
          const bounds = event.currentTarget.getBoundingClientRect();
          onSeek(
            Math.round(
              start + ((event.clientX - bounds.left) / bounds.width) * width,
            ),
          );
        }}
        disabled={ownClock}
        tabIndex={-1}
      >
        <svg
          viewBox="0 0 1200 84"
          preserveAspectRatio="none"
          role="img"
          aria-label={
            ownClock
              ? `${source?.name}: actual waveform in its own clock, not synchronized`
              : `${source?.name || "Repaired output"}: actual audio waveform`
          }
        >
          <path className="zero-line" d="M0 42H1200" />
          {path && <path className="wave-ink" d={path} />}
        </svg>
      </button>
      {loading && <span className="wave-status">Loading waveform…</span>}
      {failed && (
        <button className="wave-retry" onClick={() => setRetry(retry + 1)}>
          Retry waveform
        </button>
      )}
      {ownClock && (
        <span className="clock-note">Own clock · alignment needed</span>
      )}
      {!ownClock &&
        selected &&
        selected.end_frame > start &&
        selected.start_frame < end && (
          <div
            className="selection-band"
            style={{
              left: `${Math.max(0, percent(selected.start_frame))}%`,
              width: `${Math.min(100, percent(selected.end_frame)) - Math.max(0, percent(selected.start_frame))}%`,
            }}
          />
        )}
      {!source &&
        project.repairs
          .filter(
            (repair) =>
              repair.status === "accepted" &&
              repair.end_frame > start &&
              repair.start_frame < end,
          )
          .map((repair) => (
            <button
              key={repair.id}
              className="accepted-span"
              style={{
                left: `${Math.max(0, percent(repair.start_frame))}%`,
                width: `${Math.min(100, percent(repair.end_frame)) - Math.max(0, percent(repair.start_frame))}%`,
              }}
              onClick={() => onRepair(repair)}
              title={`Accepted: ${project.sources.find((item) => item.id === repair.source_id)?.name}`}
              aria-label={`Inspect accepted repair from ${project.sources.find((item) => item.id === repair.source_id)?.name}`}
            >
              {
                project.sources.find((item) => item.id === repair.source_id)
                  ?.name
              }
            </button>
          ))}
      {!ownClock && frame >= start && frame <= end && (
        <div className="playhead" style={{ left: `${percent(frame)}%` }} />
      )}
      {peaks && !ownClock && (
        <>
          {peaks.coverage[0] > start && (
            <div
              className="no-coverage"
              style={{
                left: 0,
                width: `${Math.min(100, percent(peaks.coverage[0]))}%`,
              }}
            />
          )}
          {peaks.coverage[1] < end && (
            <div
              className="no-coverage"
              style={{
                right: 0,
                width: `${Math.min(100, 100 - percent(peaks.coverage[1]))}%`,
              }}
            />
          )}
        </>
      )}
    </div>
  );
}
