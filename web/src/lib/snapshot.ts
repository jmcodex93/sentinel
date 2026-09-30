/** One channel per displayed snapshot; payload and stamp must travel together. */
export type ReadResult<T> = { kind: "ok"; data: T } | { kind: "empty"; reason: string } | { kind: "error"; message: string };
export interface SnapshotRead<T> { result: ReadResult<T>; stamp: string | null }

export class SnapshotChannel {
  private sequence = 0;
  private stamp: string | null = null;
  private pending = false;
  private requestedStamp: string | null = null;

  needsRefresh(stamp: string | null): boolean {
    return this.pending ? stamp !== this.requestedStamp : stamp !== this.stamp;
  }

  // Selection-only changes do not invalidate a Hub inventory's contents.
  currentStamp(): string | null { return this.stamp; }

  acknowledge(stamp: string, previous: string): void {
    if (!this.pending && this.stamp === previous) this.stamp = stamp;
  }

  invalidate(): void {
    this.sequence += 1;
    this.pending = false;
    this.stamp = null;
  }

  async load<T>(fetcher: () => Promise<SnapshotRead<T>>, commit: (snapshot: SnapshotRead<T>) => void, requestedStamp: string | null = null): Promise<void> {
    const sequence = ++this.sequence;
    this.pending = true;
    this.requestedStamp = requestedStamp;
    let snapshot: SnapshotRead<T>;
    try {
      snapshot = await fetcher();
    } catch {
      snapshot = { stamp: null, result: { kind: "error", message: "Could not refresh the scene." } };
    }
    if (sequence !== this.sequence) return;
    this.pending = false;
    this.stamp = snapshot.result.kind === "ok" ? snapshot.stamp : null;
    commit(snapshot);
  }
}
