# Desktop installation

CleanTake's desktop app includes its editing window, Python, audio tools,
processing libraries and sample recordings. You do not need a separate browser,
FFmpeg installation, model, account, developer tools or GPU computing driver.
Processing stays on your computer and the included sample works offline.

## Choose your download

Download from the [CleanTake 0.2.0 release](https://github.com/pavangupta352/cleantake/releases/tag/v0.2.0).

| Computer | File |
|---|---|
| Mac with Apple silicon | `CleanTake-0.2.0-mac-arm64.dmg` |
| Mac with Intel processor | `CleanTake-0.2.0-mac-x64.dmg` |
| Windows with Intel or AMD processor | `CleanTake-0.2.0-win-x64.exe` |
| Windows with ARM processor | `CleanTake-0.2.0-win-arm64.exe` |
| Ubuntu desktop with Intel or AMD processor | `CleanTake-0.2.0-linux-amd64.deb` |
| Ubuntu desktop with ARM processor | `CleanTake-0.2.0-linux-arm64.deb` |

On a Mac, **Apple menu → About This Mac** shows an Apple chip or an Intel
processor. On Windows, check **Settings → System → About → System type**.
On Ubuntu, `dpkg --print-architecture` reports `amd64` or `arm64`.

Mac downloads require macOS 14 or newer. The intended Windows minimum is Windows
10 for Intel/AMD and Windows 11 for ARM. Linux builds use Ubuntu 22.04 for
Intel/AMD and Ubuntu 24.04 for ARM; other Debian-based distributions have not
been qualified. The release notes identify the systems actually checked. There
are no 32-bit or mobile builds. See the [native validation record](VALIDATION.md#native-desktop--020)
for the exact tested systems and installer checks.

## Mac

1. Open the matching DMG and drag **CleanTake** into **Applications**.
2. Open **CleanTake** from Applications.
3. Eject the disk image once installation is complete.

These builds are ad-hoc signed and **not notarized**. macOS may block their first
launch. If you downloaded the app from this project's release and choose to
open it, Apple documents a per-app approval: after attempting to open CleanTake,
go to **System Settings → Privacy & Security**, find CleanTake's blocked-app
entry and choose **Open Anyway**, then **Open**. Use this only when the entry
identifies the app you intended to install. This option may be unavailable on a
managed Mac. See [Apple's instructions](https://support.apple.com/en-us/102445).

This is the official conditional approval route; acceptance of the exact
downloaded CleanTake build has not yet been verified. If the option is absent,
or macOS reports damage or malware, stop and report the exact message through
the [issue tracker](https://github.com/pavangupta352/cleantake/issues).

## Windows

1. Open the matching installer. It installs for your Windows account and opens
   CleanTake when finished.
2. Use the **CleanTake** Start menu or desktop shortcut for later launches.

These installers are **unsigned**, so Windows does not show a verified
publisher. An unrecognized-app SmartScreen prompt may offer **More info → Run
anyway**. If you downloaded this project's installer and choose to proceed,
check its file name before confirming. See [Microsoft's SmartScreen guidance](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/publish-first-app#step-6-handle-smartscreen-for-new-apps).

Smart App Control or an organization's policy can block unsigned apps entirely.
Smart App Control has no approval for a single blocked app, so this unsigned
release may not run on those computers. For an organization-managed computer,
contact its administrator. Keep your existing protections enabled. See
[Microsoft's explanation](https://support.microsoft.com/en-us/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions).

## Ubuntu desktop

Open a terminal in the folder containing your download. For Intel/AMD:

```sh
sudo apt install ./CleanTake-0.2.0-linux-amd64.deb
```

For ARM:

```sh
sudo apt install ./CleanTake-0.2.0-linux-arm64.deb
```

Review the package manager's prompt and confirm installation. It installs any
required desktop libraries, which may need an internet connection. CleanTake's
audio tools and processing runtime are already included. Open **CleanTake**
from the application launcher when installation finishes.

Use the Debian package for the supported Ubuntu route. A portable archive, if
offered by a release, has separate compatibility limits and does not install
operating-system dependencies.

## Hear your first repair

An empty workspace starts with **Sample · recover a missing half-second**.
Open it, select the passage near 17 seconds, and compare **Original** and
**Source**. The backup contains speech missing from the main recording.
Choose **Accept repair** to include that passage in **Repair** playback, then
export the result.

The sample uses licensed AMI recordings with a clearly labeled injected gap.
The repair starts pending so you can hear and choose it yourself. Existing
projects are preserved; deleting the sample does not make it return at every
launch.

To work on your own recording, create a project and add the main recording plus
its simultaneous backups. The [editing guide](GUIDE.md) covers alignment,
listening, manual repairs and exports.

## Update, remove or reinstall

Close CleanTake before updating or removing it. **Help → Downloads and updates**
opens the release page. Install updates explicitly; the app does not silently
replace itself.

| System | Update or reinstall | Remove the application |
|---|---|---|
| Mac | Drag the new CleanTake into Applications and confirm replacement | Move CleanTake from Applications to the Trash |
| Windows | Run the matching installer again | Settings → Apps → Installed apps → CleanTake → Uninstall; on Windows 10, use Apps & features |
| Ubuntu | Install the downloaded package with the same `apt install ./…` command | Run `sudo apt remove cleantake` |

Removing the application preserves saved projects. Reinstalling for the same
account uses that workspace again. Export a portable project archive before
moving to another computer or account.

| System | Saved projects and processing data |
|---|---|
| Mac | `~/Library/Application Support/CleanTake` |
| Windows | `%LOCALAPPDATA%\CleanTake` |
| Linux | `$XDG_DATA_HOME/cleantake`, or `~/.local/share/cleantake` |

Decisions are saved as you edit. Closing the app stops processing and retains
the last published project revision; interrupted jobs can be retried after
reopening. **Edit → Undo/Redo** changes project decisions in the editor and text
when you are typing in a field. Close the app before opening its workspace with
the command-line edition.

## If something does not work

- **First launch is slow:** the operating system may need time to check bundled
  libraries. CleanTake keeps its launch window visible while the studio starts.
  If startup fails, the dialog offers a retry and access to its log.
- **Workspace already open:** close the other CleanTake studio using it, then
  retry.
- **No sound:** check the system output device and volume. No GPU computing
  driver is required, but the computer still needs working operating-system
  display and audio support.
- **Import or alignment problem:** see [common problems](INSTALLATION.md#common-problems)
  and the [editing guide](GUIDE.md).

For a bug report, include your operating-system version, the installer file name
and the exact error. Keep private recordings and session links out of public
issues.

## Licenses and component source

The app includes [third-party notices](../THIRD_PARTY_NOTICES.md). The matching
release's [native source supplement](https://github.com/pavangupta352/cleantake/releases/download/v0.2.0/CleanTake-0.2.0-native-sources.tar.xz)
contains the corresponding covered-component source and build instructions,
including the supplement for **Electron 44.2.0 / Chromium 152.0.7977.76**, alongside
the bundled FFmpeg and SoundFile component sources. It is for inspection and
rebuilding; it is not needed to install or use CleanTake. The application's
Electron and Chromium license notices remain included with the app.
