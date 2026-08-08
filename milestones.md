# Porting Milestones: Electrobun to GTK 4 (Python)

This document outlines the milestones, architectural translation, and verification steps for porting the **External Drive Media Organizer** from Electrobun (React + Vite + Bun) to a native Linux Python application built on **GTK 4 (PyGObject)**.

---

## Technical Translation Matrix

| Electrobun Component | Python/GTK 4 Translation | Libraries / APIs |
| :--- | :--- | :--- |
| **Main Process Runtime** | Python 3.14+ Script Engine | Python standard library |
| **Renderer UI / View** | Native GTK 4 Widgets | `gi.repository.Gtk` (PyGObject) |
| **Database Engine** | SQLite Database Client | `sqlite3` (Python Standard Library) |
| **File Scanner** | Background Scan Thread | `threading`, `os.walk`, `GLib.idle_add` |
| **System Info (Drives)** | Linux Mount & Block Scanner | `psutil`, `/proc/mounts`, `udisksctl` |
| **Folder Picker Dialog** | Modern File Portal Picker | `Gtk.FileDialog` (Native GTK 4 API) |
| **Thumbnail Resizer** | Image Resize Utilities | `Pillow` (`PIL`) |
| **Video Thumbnailer** | FFmpeg Wrapper (VAAPI / SW) | `subprocess`, `os.kill` (SIGSTOP/SIGCONT) |
| **External Player** | System App Opener | `Gio.AppInfo.launch_default_for_uri` / `xdg-open` |
| **Google Drive Client** | Service Account GDrive Uploader | `google-auth`, `google-api-python-client` |
| **Styling** | GTK CSS Providers | Custom CSS files via `Gtk.CssProvider` |

---

## Detailed Milestones

### Milestone 1: Environment Setup & Python Dependencies
- **Objective**: Establish the Python development environment with required dependencies.
- **Tasks**:
  1. Add dependencies to `pyproject.toml` using `uv`:
     - `psutil` (system & disk utility)
     - `pillow` (image thumbnail generator)
     - `google-auth` & `google-api-python-client` (GDrive integration)
  2. Verify that `pygobject` and system packages are installed and functional (Gtk-4.0 libraries, GStreamer for video playback).
  3. Set up the project structure with directories for views and utilities.

### Milestone 2: Portable SQLite Database Layer (`database.py`)
- **Objective**: Port the SQLite schema and portable database parameters designed for exFAT removable drives.
- **Tasks**:
  1. Port schema creation queries (`media_items`, `albums`, `tags`, `media_tags`) with indexes.
  2. Implement drive-safe connection configurations:
     - `PRAGMA busy_timeout = 5000`
     - `PRAGMA journal_mode = DELETE` (Ensures exFAT compatibility, avoids WAL-related malformation issues)
     - `PRAGMA synchronous = FULL`
  3. Implement background backup creation using `VACUUM INTO`.
  4. Port backup rotation logic (keeping the 5 most recent snapshots).
  5. Implement corruption detection and auto-recovery from the latest valid backup.

### Milestone 3: Drive & Storage Manager (`drives.py`, `file_ops.py`)
- **Objective**: Scan system block devices and handle physical file moves safely.
- **Tasks**:
  1. Read block devices using `psutil` and filter out system mounts (e.g. swap, squashfs, boot).
  2. Detect mountpoints (especially in `/run/media/` for USB storage).
  3. Port block device mounting using `udisksctl mount -b /dev/...`.
  4. Implement `move_file` with copy-and-unlink fallback to support moves across different partition boundaries.

### Milestone 4: Non-Blocking Media Scanner & Thumbnailer (`scanner.py`, `thumbnails.py`)
- **Objective**: Perform folder index scanning and thumbnail generation without freezing the GTK UI.
- **Tasks**:
  1. Implement a recursive folder walker running in a background `threading.Thread`.
  2. Communicate scanner state/progress back to GTK main thread using `GLib.idle_add`.
  3. Implement file ignore list filtering matching folder/segments/relative paths.
  4. Implement Pillow-based image thumbnail generation.
  5. Implement FFmpeg video thumbnail generation supporting hardware acceleration (`vaapi` on `/dev/dri/renderD128`) with software decoding fallback.
  6. Implement a thumbnail concurrency queue (max 2 concurrent workers).
  7. Implement video playback signal interception (SIGSTOP/SIGCONT) to pause and resume active ffmpeg processes to prevent UI/playback stutter.

### Milestone 5: Google Drive Backup Client (`gdrive.py`)
- **Objective**: Backup database snapshots to Google Drive using service accounts.
- **Tasks**:
  1. Implement auth flow using service account JSON credentials.
  2. Implement file list checks to see if `.media_library.db` or backup files already exist on Drive.
  3. Upload/update backup databases into a specified Google Drive folder ID.

### Milestone 6: Application Shell & UI Styles (`gui.py`, `style.css`)
- **Objective**: Scaffold the GTK 4 App, layout routing, and custom CSS theme.
- **Tasks**:
  1. Build a modern `Gtk.Application` skeleton with main window structure.
  2. Create a layout consisting of a left sidebar navigation, top bar, and content views.
  3. Add custom dark-mode CSS (`Gtk.CssProvider`) with glassmorphic styles, rounded corners, and premium colors (matching DaisyUI's premium feel).
  4. Set up view-routing using `Gtk.Stack` to switch between active sub-pages.

### Milestone 7: GTK 4 Native Views Implementation
- **Objective**: Create the functional views to match the React routes.
- **Tasks**:
  1. **Drive Selector (`views/drive_selector.py`)**: List connected drives, used capacity bars, mount status badges, and trigger selection. Include native folder picker via `Gtk.FileDialog` for custom directory mounts.
  2. **Scanner / Discover Control (`views/discover.py`)**: Interactive ignore list manager (with preset chips/badges), scanner controller (Start/Stop), progress bar, and scan log viewer.
  3. **Media Grid (`views/media_grid.py`)**: Grid layout (`Gtk.FlowBox` or `Gtk.GridView`) showing media items. Supports search entry, filter dropdowns (All / Images / Videos), sorting, and page controls.
  4. **Albums View (`views/albums.py`)**: Grid of albums displaying custom cover thumbnails and media counts.
  5. **Media Detail Viewer (`views/media_viewer.py`)**: Image viewer or video player (`Gtk.Video` or `GstPlayBin` overlay). Displays item metadata JSON, categories, and tags. Pauses thumbnailer queue during active video play.
  6. **Settings Page (`views/settings.py`)**: Text area for service account credentials, backup testing utilities, and system defaults.

### Milestone 8: Consolidation Flow & Integration Testing
- **Objective**: Wire up virtual staging execution and test the application end-to-end.
- **Tasks**:
  1. Implement the consolidation panel: group unsorted/sorted items and show final transaction details.
  2. Verify dry-run space checks and destination folder creation.
  3. Verify de-duplication rules (deleting files with matching SHA-256 or renaming if hashes differ).
  4. Test drive yanking/interruptions and verify SQLite recovery.
