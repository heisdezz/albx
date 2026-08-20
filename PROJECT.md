# External Drive Media Organizer

Native Linux Python GTK 4 application for scanning, organizing, previewing, and consolidating media assets across external storage drives and removable devices.

---

## Technical Translation Matrix

| Electrobun Component | Python / GTK 4 Translation | Libraries / APIs |
| :--- | :--- | :--- |
| **Main Process Runtime** | Python 3.14+ Script Engine | Python standard library (`threading`, `sqlite3`, `subprocess`) |
| **Renderer UI / View** | Native GTK 4 Widgets | `gi.repository.Gtk`, `Gdk`, `GLib` (PyGObject) |
| **Database Engine** | Portable SQLite Client | `sqlite3` (Python Standard Library with exFAT pragmas) |
| **File Scanner** | Background DFS Directory Walker | `threading.Thread`, `os.walk`, `GLib.idle_add` |
| **System Info (Drives)** | Linux Mount & Block Scanner | `psutil`, `/proc/mounts`, `udisksctl` |
| **Folder Picker Dialog** | Native GTK 4 File Portal | `Gtk.FileDialog` |
| **Thumbnail Generator** | Image Scaler & Resizer | `Pillow` (`PIL.Image`) |
| **Video Thumbnailer** | FFmpeg Wrapper (VAAPI / SW) | `subprocess`, `os.kill` (`SIGSTOP` / `SIGCONT` concurrency control) |
| **External Player** | System App Launcher / Player | `Gio.AppInfo.launch_default_for_uri`, `Gtk.Video` / PySide6 MPV |
| **Google Drive Client** | Service Account Backup Syncer | `google-auth`, `google-api-python-client` |
| **Mobile Sync Server** | Local Network HTTP Server | `http.server.ThreadingHTTPServer`, `socket` |
| **Styling** | GTK CSS Provider | Custom CSS theme via `Gtk.CssProvider` |

---

## System Architecture & File Structure

```
.
├── core/                        # Core backend & business logic modules
│   ├── database.py              # Portable SQLite DB layer, schemas, pragmas & auto-recovery
│   ├── drives.py                # Mount point detection & udisksctl block device manager
│   ├── file_ops.py              # Cross-boundary move_file with copy-and-unlink fallback
│   ├── gdrive.py                # Google Drive Service Account snapshot backup client
│   ├── logger.py                # Centralized logging & thread-safe event streaming
│   ├── media_ops.py             # Consolidation engine, metadata extraction & hash deduplication
│   ├── scanner.py               # Non-blocking directory walker & path ignore list filter
│   ├── sync_server.py           # Threaded HTTP server for LAN mobile DB sync, video streaming & thumbnails
│   └── thumbnails.py            # Pillow image & FFmpeg VAAPI video thumbnail generator
├── drive_gtk/                   # GTK 4 Native Frontend Application
│   ├── main.py                  # GTK App Entrypoint & Window initializer
│   ├── router.py                # View switching stack controller
│   └── ui/                      # UI components, layout views & styling
│       ├── gui.py               # Main window layout, sidebar navigation & topbar
│       ├── style.css            # Dark mode glassmorphic CSS stylesheet
│       ├── views/               # Sub-views (Stack pages)
│       │   ├── drive_selector.py# Drive selection, mounting status & folder picker
│       │   ├── discover.py      # Scanner controls, path ignore-list & scan logs
│       │   ├── dashboard.py     # System stats, drive health & media distribution
│       │   ├── media_viewer.py  # Image viewer, video player, tagger & metadata panel
│       │   ├── albums.py        # Custom album collections & album media grid
│       │   └── settings.py      # GDrive config, Mobile LAN Sync server & local DB snapshots
│       └── widgets/             # Reusable UI Components
│           ├── filter_bar.py    # Search, type filtering (All/Images/Videos) & sorting
│           ├── media_card.py    # Individual thumbnail card item with status badges
│           └── media_grid.py    # Paginated flow grid layout with lazy loading
├── milestones.md                # Porting roadmap and architectural matrix
├── mobile_connection.md         # Guide for mobile device local network sync & DB download
├── progress.md                  # Milestone status tracking and task checklist
├── pyproject.toml               # Python dependencies and project configuration
├── SCHEMA.md                    # Database schema reference, ERD, triggers & query guide
└── main.py                      # Root launcher script
```

---

## Detailed Milestones & Implementation Specifications

### Milestone 1: Environment Setup & Python Dependencies
- **Objective**: Establish the Python dev runtime and system libraries.
- **Key Deliverables**:
  - `pyproject.toml` with `psutil`, `pillow`, `google-auth`, `google-api-python-client`, `pygobject`.
  - System library verification (`gi.require_version('Gtk', '4.0')`).
  - Base directory structure layout (`core/` and `drive_gtk/`).

### Milestone 2: Portable SQLite Database Layer (`core/database.py`)
- **Objective**: Implement exFAT-safe SQLite storage with automated snapshot backups and recovery.
- **Key Specifications**:
  - **Tables**: `media_items`, `albums`, `tags`, `media_tags` with indexed fields on paths and hashes.
  - **exFAT Safe Pragmas**:
    - `PRAGMA busy_timeout = 5000`
    - `PRAGMA journal_mode = DELETE` (Prevents exFAT POSIX file-locking corruption issues).
    - `PRAGMA synchronous = FULL`
  - **Backups**: Snapshot backups using SQLite `VACUUM INTO` into `.backups/`.
  - **Rotation & Auto-Recovery**: Retain 5 most recent snapshots; check DB integrity on startup and restore automatically if corrupted.

### Milestone 3: Drive & Storage Manager (`core/drives.py`, `core/file_ops.py`)
- **Objective**: Detect block devices, mount USB storage safely, and perform cross-filesystem file moves.
- **Key Specifications**:
  - **Drive Detection**: Parse `psutil.disk_partitions()` and `/proc/mounts`, filtering system/squashfs mounts.
  - **Volume Mounting**: Trigger `udisksctl mount -b /dev/...` for unmounted removable partitions.
  - **Cross-Boundary Move**: `move_file()` attempts atomic rename; falls back to copy + sync + unlink across different file system boundaries.

### Milestone 4: Non-Blocking Media Scanner & Thumbnailer (`core/scanner.py`, `core/thumbnails.py`)
- **Objective**: Scan directories and render media thumbnails without stalling GTK UI loop.
- **Key Specifications**:
  - **Scanner**: Threaded Depth-First Search (`threading.Thread`) reporting progress via `GLib.idle_add`.
  - **Ignore Filter**: Ignore list pattern matching against folder names, hidden paths, and relative segments.
  - **Image Thumbnailer**: Fast PIL scaling down to 320px high-quality webp/jpeg thumbnails.
  - **Video Thumbnailer**: FFmpeg extraction with hardware acceleration (`-hwaccel vaapi -vaapi_device /dev/dri/renderD128`) and software fallback.
  - **Throttle & Pause Control**: Concurrency limit of 2 thumbnail workers; supports sending `SIGSTOP`/`SIGCONT` signals to FFmpeg subprocesses when video playback starts.

### Milestone 5: Google Drive Backup Client (`core/gdrive.py`)
- **Objective**: Cloud backup of `.media_library.db` snapshots via Service Account credentials.
- **Key Specifications**:
  - Authentication via Google Service Account JSON configuration.
  - Remote folder search/creation on Google Drive.
  - Snapshot database upload and retention sync.

### Milestone 6: Application Shell & UI Styles (`drive_gtk/ui/gui.py`, `drive_gtk/ui/style.css`)
- **Objective**: Modern GTK 4 App Shell, sidebar layout, and glassmorphic styling.
- **Key Specifications**:
  - `Gtk.ApplicationWindow` containing sidebar navigation, header status bar, and central view stack (`Gtk.Stack`).
  - Custom CSS (`Gtk.CssProvider`) implementing dark mode palette, rounded corners, translucent surfaces, and hover animations.

### Milestone 7: GTK 4 Native Views Implementation (`drive_gtk/ui/views/*`)
- **Objective**: Functional UI views mapped to all application routes.
- **Views**:
  1. **Drive Selector (`drive_selector.py`)**: Removable storage list with capacity meters, mount status badges, and `Gtk.FileDialog` directory picker.
  2. **Discover / Scanner (`discover.py`)**: Scan controls, path ignore-list preset chips, real-time scan metrics, and progress bars.
  3. **Media Grid (`media_grid.py` & `widgets/media_grid.py`)**: Flow layout with paginated grid, lazy thumbnail loading, type filters, and search bar.
  4. **Albums (`albums.py`)**: Collection cards with cover image preview, album creation modals, and item management.
  5. **Media Detail (`media_viewer.py`)**: High-res preview, GStreamer/MPV video player overlay, tag editor, metadata inspector, and thumbnailer queue pause signal.
  6. **Settings (`settings.py`)**: Service account JSON editor, database backup controls, auto-scan settings, and system diagnostic logs.

### Milestone 8: Consolidation Flow & Integration Testing (`core/media_ops.py`)
- **Objective**: Drive consolidation workflow and end-to-end integration verification.
- **Key Specifications**:
  - Consolidation staging: Sort unsorted files into structured date/album destination folders.
  - Pre-flight dry-run checks: Storage capacity validation and write permission test.
  - Hash Deduplication: De-duplicate identical files via SHA-256 matching; rename unique file collisions safely.
  - System resilience tests: Drive disconnect recovery, database corruption fallback, and UI responsiveness under heavy load.

---

## Development & Usage

### Running the Application
```bash
# Install dependencies
uv sync

# Launch GTK 4 Application (default)
python main.py

# Launch Standalone Headless Sync Server (no GUI)
python main.py --server
python main.py --server --port 8080 --drive /path/to/drive

# Launch Qt Frontend
python main.py --qt
```

### Running Type & Lint Checks
```bash
# Verify GTK PyGObject & Python type safety
bunx tsgo --noEmit  # or pyright
```
