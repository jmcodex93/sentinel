# Install, update, and roll back Sentinel

This candidate contains the complete `plugin/` payload and a standard-library
installer. Close every target Cinema 4D process before installing or rolling
back. A full restart is required; **Reload Python Plugins is not sufficient**.

## Requirements

- **Cinema 4D 2024 or newer** with Redshift. Tested: 2026.4 on Windows,
  2026.3 on macOS, and 2025 on Windows. Known issue: on one Windows host with
  C4D 2026.3.4 and other plugins loaded, expanding the Sentinel Frame tag in
  the Attribute Manager closed C4D; Doctor shows a warning on that version. If
  it happens to you, 2026.4 does not have the problem.
- A Python 3 to run `install.py` (any recent version).
- For snapshot EXR → PNG conversion only: an external Python with OpenEXR,
  numpy and Pillow (see *Snapshot EXR conversion* below). Everything else
  runs inside Cinema 4D's own Python.

## Install or update

From the extracted candidate directory:

```bash
python3 install.py --list
python3 install.py                         # interactive target selection
python3 install.py --all                   # every detected C4D preference folder
python3 install.py --target "/path/to/Cinema 4D preferences/plugins"
```

On Windows, use `py -3` instead of `python3` if that is how Python is installed.
The explicit target is the C4D **plugins directory**, not the `Sentinel`
directory inside it.

The installer validates the source, copies it to a staging directory outside
C4D's scanned plugin folder, verifies every staged file by SHA256, and only then
activates it. On update, the previous `Sentinel` directory is retained beside
the plugins directory under `Sentinel Backups/backup-.../`. The installer never
deletes recorded backups.

## Roll back

Use the same explicit plugins directory used for installation:

```bash
python3 install.py --target "/path/to/Cinema 4D preferences/plugins" --rollback latest
python3 install.py --target "/path/to/Cinema 4D preferences/plugins" --rollback backup-YYYYMMDD...
```

The rollback command verifies the selected backup's recorded file set and
SHA256 hashes before changing the active plugin. It also retains the displaced
current version as a new backup, so the rollback itself is reversible. Backups
from older Sentinel versions remain restorable even when they predate files
required by the current release.

If an activation or verification step fails, read the printed `Recovery
payload` path. The installer either restores the prior live installation or
reports the exact preserved directory needed for manual recovery.

## Manual install

Manual copying bypasses staging and automatic backups. If Python is unavailable,
copy the contents of `plugin/` into `<plugins>/Sentinel/` while Cinema 4D is
closed, keeping `sentinel_panel.pyp`, `sentinel/`, `res/`, `abc_retime/`, `c4d/`,
`icons/`, `web/`, `LICENSE`, and `THIRD_PARTY_NOTICES.txt` together.

After starting Cinema 4D, open Sentinel's **Doctor** from the panel footer to
check the running payload and environment.

## Snapshot EXR conversion (external Python)

Snapshot Watch converts Redshift EXR snapshots to PNG with an ACES transform
that Cinema 4D's own Python can't do. It runs in a separate Python that must
have **OpenEXR, numpy and Pillow**. Without it the rest of Sentinel works
normally; Doctor reports "No system Python 3 with OpenEXR + numpy + Pillow".

Sentinel looks for that Python when Cinema 4D starts, in these places only:

| System | Where Sentinel looks |
|---|---|
| Windows | `python` / `python3` on the PATH, `C:\Program Files\Python*\python.exe`, `%LOCALAPPDATA%\Programs\Python\Python*\python.exe` |
| macOS | `/usr/bin/python3`, `/usr/local/bin/python3`, `/opt/homebrew/bin/python3` (not the PATH) |

It tries each one and uses the first that imports all three libraries.

**Windows.** OpenEXR has no package for Python 3.14 yet (`pip` answers "No
matching distribution"), so install **Python 3.12** from python.org with the
default per-user option, then:

```powershell
py -3.12 -m pip install OpenEXR numpy Pillow
py -3.12 -c "import OpenEXR, numpy, PIL; print('OK')"
```

**macOS.** Install the libraries into one of the three interpreters above, for
example:

```bash
/usr/local/bin/python3 -m pip install OpenEXR numpy Pillow
```

Then **restart Cinema 4D** (the search runs at startup) and check Doctor: the
"External Python (EXR converter)" row should say *Found* with the path. In
RenderView, enable *Save snapshots as EXR* (Preferences → Snapshots); Redshift
does not persist that option between sessions.

## Candidate identity

`SENTINEL_CANDIDATE.json` records the exact source commit, build identity, and
SHA256/size for every archived file. The repository-only builder creates an
archive from committed Git objects rather than uncommitted working-tree files:

```bash
python3 build_candidate.py --source-ref HEAD
```

The builder extracts and verifies the completed archive before publishing it to
the local `dist/` directory. `dist/` is excluded from Git. This is a local beta
artifact; building it does not publish or license a commercial release.
