# Desktop installation

The 0.2.0 desktop candidates are being verified. The published 0.1.0 release uses
the [Python/browser installation](INSTALLATION.md). Native release notes will
identify the tested installers and their publisher-signing status.

The desktop edition includes its audio tools, Python, processing libraries,
editing window, and sample recordings. You do not need to install developer
tools, download a model, create an account, or install a GPU computing driver.
Recordings and edits stay on your computer.

## Choose your download

| Computer | Download type | Architecture choice |
|---|---|---|
| Mac, macOS 14 or newer | `.dmg` | `arm64` for Apple silicon; `x64` for Intel |
| Windows | `.exe` | `x64` for Intel/AMD; `arm64` for Windows on ARM |
| Ubuntu / Debian desktop | `.deb` | `amd64` for Intel/AMD; `arm64` for ARM |

On a Mac, **About This Mac** shows either an Apple chip or an Intel processor.
On Windows, **Settings → System → About → System type** identifies the processor
architecture. Match the download to the processor; an ARM download is not an
alternative name for a 64-bit Intel/AMD download.

The intended Windows minimum is Windows 10 for x64 and Windows 11 for ARM64.
Linux builds use Ubuntu 22.04 for x64 and Ubuntu 24.04 for ARM64. Exact runner
and dependency evidence belongs to each release. These targets do not cover
32-bit systems, phones, every Linux distribution, or computers whose operating
system cannot provide normal display and audio output.

## Install and open

**Mac:** open the DMG, drag CleanTake into Applications, and open the installed
application. Eject the disk image afterward. Replace the application when
upgrading; your saved projects live elsewhere.

**Windows:** open the matching installer. It installs for your user and creates
normal application shortcuts. Use **Settings → Apps** to remove it. Removing
the application preserves saved projects.

**Ubuntu / Debian:** install the downloaded package through your package manager.
For example, from the directory containing the Intel/AMD download:

```sh
sudo apt install ./CleanTake-0.2.0-linux-amd64.deb
```

The package manager resolves the required operating-system desktop libraries.
Those downloads may need an internet connection. CleanTake's own audio tools
and processing runtime are already in the package. Open CleanTake from your
application launcher after installation.

Linux portable archives are a secondary route. They cannot install desktop
libraries or an application-specific sandbox policy, and therefore have narrower
compatibility than the Debian package. Use the package on distributions that
restrict unprivileged user namespaces; do not disable the browser sandbox.

## Try a repair immediately

The first launch adds **Sample · recover a missing half-second** to an empty
workspace. Open it, select the passage near 17 seconds, and listen to **Original**
and **Source**. The backup contains the recorded speech missing from the main
microphone. Choose **Accept repair** to include it in **Repair** playback, then
export the result.

The sample uses real, licensed AMI recordings with a clearly labeled injected
gap. Its suggestion starts pending. Removing the sample does not make it
reappear on every launch. Existing projects are preserved.

For your own recording, create a project and add a main recording plus its
simultaneous backups. See the [editing guide](GUIDE.md) for alignment, listening,
manual repairs, transcripts, and exports.

## Saved work and updates

Decisions are saved as you edit. Closing CleanTake stops processing and keeps
the last published project revision. Interrupted jobs can be retried after
reopening. **Edit → Undo/Redo** operates on project decisions when you are in the
editor and on text when you are typing in a field.

Default project folders are the same as the browser/CLI edition:

| System | Saved projects and processing data |
|---|---|
| macOS | `~/Library/Application Support/CleanTake` |
| Windows | `%LOCALAPPDATA%\CleanTake` |
| Linux | `$XDG_DATA_HOME/cleantake`, or `~/.local/share/cleantake` |

Export a portable project archive to move work between computers. A native
application update does not replace this workspace. Close the application before
editing the same workspace through the command line.

**Help → Downloads and updates** opens the release page. Updates are installed
explicitly; the application does not silently replace executable code.

## First-launch and troubleshooting

First launch can take longer while the operating system validates bundled
libraries. CleanTake shows its launch window until the studio is ready. If the
audio service cannot start, the dialog offers a retry and access to its log.
The log excludes private session tokens.

Application dependencies and publisher trust are separate checks. Ad-hoc macOS
signatures are not notarization, and unsigned Windows builds do not identify a
verified publisher. Read the actual release's signing status before installing.
An installer never removes quarantine, changes trusted roots, or disables
platform security to hide a warning.

If a workspace is already open, close its other studio first. If audio does not
play, check the system output device and volume. CleanTake does not replace
missing operating-system hardware drivers. For import or alignment problems,
see [common problems](INSTALLATION.md#common-problems).
