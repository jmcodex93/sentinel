import type { SettingsSubmitPayload } from "../types";

export interface SettingsFormValues {
  artistName: string;
  fps: number;
  compositor: number;
  multipart: boolean;
  slate: boolean;
  renderNotify: boolean;
  mvMax: number;
  snapshotDir: string;
  historyMax: number;
}

export function settingsSubmitPayload(values: SettingsFormValues): SettingsSubmitPayload {
  return {
    artist_name: values.artistName.trim(),
    fps: values.fps,
    compositor: values.compositor,
    multipart_default: values.multipart,
    slate: values.slate,
    render_notify: values.renderNotify,
    mv_max_motion: values.mvMax,
    snapshot_dir: values.snapshotDir,
    history_max: values.historyMax,
  };
}
