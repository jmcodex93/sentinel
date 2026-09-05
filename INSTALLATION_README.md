# Install, update, and roll back Sentinel

This candidate contains the complete `plugin/` payload and a standard-library
installer. Close every target Cinema 4D process before installing or rolling
back. A full restart is required; **Reload Python Plugins is not sufficient**.

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
