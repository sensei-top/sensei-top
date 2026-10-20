# Installing Sensei Top

Sensei Top runs on Windows 10 and 11 (64-bit) and on 64-bit Linux. Every
download is on the [releases page](https://github.com/sensei-top/sensei-top/releases).
There is nothing to sign up for.

- [Windows](#windows)
- [Linux](#linux): [Arch-based](#arch-based-distributions-cachyos-endeavouros-manjaro),
  [Ubuntu](#ubuntu), [SteamOS](#steamos-desktop-mode)
- [Where your data lives](#where-your-data-lives)
- [Updates](#updates)

The first time it opens, the app walks you through setup: it asks which you
play, looks for Arena's log, asks where Magic Online keeps its game logs if
you play there, and downloads the card data on its own. In Arena, turn on
**Detailed Logs (Plugin Support)** under Options → Account, then restart
Arena. Without it, Arena's log is missing most of what the app reads.

## Windows

1. Download `Sensei-Top-Setup-<version>.exe`.
2. Run it. It first asks for its language, English or Português (Brasil);
   the app opens in the same one, and Settings can change it later. It
   installs for your Windows user only and never asks for administrator
   rights.
3. On the last page, choose whether Sensei Top should start when Windows
   starts. You can change this later in Settings.

**"Windows protected your PC."** The installer is not code-signed yet, so
Microsoft Defender SmartScreen may stop it the first time. Click **More
info**, then **Run anyway**.

Closing the window keeps Sensei Top running in the system tray, so it
records the games you play with the window closed. Quit from the tray
icon's menu.

To uninstall, use **Installed apps** in Windows' Settings (**Apps &
features** on Windows 10).
Uninstalling keeps your match history; see
[where your data lives](#where-your-data-lives).

## Linux

The Linux build is one file, an AppImage. It is not installed: you keep the
file somewhere and run it.

1. Download `Sensei-Top-<version>.AppImage`.
2. Move it to a folder of your own, such as `~/Applications`. It updates
   itself by replacing this file, so keep it in a folder you can write to.
3. Make it executable, then run it:

       chmod +x ~/Applications/Sensei-Top-*.AppImage
       ~/Applications/Sensei-Top-*.AppImage

   Most file managers can do the same: open the file's properties, allow
   it to run as a program, then double-click it.

The AppImage needs FUSE 2 (`libfuse.so.2`) to run. If it exits with
`dlopen(): error loading libfuse.so.2`, install the package your
distribution's section below names. If you can't install it, this runs the
app without FUSE, unpacking it to a temporary folder first, so it starts
more slowly:

    ~/Applications/Sensei-Top-*.AppImage --appimage-extract-and-run

**Closing the window quits the app on Linux**, so games you play afterwards
are not recorded. To keep it running, turn on **Keep running when the window
is closed** in Settings, and reopen the window from the tray icon. On GNOME
there is no tray icon unless the
[AppIndicator extension](https://extensions.gnome.org/extension/615/appindicator-support/)
is installed, so leave this setting off there unless you have that extension.

**Arena on Linux.** Arena is found on its own when you run it through
Steam (Proton), installed natively, as a Flatpak or as a Snap, with the
game in any of your Steam libraries; through Lutris, Heroic or Bottles,
installed natively or as a Flatpak; or with plain Wine, in `~/.wine` or
the prefix `WINEPREFIX` names. When more than one of these holds a log,
the one Arena wrote to last is read. If yours isn't found (a prefix
kept somewhere none of these launchers records it, say), set it under
**Settings → Sources → Arena → Log file**. It is inside the prefix, at:

    <prefix>/drive_c/users/<user>/AppData/LocalLow/Wizards Of The Coast/MTGA/Player.log

**Magic Online on Linux.** Setup asks for the folder where Magic Online
writes files named `Match_GameLog`. Under Wine or Proton it is inside the
prefix, under
`drive_c/users/<user>/AppData/Local/Apps/2.0/Data/`. Magic Online moves this
folder when it updates, so if the app stops seeing your games, choose the
folder again in **Settings → Sources → Magic Online**.

### Arch-based distributions (CachyOS, EndeavourOS, Manjaro)

Install FUSE 2 if it is missing:

    sudo pacman -S fuse2

Tested on CachyOS with GNOME, under Wayland and under XWayland.

### Ubuntu

> **Untested.** These steps follow Ubuntu's documentation but no one has
> run them yet. If you try them, please
> [tell us how it went](https://github.com/sensei-top/sensei-top/discussions).

The AppImage needs Ubuntu 24.04 or later: it is built on 24.04, and the
server inside it needs a C library at least as new as that release's.
Install FUSE 2:

    sudo apt install libfuse2t64

Ubuntu 24.04 stops ordinary applications from creating user namespaces,
which Chromium (and so Electron, which Sensei Top's window is built on)
uses as its sandbox. When the AppImage's launcher finds that blocked, it
starts the app with Chromium's sandbox turned off rather than failing.
The window only ever shows the app's own pages, served from your
computer, and opens every outside link in your web browser.

If the app still won't start and the terminal shows a sandbox error, run it
with `--no-sandbox` added to the command, and please report it.

### SteamOS (desktop mode)

Use desktop mode (Steam button → Power → Switch to Desktop). SteamOS
replaces its system files when it updates, so keep everything in your home
folder and install nothing system-wide.

1. Download the AppImage in desktop mode, then move it to `~/Applications`
   (create the folder in Dolphin if it doesn't exist).
2. Right-click the file → **Properties** → **Permissions**, tick
   **Is executable**, then double-click the file.
3. To add it to the application menu: right-click the application launcher
   (the Steam Deck logo, bottom left) → **Edit Applications…** → **New
   Item**. Name it Sensei Top, set **Program** to the AppImage's path, and
   save.

If it won't start, try the `--appimage-extract-and-run` command from the
Linux section above.

Sensei Top runs only in desktop mode for now. Returning to Game Mode
closes it with the rest of the desktop, so play Arena in desktop mode
while you want your games recorded. Starting it from Game Mode hasn't been
tried yet.

## Where your data lives

Your match history is one database file in a folder of its own. Settings
shows the folder and has a button that opens it.

| | Windows | Linux |
|---|---|---|
| Match history, backups, logs | `%LOCALAPPDATA%\Sensei Top\` | `~/.local/share/sensei-top/` |
| Settings and keys | `%APPDATA%\sensei-top\config.toml` | `~/.config/sensei-top/config.toml` |

A Claude or TopDeck.gg key you add is kept in Windows Credential Manager,
or in the system keyring on Linux. Only when no keyring exists does it go
in `config.toml`.

Uninstalling the app, or deleting the AppImage, leaves these folders where
they are, so reinstalling picks up where you left off. Delete them yourself
to remove everything.

## Updates

Once a day, and each time it starts, the app checks the releases page for a
newer version. The request carries what any web request does, your IP
address and the app's version among it, and nothing about your games. A
newer version downloads in the background and installs when you quit, or
straight away from **Restart to update** in Settings. To stop checking,
turn off **Check for updates** in Settings.
