import { expect, it } from "vitest";
import { settingsSubmitPayload } from "./settings";

it("submits the editable artist name without changing existing settings fields", () => {
  const payload = settingsSubmitPayload({
    artistName: "  Motioneer  ",
    fps: 25,
    compositor: 1,
    multipart: false,
    slate: true,
    renderNotify: false,
    mvMax: 64,
    snapshotDir: "/Volumes/render/snapshots",
    historyMax: 10,
  });

  expect(payload).toEqual({
    artist_name: "Motioneer",
    fps: 25,
    compositor: 1,
    multipart_default: false,
    slate: true,
    render_notify: false,
    mv_max_motion: 64,
    snapshot_dir: "/Volumes/render/snapshots",
    history_max: 10,
  });
});
