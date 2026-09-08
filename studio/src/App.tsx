import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  AudioLines,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  FileText,
  FolderOpen,
  Headphones,
  HelpCircle,
  LoaderCircle,
  Pause,
  Play,
  Plus,
  Redo2,
  RotateCcw,
  Settings2,
  ShieldCheck,
  SkipBack,
  SlidersHorizontal,
  Trash2,
  Undo2,
  Upload,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  api,
  ApiError,
  hasSession,
  projectPath,
  time,
  type AudioMode,
  type ExportResult,
  type Job,
  type Project,
  type Repair,
  type Source,
  type Summary,
} from "./api";
import { TimelinePlayer, type PlaybackState } from "./audio";
import { Waveform } from "./Waveform";

const colors = ["#3459a2", "#277b74", "#88628d", "#9a6936"];
const initialPlayback = { playing: false, loading: false, frame: 0 };
const terminal = (job: Job) => !["queued", "running"].includes(job.status);
const classStatus = (status: string) =>
  status === "accepted" ||
  status === "aligned" ||
  status === "manual" ||
  status === "reference"
    ? "good"
    : status === "rejected"
      ? "muted"
      : "warning";
function IconButton({
  label,
  children,
  ...props
}: {
  label: string;
  children: ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className="icon-button"
      aria-label={label}
      title={label}
      {...props}
    >
      {children}
    </button>
  );
}
function FormField({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
    </label>
  );
}
function Confirmation({
  title,
  message,
  confirm,
  onClose,
}: {
  title: string;
  message: string;
  confirm: () => Promise<void>;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [working, setWorking] = useState(false);
  useEffect(() => {
    ref.current?.showModal();
    return () => ref.current?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      onCancel={(event) => {
        event.preventDefault();
        if (!working) onClose();
      }}
      aria-labelledby="confirmation-title"
    >
      <div className="dialog-content">
        <h2 id="confirmation-title">{title}</h2>
        <p>{message}</p>
        <div className="actions">
          <button autoFocus onClick={onClose} disabled={working}>
            Keep current project
          </button>
          <button
            className="danger"
            disabled={working}
            onClick={async () => {
              setWorking(true);
              try {
                await confirm();
                onClose();
              } finally {
                setWorking(false);
              }
            }}
          >
            {working ? "Applying…" : title}
          </button>
        </div>
      </div>
    </dialog>
  );
}

export default function App() {
  const [projects, setProjects] = useState<Summary[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [shelf, setShelf] = useState(true);
  const [opening, setOpening] = useState(false);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedId, setSelectedId] = useState<string>();
  const [sourceId, setSourceId] = useState<string>();
  const [sourceSettings, setSourceSettings] = useState<string>();
  const [filter, setFilter] = useState("review");
  const [panel, setPanel] = useState<"transcript" | "export" | "help" | null>(
    null,
  );
  const [manual, setManual] = useState(false);
  const [mode, setMode] = useState<AudioMode>("repaired");
  const [playback, setPlayback] = useState<PlaybackState>(initialPlayback);
  const [windowStart, setWindowStart] = useState(0);
  const [windowSize, setWindowSize] = useState(0);
  const [exports, setExports] = useState<ExportResult[]>([]);
  const [confirmation, setConfirmation] = useState<{
    title: string;
    message: string;
    confirm: () => Promise<void>;
  }>();
  const [session, setSession] = useState(hasSession());
  const [importChannel, setImportChannel] = useState("");
  const [importStream, setImportStream] = useState("");
  const mediaInput = useRef<HTMLInputElement>(null);
  const archiveInput = useRef<HTMLInputElement>(null);
  const projectRef = useRef<Project | null>(null);
  const player = useRef<TimelinePlayer | null>(null);
  const openingSequence = useRef(0);
  const currentBusy = busy || Boolean(job && !terminal(job));
  projectRef.current = project;
  if (!player.current)
    player.current = new TimelinePlayer(setPlayback, setError);
  const showError = useCallback((message: string) => setError(message), []);
  const refreshShelf = useCallback(async () => {
    const data = await api<{ projects: Summary[] }>("/projects");
    setProjects(data.projects);
  }, []);
  useEffect(() => {
    if (session) void refreshShelf().catch((error) => setError(error.message));
    return () => {
      player.current?.stop();
    };
  }, [session, refreshShelf]);
  useEffect(() => {
    return () => {
      player.current?.dispose();
    };
  }, []);
  useEffect(() => {
    player.current?.stop();
  }, [project?.id, project?.revision]);
  const report = useCallback(async (error: unknown) => {
    if (
      error instanceof ApiError &&
      error.status === 409 &&
      projectRef.current
    ) {
      const updated = await api<Project>(
        projectPath(projectRef.current.id),
      ).catch(() => null);
      if (updated) setProject(updated);
      setError(
        `${error.message} The latest saved project has been loaded. Review it before applying your change again.`,
      );
    } else if (error instanceof ApiError && error.status === 401) {
      setError(
        "This session is no longer valid. Reopen the studio from the running CleanTake process.",
      );
      setSession(false);
    } else
      setError(
        error instanceof Error
          ? error.message
          : "The action could not be completed. Try again.",
      );
  }, []);
  const loadProject = async (id: string) => {
    const sequence = ++openingSequence.current;
    player.current?.stop();
    setOpening(true);
    setError("");
    try {
      const item = await api<Project>(projectPath(id));
      if (sequence !== openingSequence.current) return;
      setProject(item);
      setShelf(false);
      setSelectedId(undefined);
      setSourceSettings(undefined);
      setManual(false);
      setPanel(null);
      setSourceId(
        item.sources.find((source) => source.id !== item.primary_source_id)?.id,
      );
      setWindowStart(0);
      setWindowSize(item.duration_frames || 1);
      setPlayback(initialPlayback);
      player.current?.seek(0);
      setExports([]);
    } catch (error) {
      await report(error);
    } finally {
      if (sequence === openingSequence.current) setOpening(false);
    }
  };
  const action = async (operation: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await operation();
    } catch (error) {
      await report(error);
    } finally {
      setBusy(false);
    }
  };
  const mutate = async (
    suffix: string,
    method: string,
    payload: Record<string, unknown> = {},
  ) => {
    const item = projectRef.current;
    if (!item) return;
    player.current?.stop();
    const updated = await api<Project>(
      `${projectPath(item.id)}${suffix}`,
      method,
      { ...payload, expected_revision: item.revision },
    );
    setProject(updated);
    projectRef.current = updated;
    setNotice(`Saved · revision ${updated.revision}`);
    await refreshShelf();
  };
  const watchJob = async (initial: Job): Promise<Job> => {
    let current = initial;
    setJob(current);
    while (!terminal(current)) {
      await new Promise((resolve) => window.setTimeout(resolve, 500));
      current = await api<Job>(`/jobs/${current.id}`);
      setJob(current);
    }
    if (current.status === "completed") {
      const id = current.result?.project_id || current.project_id;
      if (id) {
        const updated = await api<Project>(projectPath(id));
        if (
          !projectRef.current ||
          updated.id === projectRef.current.id ||
          current.operation === "archive_import"
        ) {
          const isNew = updated.id !== projectRef.current?.id;
          const hadAudio = Boolean(projectRef.current?.duration_frames);
          setProject(updated);
          projectRef.current = updated;
          if (isNew || !hadAudio) {
            setWindowStart(0);
            setWindowSize(updated.duration_frames || 1);
          }
          if (
            isNew ||
            !updated.sources.some(
              (source) =>
                source.id === sourceId &&
                source.id !== updated.primary_source_id,
            )
          )
            setSourceId(
              updated.sources.find(
                (source) => source.id !== updated.primary_source_id,
              )?.id,
            );
          if (isNew) {
            setSelectedId(undefined);
            setSourceSettings(undefined);
            setManual(false);
            setPanel(null);
            setExports([]);
            player.current?.seek(0);
          }
          setShelf(false);
        }
      }
      if (current.result?.artifacts)
        setExports((previous) => [current.result as ExportResult, ...previous]);
      setNotice(current.message || `${current.operation} complete.`);
      await refreshShelf();
    } else if (current.status === "cancelled")
      setNotice("Operation cancelled. Your saved project is available.");
    else
      throw new Error(
        current.error ||
          `The ${current.operation} operation was ${current.status}. Try it again.`,
      );
    return current;
  };
  const uploadFiles = async (files: FileList | File[]) => {
    if (!projectRef.current) return;
    const items = Array.from(files);
    if (items.length + projectRef.current.sources.length > 4) {
      setError(
        "A project supports up to four recordings. Choose fewer files or create another project.",
      );
      return;
    }
    player.current?.stop();
    await action(async () => {
      for (const file of items) {
        const form = new FormData();
        form.append("file", file);
        if (importChannel !== "")
          form.append("channel", String(Number(importChannel) - 1));
        if (importStream !== "")
          form.append("stream", String(Number(importStream) - 1));
        const result = await watchJob(
          await api<Job>(
            `${projectPath(projectRef.current!.id)}/sources`,
            "POST",
            form,
          ),
        );
        if (result.status !== "completed") break;
      }
    });
  };
  const createProject = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name")).trim();
    await action(async () => {
      const item = await api<Project>("/projects", "POST", { name });
      await refreshShelf();
      await loadProject(item.id);
    });
  };
  const selected = project?.repairs.find((repair) => repair.id === selectedId);
  const duration = project?.duration_frames || 0;
  const rate = project?.sample_rate || 48000;
  const end = Math.min(duration, windowStart + (windowSize || duration));
  const source = project?.sources.find((item) => item.id === sourceId);
  const review =
    project?.repairs.filter((repair) =>
      ["proposed", "unresolved"].includes(repair.status),
    ) || [];
  const accepted =
    project?.repairs.filter((repair) => repair.status === "accepted") || [];
  const bulkEligible =
    project?.repairs.filter(
      (repair) =>
        repair.status === "proposed" &&
        repair.source_id &&
        project.sources.some(
          (item) =>
            item.id === repair.source_id &&
            item.alignment.status !== "uncertain",
        ),
    ) || [];
  const filtered =
    project?.repairs.filter(
      (repair) =>
        filter === "all" ||
        (filter === "review"
          ? ["proposed", "unresolved"].includes(repair.status)
          : repair.status === filter),
    ) || [];
  const seek = (frame: number, auditionSource = sourceId) => {
    if (currentBusy) return;
    const bounded = Math.max(0, Math.min(duration - 1, frame));
    const wasPlaying = playback.playing;
    player.current?.seek(bounded);
    if (wasPlaying && project)
      void player.current?.play(project, mode, auditionSource, bounded);
  };
  const selectRepair = (repair: Repair) => {
    setSelectedId(repair.id);
    setManual(false);
    setSourceId(repair.source_id || sourceId);
    setSourceSettings(undefined);
    const context = Math.max(
      (repair.end_frame - repair.start_frame) * 2.5,
      rate * 8,
    );
    const size = Math.min(duration, context);
    setWindowSize(size);
    setWindowStart(
      Math.max(0, Math.min(duration - size, repair.start_frame - rate * 2)),
    );
    seek(Math.max(0, repair.start_frame - rate), repair.source_id || sourceId);
  };
  const togglePlay = () => {
    if (playback.playing || playback.loading) player.current?.stop();
    else if (project && duration > 0 && !currentBusy)
      void player.current?.play(
        project,
        mode,
        sourceId,
        playback.frame >= duration ? 0 : playback.frame,
      );
  };
  const switchMode = (next: AudioMode) => {
    const frame = player.current!.position();
    const wasPlaying = playback.playing || playback.loading;
    player.current?.stop();
    setMode(next);
    if (wasPlaying && project)
      void player.current?.play(project, next, sourceId, frame);
  };
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (
        target.closest(
          "input, textarea, select, button, [contenteditable], dialog",
        )
      )
        return;
      if (event.code === "Space" && project && !shelf) {
        event.preventDefault();
        togglePlay();
      }
      if (
        (event.metaKey || event.ctrlKey) &&
        event.key.toLowerCase() === "z" &&
        !currentBusy &&
        !shelf
      ) {
        event.preventDefault();
        if (event.shiftKey ? project?.can_redo : project?.can_undo)
          void action(() => mutate(event.shiftKey ? "/redo" : "/undo", "POST"));
      }
      if (event.key === "Escape") {
        setPanel(null);
        setSourceSettings(undefined);
      }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  });
  useEffect(() => {
    if (project && playback.playing && playback.frame >= end && end < duration)
      setWindowStart(
        Math.min(duration - windowSize, Math.floor(playback.frame)),
      );
  }, [playback.frame, playback.playing, duration, end, windowSize]);
  const zoom = (factor: number) => {
    const size = Math.max(
      Math.min(rate, duration),
      Math.min(duration, (windowSize || duration) * factor),
    );
    const center = selected
      ? (selected.start_frame + selected.end_frame) / 2
      : playback.frame || windowStart + (windowSize || duration) / 2;
    setWindowStart(
      Math.round(Math.max(0, Math.min(duration - size, center - size / 2))),
    );
    setWindowSize(Math.round(size));
  };
  const applyPrimary = (id: string) => {
    const apply = async () => {
      await action(async () => {
        await mutate("", "PATCH", { primary_source_id: id });
        setSelectedId(undefined);
        setWindowStart(0);
        setWindowSize(projectRef.current?.duration_frames || 1);
        setSourceId(
          projectRef.current?.sources.find((item) => item.id !== id)?.id,
        );
        setMode("repaired");
        player.current?.seek(0);
      });
    };
    if (project?.repairs.length)
      setConfirmation({
        title: "Change primary recording",
        message:
          "The primary recording sets project time. Changing it clears repair decisions and resets every alignment. You will need to analyze the recordings again.",
        confirm: apply,
      });
    else void apply();
  };
  const download = async (result: ExportResult, artifact: string) => {
    await action(async () => {
      const ticket = await api<{ url: string }>(
        `${projectPath(project!.id)}/exports/${encodeURIComponent(result.export_id)}/${encodeURIComponent(artifact)}/ticket`,
        "POST",
      );
      const url = new URL(ticket.url, window.location.origin);
      if (url.origin !== window.location.origin)
        throw new Error(
          "The download address is outside this local studio. Re-export the project.",
        );
      const link = document.createElement("a");
      link.href = url.href;
      link.download = artifact;
      link.referrerPolicy = "no-referrer";
      document.body.append(link);
      link.click();
      link.remove();
    });
  };
  const importArchive = async (file: File | undefined) => {
    if (!file) return;
    await action(async () => {
      const data = new FormData();
      data.append("file", file);
      await watchJob(await api<Job>("/projects/import", "POST", data));
    });
  };
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to editor
      </a>
      <header className={`project-bar ${project && !shelf ? "editing" : ""}`}>
        <button
          className="brand"
          onClick={() => {
            player.current?.stop();
            setShelf(true);
            setPanel(null);
          }}
          aria-label="CleanTake project shelf"
        >
          <AudioLines aria-hidden="true" size={25} />
          <span>CleanTake</span>
        </button>
        {project && !shelf ? (
          <>
            <span className="bar-divider" />
            <button
              className="project-switch"
              onClick={() => {
                player.current?.stop();
                setShelf(true);
                setPanel(null);
              }}
            >
              <span>{project.name}</span>
              <ChevronDown size={15} />
            </button>
            <span className="save-state">
              <Check size={13} />
              Saved locally
            </span>
            <div className="header-spacer" />
            <IconButton
              label="Undo last edit"
              disabled={!project.can_undo || currentBusy}
              onClick={() => void action(() => mutate("/undo", "POST"))}
            >
              <Undo2 size={17} />
            </IconButton>
            <IconButton
              label="Redo last edit"
              disabled={!project.can_redo || currentBusy}
              onClick={() => void action(() => mutate("/redo", "POST"))}
            >
              <Redo2 size={17} />
            </IconButton>
            <button
              className="quiet compact hide-small"
              onClick={() =>
                setPanel(panel === "transcript" ? null : "transcript")
              }
            >
              <FileText size={16} />
              Transcript
            </button>
            <button
              className="primary compact"
              disabled={!duration || currentBusy}
              onClick={() => setPanel("export")}
            >
              <ArrowDownToLine size={16} />
              Export
            </button>
          </>
        ) : (
          <>
            <div className="header-spacer" />
            <span className="local-label">
              <ShieldCheck size={16} />
              On your computer
            </span>
          </>
        )}
        <IconButton
          label="Keyboard shortcuts and help"
          onClick={() => setPanel(panel === "help" ? null : "help")}
        >
          <HelpCircle size={18} />
        </IconButton>
      </header>
      <div className="messages" aria-live="polite">
        {error && (
          <div className="message error" role="alert">
            <span>{error}</span>
            <div className="actions">
              {project && (
                <button onClick={() => void loadProject(project.id)}>
                  Refresh project
                </button>
              )}
              <IconButton label="Dismiss error" onClick={() => setError("")}>
                <X size={16} />
              </IconButton>
            </div>
          </div>
        )}
        {notice && !error && (
          <div className="sr-only" role="status">
            {notice}
          </div>
        )}
      </div>
      {!session ? (
        <main className="session-state" id="main">
          <ShieldCheck size={32} />
          <h1>Open your local session</h1>
          <p>
            Launch CleanTake with <code>cleantake studio</code>, then use the
            browser window it opens. That link gives this page private access to
            your local recordings.
          </p>
          <button
            onClick={() => {
              setSession(hasSession());
              void refreshShelf().catch((error) => report(error));
            }}
          >
            Retry connection
          </button>
        </main>
      ) : shelf ? (
        <main className="shelf" id="main">
          <div className="shelf-intro">
            <div className="intro-copy">
              <h1>
                {projects.length
                  ? "Your recording desk."
                  : "Every take has another chance."}
              </h1>
              <p>
                Recover a damaged passage from another recording of the same
                performance. Hear the source, decide on the repair, keep the
                whole conversation.
              </p>
              <div className="local-note">
                <ShieldCheck size={16} />
                <span>Your recordings and edits stay on this computer.</span>
              </div>
            </div>
            <form className="create-form" onSubmit={createProject}>
              <h2>Start a project</h2>
              <FormField label="Project name">
                <input
                  name="name"
                  aria-label="Project name"
                  placeholder="Interview, episode, or scene"
                  required
                  maxLength={200}
                  autoComplete="off"
                />
              </FormField>
              <button className="primary" type="submit" disabled={busy}>
                {busy ? (
                  <LoaderCircle className="spin" size={17} />
                ) : (
                  <Plus size={17} />
                )}
                Create project
              </button>
              <p>Add a primary recording and up to three backups.</p>
            </form>
          </div>
          <section className="project-library">
            <div className="section-heading">
              <h2>
                {projects.length
                  ? "Recent projects"
                  : "A place for the recordings worth keeping"}
              </h2>
              <button
                disabled={currentBusy}
                onClick={() => archiveInput.current?.click()}
              >
                <FolderOpen size={16} />
                Open project archive
              </button>
            </div>
            {projects.length ? (
              <div className="project-list">
                {projects.map((item) => (
                  <button
                    key={item.id}
                    className="project-row"
                    disabled={opening || currentBusy}
                    onClick={() => void loadProject(item.id)}
                  >
                    <span className="project-symbol">
                      <AudioLines size={22} />
                    </span>
                    <span className="project-row-name">
                      <strong>{item.name}</strong>
                      <span>
                        {item.source_count} recordings ·{" "}
                        {time(item.duration_frames)} · {item.repair_count}{" "}
                        repairs
                      </span>
                    </span>
                    <span className="project-date">
                      {new Date(item.updated_at).toLocaleDateString(undefined, {
                        month: "short",
                        day: "numeric",
                      })}
                    </span>
                    <ArrowRight size={18} />
                  </button>
                ))}
              </div>
            ) : (
              <div className="library-empty">
                <AudioLines size={30} />
                <p>
                  Projects appear here after you create them.
                  <br />
                  Original media is preserved with every saved project.
                </p>
              </div>
            )}
          </section>
        </main>
      ) : project ? (
        <main id="main" className="studio" aria-busy={currentBusy}>
          <div className="workspace-heading">
            <div>
              <h1>Review the performance</h1>
              <p>
                {project.sources.length
                  ? `${project.sources.length} of 4 recordings · ${time(duration, rate)} preserved`
                  : "Bring in the recordings of the same conversation."}
              </p>
            </div>
            <div className="actions">
              <button
                disabled={currentBusy || project.sources.length >= 4}
                onClick={() => mediaInput.current?.click()}
              >
                <Plus size={16} />
                Add recording
              </button>
              <button
                className="primary"
                disabled={project.sources.length < 2 || currentBusy}
                onClick={() =>
                  void action(async () => {
                    player.current?.stop();
                    await watchJob(
                      await api<Job>(
                        `${projectPath(project.id)}/analyze`,
                        "POST",
                        { expected_revision: project.revision },
                      ),
                    );
                    setFilter("review");
                  })
                }
              >
                <AudioLines size={17} />
                {project.status === "analyzed"
                  ? "Analyze again"
                  : "Align & analyze"}
              </button>
            </div>
          </div>
          <details className="import-options">
            <summary>Recording import options</summary>
            <div className="field-pair">
              <FormField label="Input channel">
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={importChannel}
                  placeholder="All channels → mono downmix"
                  onChange={(event) => setImportChannel(event.target.value)}
                />
              </FormField>
              <FormField label="Audio stream">
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={importStream}
                  placeholder="First audio stream"
                  onChange={(event) => setImportStream(event.target.value)}
                />
              </FormField>
            </div>
            <p>
              Channel and stream numbers start at 1. These settings apply to the
              next recordings you import.
            </p>
          </details>
          {project.warnings.length > 0 && (
            <div className="project-warnings">
              {project.warnings.map((warning, i) => (
                <p key={i}>{warning}</p>
              ))}
            </div>
          )}
          {project.error && (
            <div className="message error">{project.error}</div>
          )}
          {job && !terminal(job) && (
            <div className="job-status" role="status">
              <LoaderCircle className="spin" size={17} />
              <span>
                <strong>
                  {job.operation === "import"
                    ? "Importing recording"
                    : job.operation === "analyze"
                      ? "Listening for alignment and damage"
                      : "Preparing files"}
                </strong>
                <span>{job.message || "Processing locally…"}</span>
              </span>
              {job.progress !== null && (
                <progress
                  max={1}
                  value={job.progress}
                  aria-label="Operation progress"
                />
              )}
              <button
                onClick={() =>
                  void api<Job>(`/jobs/${job.id}/cancel`, "POST")
                    .then(setJob)
                    .catch(report)
                }
              >
                Cancel
              </button>
            </div>
          )}
          {!project.sources.length ? (
            <section
              className="import-workspace"
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                if (!currentBusy) void uploadFiles(event.dataTransfer.files);
              }}
            >
              <div className="import-sheet">
                <div className="import-icon">
                  <Upload size={30} />
                </div>
                <h2>Start with your main recording.</h2>
                <p>
                  Drop audio or video here, then add your backups. The first
                  recording sets the timeline; you can change it before
                  reviewing.
                </p>
                <button
                  className="primary"
                  onClick={() => mediaInput.current?.click()}
                  disabled={currentBusy}
                >
                  <Plus size={17} />
                  Choose recordings
                </button>
                <p className="fine-print">
                  WAV, FLAC, MP3, M4A, MP4 and other formats supported by
                  FFmpeg.
                  <br />
                  Two to four simultaneous recordings. Mono working audio at 48
                  kHz.
                </p>
              </div>
              <div className="empty-side">
                <Headphones size={23} />
                <h3>Listen before you decide.</h3>
                <p>
                  CleanTake proposes repairs using your backup audio. You review
                  each one before it reaches the output.
                </p>
                <p>
                  Nothing is shortened. Original recordings are kept intact.
                </p>
              </div>
            </section>
          ) : (
            <div className="editor-grid">
              <div className="score-column">
                <section className="score" aria-label="Performance timeline">
                  <div className="score-toolbar">
                    <h2>Performance</h2>
                    <span className="timeline-units">minutes : seconds</span>
                    <div className="header-spacer" />
                    <IconButton
                      label="Previous timeline window"
                      disabled={windowStart === 0}
                      onClick={() =>
                        setWindowStart(Math.max(0, windowStart - windowSize))
                      }
                    >
                      <ChevronLeft size={16} />
                    </IconButton>
                    <IconButton
                      label="Next timeline window"
                      disabled={end >= duration}
                      onClick={() =>
                        setWindowStart(
                          Math.min(
                            duration - windowSize,
                            windowStart + windowSize,
                          ),
                        )
                      }
                    >
                      <ChevronRight size={16} />
                    </IconButton>
                    <span className="small-divider" />
                    <IconButton
                      label="Zoom out"
                      disabled={windowSize >= duration}
                      onClick={() => zoom(2)}
                    >
                      <ZoomOut size={17} />
                    </IconButton>
                    <IconButton
                      label="Zoom in"
                      disabled={windowSize <= rate}
                      onClick={() => zoom(0.5)}
                    >
                      <ZoomIn size={17} />
                    </IconButton>
                    <button
                      className="text-button"
                      onClick={() => {
                        setWindowStart(0);
                        setWindowSize(duration);
                      }}
                    >
                      Fit
                    </button>
                  </div>
                  <div className="timeline-ruler">
                    <span>Project time</span>
                    <div>
                      {Array.from({ length: 5 }, (_, index) => (
                        <span key={index} style={{ left: `${index * 25}%` }}>
                          <span>
                            {time(
                              windowStart + ((end - windowStart) * index) / 4,
                              rate,
                            )}
                          </span>
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="lane output-lane">
                    <div className="lane-label">
                      <span className="lane-title">
                        <AudioLines size={17} />
                        Repaired output
                      </span>
                      <span>
                        {accepted.length} accepted{" "}
                        {accepted.length === 1 ? "repair" : "repairs"}
                      </span>
                      <span className="lane-caption">
                        Original until accepted
                      </span>
                    </div>
                    {end > windowStart && (
                      <Waveform
                        project={project}
                        start={windowStart}
                        end={end}
                        frame={playback.frame}
                        selected={selected}
                        onSeek={seek}
                        onRepair={selectRepair}
                        onError={showError}
                      />
                    )}
                  </div>
                  {project.sources.map((item, index) => (
                    <div
                      key={item.id}
                      className={`lane source-lane source-${index}`}
                      style={
                        { "--source-color": colors[index] } as CSSProperties
                      }
                    >
                      <div className="lane-label">
                        <div className="lane-title">
                          <span className="source-dot" />
                          <button
                            className="source-name"
                            onClick={() => {
                              setSourceSettings(
                                sourceSettings === item.id
                                  ? undefined
                                  : item.id,
                              );
                              setSelectedId(undefined);
                              setManual(false);
                            }}
                            title={`Edit ${item.name}`}
                          >
                            {item.name}
                          </button>
                          <IconButton
                            label={`Settings for ${item.name}`}
                            onClick={() => {
                              setSourceSettings(
                                sourceSettings === item.id
                                  ? undefined
                                  : item.id,
                              );
                              setSelectedId(undefined);
                              setManual(false);
                            }}
                          >
                            <Settings2 size={14} />
                          </IconButton>
                        </div>
                        <span>
                          {item.id === project.primary_source_id
                            ? "Primary · project clock"
                            : item.alignment.status === "uncertain"
                              ? "Alignment needed"
                              : item.alignment.status === "manual"
                                ? "Manually aligned"
                                : `Aligned · ${item.alignment.residual_ms.toFixed(1)} ms residual`}
                        </span>
                        <span className="lane-caption">
                          {item.speaker ||
                            `${item.audio.source_sample_rate / 1000} kHz · ${item.audio.channel_mode === "downmix" ? "mono downmix" : `channel ${Number(item.audio.selected_channel) + 1}`}`}
                        </span>
                      </div>
                      {end > windowStart && (
                        <Waveform
                          project={project}
                          source={item}
                          start={windowStart}
                          end={end}
                          frame={playback.frame}
                          selected={selected}
                          onSeek={seek}
                          onRepair={selectRepair}
                          onError={showError}
                        />
                      )}
                    </div>
                  ))}
                  <div className="timeline-footer">
                    <span>
                      <span className="legend-mark" />
                      Accepted source span
                    </span>
                    <span>
                      <span className="legend-selection" />
                      Selected passage
                    </span>
                    <span className="header-spacer" />
                    <span>
                      {time(windowStart, rate)} – {time(end, rate)}
                    </span>
                  </div>
                </section>
                {project.sources.length === 1 && (
                  <div className="inline-guidance">
                    <Plus size={18} />
                    <span>
                      <strong>Add a backup to find a repair.</strong> Use
                      another recording of this same performance.
                    </span>
                    <button
                      onClick={() => mediaInput.current?.click()}
                      disabled={currentBusy}
                    >
                      Add backup
                    </button>
                  </div>
                )}
                <section className="review-queue" aria-label="Repair queue">
                  <div className="queue-heading">
                    <div>
                      <h2>
                        Repair queue{" "}
                        <span className="count">{review.length}</span>
                      </h2>
                      <p>
                        {project.status === "analyzed"
                          ? "Hear the evidence. Keep the choices you trust."
                          : "Align and analyze to find possible repairs."}
                      </p>
                    </div>
                    <button
                      onClick={() => {
                        setManual(true);
                        setSelectedId(undefined);
                        setSourceSettings(undefined);
                      }}
                      disabled={currentBusy || project.sources.length < 2}
                    >
                      <Plus size={15} />
                      Manual repair
                    </button>
                  </div>
                  {bulkEligible.length > 1 && (
                    <div className="bulk-review">
                      <span>
                        {bulkEligible.length} proposals have an aligned
                        replacement source.
                      </span>
                      <button
                        disabled={currentBusy}
                        onClick={() =>
                          setConfirmation({
                            title: "Accept all proposed repairs",
                            message: `Accept these ${bulkEligible.length} proposals from aligned recordings? Listen through their replacements before accepting. Unresolved passages will remain in the original audio. You can undo each decision.`,
                            confirm: async () => {
                              await action(async () => {
                                for (const item of bulkEligible)
                                  await mutate(`/repairs/${item.id}`, "PATCH", {
                                    status: "accepted",
                                  });
                              });
                            },
                          })
                        }
                      >
                        Accept all proposals
                      </button>
                    </div>
                  )}
                  <div
                    className="queue-tabs"
                    role="group"
                    aria-label="Filter repairs"
                  >
                    {[
                      ["review", "Needs review"],
                      ["accepted", "Accepted"],
                      ["rejected", "Rejected"],
                      ["all", "All repairs"],
                    ].map(([value, label]) => (
                      <button
                        key={value}
                        aria-pressed={filter === value}
                        onClick={() => setFilter(value)}
                      >
                        {label}
                        {value === "accepted" && accepted.length > 0 && (
                          <span>{accepted.length}</span>
                        )}
                      </button>
                    ))}
                  </div>
                  {filtered.length ? (
                    <div className="repair-list">
                      {filtered.map((repair, index) => (
                        <button
                          className={`repair-row ${selectedId === repair.id ? "selected" : ""}`}
                          key={repair.id}
                          onClick={() => selectRepair(repair)}
                          aria-pressed={selectedId === repair.id}
                        >
                          <span className="repair-index">
                            {String(index + 1).padStart(2, "0")}
                          </span>
                          <span className="repair-time">
                            {time(repair.start_frame, rate, true)}
                            <small>
                              {(
                                (repair.end_frame - repair.start_frame) /
                                rate
                              ).toFixed(2)}{" "}
                              s
                            </small>
                          </span>
                          <span className="repair-description">
                            <strong>
                              {repair.kind === "manual"
                                ? "Manual passage"
                                : repair.kind === "dropout"
                                  ? "Missing signal"
                                  : repair.kind === "clipping"
                                    ? "Clipped passage"
                                    : "Possible noise"}
                            </strong>
                            <small>
                              {repair.source_id
                                ? project.sources.find(
                                    (item) => item.id === repair.source_id,
                                  )?.name
                                : "No intact source found"}
                            </small>
                          </span>
                          <span
                            className={`state ${classStatus(repair.status)}`}
                          >
                            {repair.status === "proposed"
                              ? "Review"
                              : repair.status}
                          </span>
                          <ChevronRight size={16} />
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="queue-empty">
                      <Check size={21} />
                      <div>
                        <strong>
                          {project.status !== "analyzed"
                            ? "The recording is ready to inspect."
                            : filter === "review"
                              ? "No passages waiting for review."
                              : "No repairs in this view."}
                        </strong>
                        <p>
                          {project.status !== "analyzed"
                            ? "Add your backups, then align and analyze the recordings."
                            : "You can still inspect the waveforms and mark a passage manually."}
                        </p>
                      </div>
                    </div>
                  )}
                </section>
              </div>
              <aside className="inspector" aria-label="Passage inspector">
                {sourceSettings ? (
                  <SourceInspector
                    key={`${sourceSettings}-${project.revision}`}
                    source={
                      project.sources.find(
                        (item) => item.id === sourceSettings,
                      )!
                    }
                    project={project}
                    busy={currentBusy}
                    close={() => setSourceSettings(undefined)}
                    save={(payload) =>
                      action(() =>
                        mutate(`/sources/${sourceSettings}`, "PATCH", payload),
                      )
                    }
                    primary={applyPrimary}
                  />
                ) : selected || manual ? (
                  <RepairInspector
                    key={
                      manual ? "manual" : `${selected!.id}-${project.revision}`
                    }
                    repair={selected}
                    project={project}
                    frame={playback.frame}
                    busy={currentBusy}
                    close={() => {
                      setManual(false);
                      setSelectedId(undefined);
                    }}
                    chooseSource={(id) => {
                      player.current?.stop();
                      setSourceId(id);
                    }}
                    save={async (payload) => {
                      await action(async () => {
                        await mutate(
                          selected ? `/repairs/${selected.id}` : "/repairs",
                          selected ? "PATCH" : "POST",
                          payload,
                        );
                        if (!selected) {
                          const item = projectRef.current?.repairs.at(-1);
                          setManual(false);
                          if (item) {
                            setFilter("review");
                            selectRepair(item);
                          }
                        }
                      });
                    }}
                    status={(status) =>
                      action(() =>
                        mutate(`/repairs/${selected!.id}`, "PATCH", { status }),
                      )
                    }
                    listen={() => {
                      setMode("source");
                      const donor = selected?.source_id || sourceId;
                      setSourceId(donor);
                      void player.current?.play(
                        project,
                        "source",
                        donor,
                        Math.max(
                          0,
                          (selected?.start_frame || playback.frame) - rate,
                        ),
                      );
                    }}
                  />
                ) : (
                  <div className="inspector-empty">
                    <div className="inspector-heading">
                      <h2>Passage inspector</h2>
                      <SlidersHorizontal size={18} />
                    </div>
                    <div className="inspector-teaching">
                      <Headphones size={29} />
                      <h3>A repair starts with listening.</h3>
                      <p>
                        Select a passage in the queue to compare its source,
                        adjust the boundaries, and decide what belongs in the
                        output.
                      </p>
                      <div className="inspector-rule" />
                      <dl>
                        <div>
                          <dt>Original</dt>
                          <dd>Your primary recording</dd>
                        </div>
                        <div>
                          <dt>Repair</dt>
                          <dd>Only the edits you accept</dd>
                        </div>
                        <div>
                          <dt>Source</dt>
                          <dd>A backup at the same time</dd>
                        </div>
                      </dl>
                      <p className="fine-print">
                        Uncertain recordings need alignment before a
                        synchronized comparison.
                      </p>
                    </div>
                    <div className="project-settings">
                      <details>
                        <summary>Project settings</summary>
                        <form
                          onSubmit={(event) => {
                            event.preventDefault();
                            const data = new FormData(event.currentTarget);
                            void action(() =>
                              mutate("", "PATCH", {
                                name: String(data.get("name")).trim(),
                              }),
                            );
                          }}
                        >
                          <FormField label="Project name">
                            <input
                              name="name"
                              defaultValue={project.name}
                              required
                              maxLength={200}
                            />
                          </FormField>
                          <button type="submit" disabled={currentBusy}>
                            Save name
                          </button>
                        </form>
                        <button
                          className="danger-text"
                          disabled={currentBusy}
                          onClick={() =>
                            setConfirmation({
                              title: "Delete project",
                              message: `Delete “${project.name}” and its imported copies, edits, and exports from this studio? Files outside the project stay where they are. This cannot be undone.`,
                              confirm: async () => {
                                await action(async () => {
                                  await api(projectPath(project.id), "DELETE", {
                                    expected_revision: project.revision,
                                  });
                                  player.current?.stop();
                                  setProject(null);
                                  projectRef.current = null;
                                  setShelf(true);
                                  await refreshShelf();
                                });
                              },
                            })
                          }
                        >
                          <Trash2 size={15} />
                          Delete project
                        </button>
                      </details>
                    </div>
                  </div>
                )}
              </aside>
            </div>
          )}
        </main>
      ) : (
        <main className="session-state">
          <LoaderCircle className="spin" />
          <p>Opening your project…</p>
        </main>
      )}
      {project && !shelf && (
        <footer className="transport" aria-label="Playback controls">
          <div className="transport-play">
            <IconButton
              label="Return to start"
              disabled={!duration}
              onClick={() => seek(0)}
            >
              <SkipBack size={18} />
            </IconButton>
            <button
              className="play-button"
              aria-label={
                playback.loading
                  ? "Cancel audio loading"
                  : playback.playing
                    ? "Pause playback"
                    : "Play audio"
              }
              disabled={
                !duration ||
                (currentBusy && !playback.playing && !playback.loading) ||
                (mode === "source" &&
                  (!sourceId || source?.alignment.status === "uncertain"))
              }
              onClick={togglePlay}
            >
              {playback.loading ? (
                <LoaderCircle className="spin" size={20} />
              ) : playback.playing ? (
                <Pause size={20} fill="currentColor" />
              ) : (
                <Play size={20} fill="currentColor" />
              )}
            </button>
            <div className="transport-time">
              <output aria-label="Playhead time">
                {time(playback.frame, rate, true)}
              </output>
              <span>of {time(duration, rate)}</span>
            </div>
          </div>
          <div className="comparison">
            <span className="comparison-label">Listen to</span>
            <div className="segmented" role="group" aria-label="Audition mode">
              {[
                ["original", "Original"],
                ["repaired", "Repair"],
                ["source", "Source"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  aria-pressed={mode === value}
                  onClick={() => switchMode(value as AudioMode)}
                  disabled={
                    !duration ||
                    (value === "source" &&
                      (!sourceId || source?.alignment.status === "uncertain"))
                  }
                >
                  {label}
                </button>
              ))}
            </div>
            <select
              aria-label="Audition source"
              value={sourceId || ""}
              onChange={(event) => {
                const frame = player.current!.position();
                const wasPlaying = playback.playing;
                player.current?.stop();
                setSourceId(event.target.value);
                if (wasPlaying)
                  void player.current?.play(
                    project,
                    mode,
                    event.target.value,
                    frame,
                  );
              }}
              disabled={currentBusy || project.sources.length < 2}
            >
              <option value="" disabled>
                Choose a backup
              </option>
              {project.sources
                .filter((item) => item.id !== project.primary_source_id)
                .map((item) => (
                  <option
                    value={item.id}
                    key={item.id}
                    disabled={item.alignment.status === "uncertain"}
                  >
                    {item.name}
                    {item.alignment.status === "uncertain"
                      ? " — alignment needed"
                      : ""}
                  </option>
                ))}
            </select>
          </div>
          <div className="seek-control">
            <label htmlFor="seek-time">Go to (s)</label>
            <input
              id="seek-time"
              key={project.id}
              type="number"
              disabled={currentBusy}
              min={0}
              max={duration / rate}
              step="0.001"
              defaultValue="0"
              onFocus={(event) => {
                event.currentTarget.dataset.focusValue =
                  event.currentTarget.value;
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  const value = event.currentTarget.valueAsNumber;
                  event.currentTarget.dataset.focusValue =
                    event.currentTarget.value;
                  if (Number.isFinite(value)) seek(value * rate);
                }
              }}
              onBlur={(event) => {
                if (
                  event.currentTarget.dataset.focusValue ===
                  event.currentTarget.value
                )
                  return;
                const value = event.currentTarget.valueAsNumber;
                if (Number.isFinite(value)) seek(value * rate);
              }}
            />
            <span className="keyboard-hint">
              <kbd>space</kbd> play / pause
            </span>
          </div>
        </footer>
      )}
      <input
        ref={mediaInput}
        type="file"
        aria-label="Import recordings"
        multiple
        accept="audio/*,video/*,.wav,.flac,.mp3,.m4a,.mp4,.mov,.ogg,.aiff"
        hidden
        onChange={(event) => {
          if (event.target.files) void uploadFiles(event.target.files);
          event.target.value = "";
        }}
      />
      <input
        ref={archiveInput}
        type="file"
        aria-label="Import project archive"
        accept=".zip"
        hidden
        onChange={(event) => {
          void importArchive(event.target.files?.[0]);
          event.target.value = "";
        }}
      />
      {panel && (
        <section
          className="drawer"
          aria-label={
            panel === "export"
              ? "Export project"
              : panel === "transcript"
                ? "Transcript navigation"
                : "Studio help"
          }
        >
          <div className="drawer-heading">
            <h2>
              {panel === "export"
                ? "Take your work with you."
                : panel === "transcript"
                  ? "Follow the conversation."
                  : "Made for careful listening."}
            </h2>
            <IconButton label="Close panel" onClick={() => setPanel(null)}>
              <X size={20} />
            </IconButton>
          </div>
          {panel === "export" && project ? (
            <>
              <p>
                Export the full performance with {accepted.length} accepted{" "}
                {accepted.length === 1 ? "repair" : "repairs"}. Unreviewed
                passages stay in the original audio.
              </p>
              <form
                className="export-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  const data = new FormData(event.currentTarget);
                  void action(async () => {
                    await watchJob(
                      await api<Job>(
                        `${projectPath(project.id)}/exports`,
                        "POST",
                        {
                          format: data.get("format"),
                          finish: false,
                          expected_revision: project.revision,
                        },
                      ),
                    );
                  });
                }}
              >
                <FormField label="Audio format">
                  <select name="format">
                    <option value="wav">WAV · uncompressed</option>
                    <option value="flac">FLAC · lossless</option>
                  </select>
                </FormField>
                <p className="included-files">
                  Includes rendered dialogue, aligned source stems, source map,
                  and an editable Reaper project. No mastering is applied.
                </p>
                <button
                  className="primary"
                  disabled={currentBusy}
                  type="submit"
                >
                  <ArrowDownToLine size={17} />
                  Prepare export
                </button>
              </form>
              <div className="archive-option">
                <h3>Portable project archive</h3>
                <p>
                  Includes your <strong>original recordings</strong>, alignment
                  and repair decisions. Open it in another local CleanTake
                  studio.
                </p>
                <button
                  disabled={currentBusy}
                  onClick={() =>
                    void action(async () => {
                      await watchJob(
                        await api<Job>(
                          `${projectPath(project.id)}/archive`,
                          "POST",
                          { expected_revision: project.revision },
                        ),
                      );
                    })
                  }
                >
                  <FolderOpen size={16} />
                  Prepare archive
                </button>
              </div>
              {job && !terminal(job) && (
                <p role="status">{job.message || "Preparing files locally…"}</p>
              )}
              {exports.map((result) => (
                <div className="export-result" key={result.export_id}>
                  <h3>Ready · revision {result.revision}</h3>
                  {result.warnings?.map((warning, index) => (
                    <p className="warning-text" key={index}>
                      {warning}
                    </p>
                  ))}
                  {result.artifacts.map((artifact) => (
                    <button
                      key={artifact.name}
                      onClick={() => void download(result, artifact.name)}
                      disabled={busy}
                    >
                      <ArrowDownToLine size={16} />
                      <span>
                        {artifact.name}
                        <small>
                          {(artifact.size / 1024 / 1024).toFixed(2)} MB
                        </small>
                      </span>
                    </button>
                  ))}
                </div>
              ))}
            </>
          ) : panel === "transcript" && project ? (
            <TranscriptPanel
              project={project}
              busy={currentBusy}
              submit={(payload) =>
                action(() => mutate("/transcript", "POST", payload))
              }
              seek={(frame) => {
                seek(frame);
                const size = Math.min(duration, rate * 20);
                setWindowSize(size);
                setWindowStart(
                  Math.max(0, Math.min(duration - size, frame - rate * 3)),
                );
              }}
            />
          ) : (
            <div className="help-content">
              <p>
                Import your primary and backup recordings, align and analyze,
                then listen to each proposed passage. Only accepted edits reach
                the repaired output.
              </p>
              <h3>Keyboard controls</h3>
              <dl>
                <div>
                  <dt>
                    <kbd>Space</kbd>
                  </dt>
                  <dd>Play / pause outside form fields</dd>
                </div>
                <div>
                  <dt>
                    <kbd>⌘ / Ctrl</kbd> <kbd>Z</kbd>
                  </dt>
                  <dd>Undo your last edit</dd>
                </div>
                <div>
                  <dt>
                    <kbd>Shift</kbd> <kbd>⌘ / Ctrl</kbd> <kbd>Z</kbd>
                  </dt>
                  <dd>Redo the last undone edit</dd>
                </div>
                <div>
                  <dt>
                    <kbd>Tab</kbd>
                  </dt>
                  <dd>Move through every control</dd>
                </div>
              </dl>
              <h3>One shared clock</h3>
              <p>
                Original, Repair, and Source use the same playhead. A recording
                marked “alignment needed” has its own clock; adjust it in the
                recording settings before comparing.
              </p>
              <h3>Every edit is saved</h3>
              <p>
                Reopen a project from the shelf to continue. Use a portable
                archive to move original recordings and decisions to another
                computer.
              </p>
              <button
                className="quiet"
                onClick={() => {
                  setPanel(null);
                  if (project) setPanel("transcript");
                }}
              >
                Open transcript navigation
              </button>
            </div>
          )}
        </section>
      )}
      {confirmation && (
        <Confirmation
          {...confirmation}
          onClose={() => setConfirmation(undefined)}
        />
      )}
    </div>
  );
}

function SourceInspector({
  source,
  project,
  busy,
  close,
  save,
  primary,
}: {
  source: Source;
  project: Project;
  busy: boolean;
  close: () => void;
  save: (payload: Record<string, unknown>) => Promise<void>;
  primary: (id: string) => void;
}) {
  const [editingAlignment, setEditingAlignment] = useState(false);
  return (
    <div className="inspector-content">
      <div className="inspector-heading">
        <h2>Recording settings</h2>
        <IconButton label="Close recording settings" onClick={close}>
          <X size={17} />
        </IconButton>
      </div>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          void save({
            name: String(data.get("name")).trim(),
            speaker: String(data.get("speaker")).trim() || null,
          });
        }}
      >
        <FormField label="Recording name">
          <input
            name="name"
            defaultValue={source.name}
            required
            maxLength={200}
          />
        </FormField>
        <FormField label="Speaker label">
          <input
            name="speaker"
            defaultValue={source.speaker || ""}
            placeholder="Optional"
            maxLength={200}
          />
        </FormField>
        <button disabled={busy} type="submit">
          Save labels
        </button>
      </form>
      <div className="source-metadata">
        <span className={`state ${classStatus(source.alignment.status)}`}>
          {source.id === project.primary_source_id
            ? "Primary recording"
            : source.alignment.status}
        </span>
        <p>{source.original_filename}</p>
        <dl>
          <div>
            <dt>Original audio</dt>
            <dd>
              {source.audio.source_sample_rate / 1000} kHz ·{" "}
              {source.audio.source_channels} channels
            </dd>
          </div>
          <div>
            <dt>Working audio</dt>
            <dd>48 kHz mono</dd>
          </div>
          <div>
            <dt>Input selection</dt>
            <dd>
              Stream {source.audio.selected_stream + 1} ·{" "}
              {source.audio.channel_mode === "downmix"
                ? "downmix"
                : `channel ${Number(source.audio.selected_channel) + 1}`}
            </dd>
          </div>
        </dl>
      </div>
      {source.id !== project.primary_source_id && (
        <>
          <button
            className="wide"
            onClick={() => primary(source.id)}
            disabled={busy}
          >
            Use as primary
          </button>
          <div className="alignment-section">
            <h3>Synchronization</h3>
            {source.alignment.status === "uncertain" && (
              <p className="warning-text">
                This recording is shown in its own clock. Establish its offset
                before using it as a repair source.
              </p>
            )}
            <dl>
              <div>
                <dt>Offset</dt>
                <dd>{source.alignment.offset_seconds.toFixed(4)} s</dd>
              </div>
              <div>
                <dt>Drift</dt>
                <dd>{source.alignment.drift_ppm.toFixed(1)} ppm</dd>
              </div>
              <div>
                <dt>Evidence</dt>
                <dd>{source.alignment.anchors} anchors</dd>
              </div>
              <div>
                <dt>Residual</dt>
                <dd>{source.alignment.residual_ms.toFixed(2)} ms</dd>
              </div>
            </dl>
            <button
              className="wide"
              onClick={() => setEditingAlignment(!editingAlignment)}
            >
              <Settings2 size={15} />
              {editingAlignment
                ? "Hide manual alignment"
                : "Set manual alignment"}
            </button>
            {editingAlignment && (
              <form
                className="alignment-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  const data = new FormData(event.currentTarget);
                  void save({
                    alignment: {
                      offset_seconds: Number(data.get("offset")),
                      drift_ppm: Number(data.get("drift")),
                      polarity: Number(data.get("polarity")),
                    },
                  });
                }}
              >
                <p>
                  Source time = project time × drift ratio + offset. A positive
                  offset means the sound occurs later in this source.
                </p>
                <FormField label="Offset (seconds)">
                  <input
                    type="number"
                    name="offset"
                    step="0.0001"
                    defaultValue={source.alignment.offset_seconds}
                    required
                  />
                </FormField>
                <FormField label="Drift (ppm)">
                  <input
                    type="number"
                    name="drift"
                    step="0.1"
                    defaultValue={source.alignment.drift_ppm}
                    required
                  />
                </FormField>
                <FormField label="Polarity">
                  <select
                    name="polarity"
                    defaultValue={source.alignment.polarity}
                  >
                    <option value="1">Normal</option>
                    <option value="-1">Inverted</option>
                  </select>
                </FormField>
                <p className="warning-text">
                  Applying a new clock marks affected repairs unresolved. Verify
                  the alignment by listening.
                </p>
                <button className="primary wide" type="submit" disabled={busy}>
                  Apply manual alignment
                </button>
              </form>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function recordingTime(seconds: number) {
  const milliseconds = Math.round(Math.abs(seconds) * 1000);
  const hours = Math.floor(milliseconds / 3_600_000);
  const minutes = Math.floor(milliseconds / 60_000) % 60;
  const remainder = milliseconds % 60_000;
  return `${seconds < 0 && milliseconds ? "−" : ""}${hours ? `${String(hours).padStart(2, "0")}:` : ""}${String(minutes).padStart(2, "0")}:${String(Math.floor(remainder / 1000)).padStart(2, "0")}.${String(remainder % 1000).padStart(3, "0")}`;
}

function RepairInspector({
  repair,
  project,
  frame,
  busy,
  close,
  chooseSource,
  save,
  status,
  listen,
}: {
  repair?: Repair;
  project: Project;
  frame: number;
  busy: boolean;
  close: () => void;
  chooseSource: (id: string) => void;
  save: (payload: Record<string, unknown>) => Promise<void>;
  status: (status: string) => Promise<void>;
  listen: () => void;
}) {
  const donorSources = project.sources.filter(
    (source) => source.id !== project.primary_source_id,
  );
  const [donor, setDonor] = useState(
    repair?.source_id ||
      donorSources.find((source) => source.alignment.status !== "uncertain")
        ?.id ||
      "",
  );
  const [formChanged, setFormChanged] = useState(false);
  const rate = project.sample_rate;
  const usable = donorSources.some(
    (source) => source.id === donor && source.alignment.status !== "uncertain",
  );
  const savedSource = donorSources.find(
    (source) => source.id === repair?.source_id,
  );
  const savedAligned =
    savedSource && savedSource.alignment.status !== "uncertain";
  const scale = savedSource
    ? 1 + savedSource.alignment.drift_ppm / 1_000_000
    : 1;
  const offset = (savedSource?.alignment.offset_seconds ?? 0) * rate;
  const sourceStart = repair ? repair.start_frame * scale + offset : 0;
  const sourceEnd = repair ? repair.end_frame * scale + offset : 0;
  const covered = !!(
    repair &&
    savedSource &&
    sourceStart >= 0 &&
    (repair.end_frame - 1) * scale + offset <= savedSource.audio.frames - 1
  );
  return (
    <div className="inspector-content">
      <div className="inspector-heading">
        <h2>{repair ? "Selected passage" : "Mark a manual repair"}</h2>
        <IconButton label="Close passage inspector" onClick={close}>
          <X size={17} />
        </IconButton>
      </div>
      {repair && (
        <>
          <div className="passage-summary">
            <span className={`state ${classStatus(repair.status)}`}>
              {repair.status === "proposed" ? "Needs review" : repair.status}
            </span>
            <h3>
              {time(repair.start_frame, rate, true)} <span>—</span>
              <br />
              {time(repair.end_frame, rate, true)}
            </h3>
            <p>{repair.reason}</p>
          </div>
          {repair.status !== "accepted" && (
            <p className="inspector-note">
              This passage is unchanged in Repair mode until you accept it. Use
              Source to hear the proposed donor.
            </p>
          )}
        </>
      )}
      <form
        onChange={() => setFormChanged(true)}
        onSubmit={(event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          void save({
            start_frame: Math.round(Number(data.get("start")) * rate),
            end_frame: Math.round(Number(data.get("end")) * rate),
            source_id: data.get("source"),
            gain_db: Number(data.get("gain")),
            fade_ms: Number(data.get("fade")),
            ...(!repair ? { kind: "manual" } : {}),
          });
        }}
      >
        <FormField label="Replacement recording">
          <select
            name="source"
            value={donor}
            required
            onChange={(event) => {
              setDonor(event.target.value);
              chooseSource(event.target.value);
            }}
          >
            <option value="" disabled>
              Choose an aligned source
            </option>
            {donorSources.map((source) => (
              <option
                key={source.id}
                value={source.id}
                disabled={source.alignment.status === "uncertain"}
              >
                {source.name}
                {source.alignment.status === "uncertain"
                  ? " — alignment needed"
                  : ""}
              </option>
            ))}
          </select>
        </FormField>
        {repair && (
          <button
            className="wide listen-source"
            type="button"
            disabled={busy || !usable || formChanged}
            onClick={listen}
          >
            <Headphones size={16} />
            Listen to source in context
          </button>
        )}
        {repair?.alternatives?.length ? (
          <p className="fine-print">
            {repair.alternatives.length} alternative{" "}
            {repair.alternatives.length === 1 ? "source" : "sources"} evaluated.
            Choose a recording above to inspect another option.
          </p>
        ) : null}
        <div className="field-pair">
          <FormField label="Start (seconds)">
            <input
              name="start"
              type="number"
              min={0}
              max={project.duration_frames / rate}
              step="0.000001"
              defaultValue={(
                (repair?.start_frame ?? Math.floor(frame)) / rate
              ).toFixed(6)}
              required
            />
          </FormField>
          <FormField label="End (seconds)">
            <input
              name="end"
              type="number"
              min={0}
              max={project.duration_frames / rate}
              step="0.000001"
              defaultValue={(
                (repair?.end_frame ??
                  Math.min(project.duration_frames, Math.floor(frame) + rate)) /
                rate
              ).toFixed(6)}
              required
            />
          </FormField>
        </div>
        <div className="field-pair">
          <FormField label="Gain (dB)">
            <input
              name="gain"
              type="number"
              min={-24}
              max={24}
              step="0.1"
              defaultValue={repair?.gain_db || 0}
              required
            />
          </FormField>
          <FormField label="Crossfade (ms)">
            <input
              name="fade"
              type="number"
              min={0}
              max={1000}
              step="0.1"
              defaultValue={repair?.fade_ms ?? 12}
              required
            />
          </FormField>
        </div>
        <button
          className={repair ? "wide" : "primary wide"}
          disabled={busy || !usable}
          type="submit"
        >
          {repair ? "Save passage changes" : "Create proposed repair"}
        </button>
      </form>
      {repair && (
        <div className="decision-actions">
          <section
            className="repair-provenance"
            aria-label="Repair source details"
          >
            <h3>Replacement details</h3>
            {savedSource ? (
              <>
                <strong className="repair-source-name">
                  {savedSource.name}
                </strong>
                {savedSource.original_filename !== savedSource.name && (
                  <span className="repair-source-file">
                    {savedSource.original_filename}
                  </span>
                )}
                {(savedSource.audio.source_channels > 1 ||
                  savedSource.audio.selected_stream > 0) && (
                  <span className="repair-source-file">
                    Stream {savedSource.audio.selected_stream + 1} ·{" "}
                    {savedSource.audio.channel_mode === "downmix"
                      ? "mono downmix"
                      : `channel ${Number(savedSource.audio.selected_channel) + 1}`}
                  </span>
                )}
              </>
            ) : (
              <p>No replacement recording saved.</p>
            )}
            <dl>
              <div>
                <dt>In project</dt>
                <dd aria-label="Project time range">
                  {recordingTime(repair.start_frame / rate)} —{" "}
                  {recordingTime(repair.end_frame / rate)}
                </dd>
              </div>
              {savedAligned && (
                <div>
                  <dt>In recording</dt>
                  <dd aria-label="Recording time range">
                    {recordingTime(sourceStart / rate)} —{" "}
                    {recordingTime(sourceEnd / rate)}
                  </dd>
                </div>
              )}
            </dl>
            <p className="fine-print">
              Times rounded to milliseconds.
              {(repair.fade_ms * rate) / 1000 > 0.5 &&
              repair.end_frame - repair.start_frame >= 2 &&
              savedSource
                ? " Edges blend with the original."
                : ""}
            </p>
            {!savedSource ? (
              <p className="warning-text">
                Choose a recording and save the passage before accepting.
              </p>
            ) : !savedAligned ? (
              <p className="warning-text">
                Alignment needed. Review this recording’s clock before
                accepting.
              </p>
            ) : !covered ? (
              <p className="warning-text">
                This recording does not cover the whole passage. Adjust the
                range or choose another recording.
              </p>
            ) : null}
            {formChanged && (
              <p className="fine-print" role="status">
                Saved values shown. Save your changes before auditioning or
                deciding.
              </p>
            )}
          </section>
          <button
            className="primary wide"
            disabled={
              busy ||
              !savedAligned ||
              !covered ||
              formChanged ||
              repair.status === "accepted"
            }
            onClick={() => void status("accepted")}
          >
            <Check size={17} />
            Accept repair
          </button>
          <button
            className="wide"
            disabled={busy || formChanged || repair.status === "rejected"}
            onClick={() => void status("rejected")}
          >
            <X size={16} />
            Keep original
          </button>
          {["accepted", "rejected"].includes(repair.status) && (
            <button
              className="text-button wide"
              disabled={busy || formChanged}
              onClick={() => void status("proposed")}
            >
              <RotateCcw size={14} />
              Return to review
            </button>
          )}
        </div>
      )}
      {!usable && (
        <p className="warning-text">
          No aligned backup is available. Open a recording’s settings to review
          its clock.
        </p>
      )}
      <div className="inspector-footnote">
        All boundaries snap to original project frames. The performance duration
        stays the same.
      </div>
    </div>
  );
}

function TranscriptPanel({
  project,
  busy,
  submit,
  seek,
}: {
  project: Project;
  busy: boolean;
  submit: (payload: Record<string, unknown>) => Promise<void>;
  seek: (frame: number) => void;
}) {
  const [text, setText] = useState("");
  const [filename, setFilename] = useState("transcript.vtt");
  const [search, setSearch] = useState("");
  const [fileError, setFileError] = useState("");
  return (
    <>
      <p>
        Transcript times help you navigate. Text never authorizes an audio cut.
        Estimated times stay marked.
      </p>
      <details className="transcript-import" open={!project.transcripts.length}>
        <summary>Import a transcript</summary>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            void submit({
              text,
              filename,
              source_id: data.get("source"),
              ...(data.get("unit") ? { time_unit: data.get("unit") } : {}),
            });
          }}
        >
          <FormField label="Transcript file">
            <input
              type="file"
              accept=".vtt,.srt,.json,.txt"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) {
                  setFilename(file.name);
                  void file
                    .text()
                    .then(setText)
                    .catch(() =>
                      setFileError(
                        "The transcript could not be read. Choose it again.",
                      ),
                    );
                }
              }}
            />
          </FormField>
          {fileError && <p role="alert">{fileError}</p>}
          <FormField label="Transcript text">
            <textarea
              value={text}
              onChange={(event) => setText(event.target.value)}
              rows={6}
              required
              placeholder="Paste VTT, SRT, or timed JSON…"
            />
          </FormField>
          <FormField label="Transcript filename / format">
            <input
              value={filename}
              onChange={(event) => setFilename(event.target.value)}
              required
            />
          </FormField>
          <FormField label="Recording clock">
            <select
              name="source"
              defaultValue={project.primary_source_id || ""}
              required
            >
              {project.sources.map((source) => (
                <option key={source.id} value={source.id}>
                  {source.name}
                </option>
              ))}
            </select>
          </FormField>
          <FormField label="Generic JSON time unit">
            <select name="unit">
              <option value="">Explicit timing / subtitle format</option>
              <option value="seconds">Seconds</option>
              <option value="milliseconds">Milliseconds</option>
            </select>
          </FormField>
          <button
            className="primary"
            type="submit"
            disabled={busy || !project.sources.length}
          >
            Import transcript
          </button>
        </form>
      </details>
      {project.transcripts.length > 0 && (
        <>
          <FormField label="Find in transcript">
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search words or a speaker"
            />
          </FormField>
          <div className="transcript-turns">
            {project.transcripts.flatMap((transcript) => {
              const source = project.sources.find(
                (item) => item.id === transcript.source_id,
              );
              const aligned = source && source.alignment.status !== "uncertain";
              return transcript.turns
                .filter((turn) =>
                  `${turn.text} ${turn.speaker || ""}`
                    .toLowerCase()
                    .includes(search.toLowerCase()),
                )
                .map((turn, index) => {
                  const projectSeconds =
                    turn.start_ms === null || !source
                      ? null
                      : (turn.start_ms / 1000 -
                          source.alignment.offset_seconds) /
                        (1 + source.alignment.drift_ppm / 1e6);
                  return (
                    <button
                      className="transcript-turn"
                      key={`${transcript.id}-${index}`}
                      disabled={
                        !aligned ||
                        projectSeconds === null ||
                        projectSeconds < 0 ||
                        projectSeconds * project.sample_rate >=
                          project.duration_frames
                      }
                      onClick={() => {
                        if (projectSeconds !== null)
                          seek(
                            Math.round(projectSeconds * project.sample_rate),
                          );
                      }}
                    >
                      <span>
                        <strong>
                          {turn.speaker ||
                            source?.speaker ||
                            source?.name ||
                            "Speaker"}
                        </strong>
                        <small>
                          {!aligned
                            ? "Source clock · alignment needed"
                            : projectSeconds === null
                              ? "Time unavailable"
                              : `${time(projectSeconds * project.sample_rate, project.sample_rate)}${turn.time_estimated ? " · estimated" : ""}`}
                        </small>
                      </span>
                      <p>{turn.text}</p>
                    </button>
                  );
                });
            })}
          </div>
        </>
      )}
    </>
  );
}
