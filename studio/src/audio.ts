import { request, projectPath, type AudioMode, type Project } from "./api";

export interface PlaybackState {
  playing: boolean;
  loading: boolean;
  frame: number;
}
export class TimelinePlayer {
  private context?: AudioContext;
  private controller?: AbortController;
  private nodes = new Set<AudioBufferSourceNode>();
  private generation = 0;
  private timer?: number;
  private nextFrame = 0;
  private startFrame = 0;
  private startTime = 0;
  private endFrame = 0;
  private rate = 48000;
  private running = false;
  private loading = false;
  private fetching = false;
  private scheduledEnd = 0;
  private frame = 0;
  private current?: { project: Project; mode: AudioMode; source?: string };
  constructor(
    private update: (state: PlaybackState) => void,
    private error: (message: string) => void,
  ) {}
  position() {
    return this.running && this.context
      ? Math.min(
          this.endFrame,
          this.startFrame +
            Math.max(
              0,
              Math.min(this.context.currentTime, this.scheduledEnd) -
                this.startTime,
            ) *
              this.rate,
        )
      : this.frame;
  }
  stop() {
    this.frame = Math.round(this.position());
    this.running = false;
    this.loading = false;
    this.generation++;
    this.controller?.abort();
    this.fetching = false;
    window.clearInterval(this.timer);
    for (const node of this.nodes) {
      node.onended = null;
      try {
        node.stop();
      } catch {
        /* Already ended. */
      }
      node.disconnect();
    }
    this.nodes.clear();
    this.update({ playing: false, loading: false, frame: this.frame });
    return this.frame;
  }
  seek(frame: number) {
    this.stop();
    this.frame = Math.max(0, Math.round(frame));
    this.update({ playing: false, loading: false, frame: this.frame });
  }
  async play(
    project: Project,
    mode: AudioMode,
    source: string | undefined,
    frame: number,
  ) {
    this.stop();
    const generation = this.generation;
    if (
      mode === "source" &&
      project.sources.find((item) => item.id === source)?.alignment.status ===
        "uncertain"
    ) {
      this.error(
        "This recording has its own clock. Set its alignment before comparing at project time.",
      );
      return;
    }
    this.context ??= new AudioContext();
    await this.context.resume();
    if (generation !== this.generation) return;
    this.current = { project, mode, source };
    this.controller = new AbortController();
    this.rate = project.sample_rate;
    this.endFrame = project.duration_frames;
    this.frame =
      this.startFrame =
      this.nextFrame =
        Math.max(0, Math.min(Math.round(frame), this.endFrame - 1));
    this.loading = true;
    this.update({ playing: false, loading: true, frame: this.frame });
    try {
      const first = await this.window(generation);
      if (!first || generation !== this.generation) return;
      this.startTime = this.context.currentTime + 0.045;
      this.scheduledEnd = this.startTime;
      this.schedule(first);
      this.running = true;
      this.loading = false;
      this.update({ playing: true, loading: false, frame: this.frame });
      this.timer = window.setInterval(() => this.tick(generation), 80);
      this.tick(generation);
    } catch (error) {
      this.fail(error, generation);
    }
  }
  private async window(generation: number) {
    if (!this.current || !this.context || this.nextFrame >= this.endFrame)
      return;
    const { project, mode, source } = this.current;
    const start = this.nextFrame;
    const end = Math.min(this.endFrame, start + 20 * this.rate);
    const query = new URLSearchParams({
      mode,
      start_frame: String(start),
      end_frame: String(end),
    });
    if (source && mode === "source") query.set("source_id", source);
    const response = await request(
      `${projectPath(project.id)}/audio?${query}`,
      { signal: this.controller?.signal },
    );
    const revision = response.headers.get("X-CleanTake-Revision");
    if (
      Number(response.headers.get("X-CleanTake-Start-Frame")) !== start ||
      Number(response.headers.get("X-CleanTake-End-Frame")) !== end
    )
      throw new Error(
        "The audio window did not match the requested time. Playback stopped; refresh the project.",
      );
    if (revision !== null && Number(revision) !== project.revision)
      throw new Error(
        "The project changed while loading audio. Playback stopped; refresh before listening again.",
      );
    const data = await response.arrayBuffer();
    if (generation !== this.generation) return;
    const buffer = await this.context.decodeAudioData(data);
    if (generation !== this.generation) return;
    if (Math.abs(buffer.duration - (end - start) / this.rate) > 2 / this.rate)
      throw new Error(
        "The audio window had an unexpected duration. Playback stopped; try again.",
      );
    this.nextFrame = end;
    return buffer;
  }
  private schedule(buffer: AudioBuffer) {
    const node = this.context!.createBufferSource();
    node.buffer = buffer;
    node.connect(this.context!.destination);
    node.onended = () => {
      node.disconnect();
      this.nodes.delete(node);
    };
    this.nodes.add(node);
    node.start(this.scheduledEnd);
    this.scheduledEnd += buffer.duration;
  }
  private tick(generation: number) {
    if (generation !== this.generation || !this.context) return;
    this.frame = Math.round(this.position());
    if (this.frame >= this.endFrame) {
      this.stop();
      return;
    }
    if (this.context.currentTime >= this.scheduledEnd) {
      this.fail(
        new Error(
          "The audio buffer ran out while the next window was loading. Playback stopped at the last heard sample; press Play to resume.",
        ),
        generation,
      );
      return;
    }
    this.update({
      playing: this.running,
      loading: this.loading,
      frame: this.frame,
    });
    if (
      this.nextFrame < this.endFrame &&
      this.scheduledEnd - this.context.currentTime < 10 &&
      !this.fetching &&
      this.nodes.size < 2
    ) {
      this.fetching = true;
      void this.window(generation)
        .then((buffer) => {
          if (!buffer || generation !== this.generation) return;
          if (this.scheduledEnd < this.context!.currentTime)
            throw new Error(
              "Audio loading fell behind playback. Playback stopped at this position; press Play to resume.",
            );
          this.schedule(buffer);
        })
        .catch((error) => this.fail(error, generation))
        .finally(() => {
          if (generation === this.generation) this.fetching = false;
        });
    }
  }
  private fail(error: unknown, generation: number) {
    if (
      generation !== this.generation ||
      (error instanceof DOMException && error.name === "AbortError")
    )
      return;
    this.stop();
    this.error(
      error instanceof Error
        ? error.message
        : "Audio could not be played. Try again.",
    );
  }
  dispose() {
    this.stop();
    void this.context?.close();
  }
}
