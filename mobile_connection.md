# Mobile Device Local Network Sync & Streaming Guide

This document explains how to connect mobile devices (Android, iOS) over your local Wi-Fi/LAN network to inspect library statistics, download fresh SQLite database snapshots (`.media_library.db`), stream full-resolution media directly to mobile decoders, and load media thumbnails on demand from the **External Drive Media Organizer**.

---

## Prerequisites

1. **Same Wi-Fi / LAN Network**: Your desktop running the External Drive Media Organizer and your mobile device must be connected to the same local router or subnet.
2. **Active Media Drive**: An external drive or folder must be mounted and selected in the desktop app.

---

## Step-by-Step Setup Instructions

### 1. Enable Mobile Sync Server via GUI (GTK Settings)

1. Launch the **External Drive Media Organizer** GTK 4 application (`python main.py`).
2. Click **Settings** in the left sidebar navigation.
3. Scroll down to the **Local Network Mobile Sync** section.
4. Toggle **Enable Mobile Sync Server** to **ON**.
5. *(Optional)* Modify the **Server Port** if needed (default port is `8080`).

Once enabled, the status indicator will display:
```text
● Server Active on 192.168.x.x:8080
```
and generate a live download URL:
```text
http://192.168.x.x:8080/download/db
```

Click the **Copy URL** button to copy the download link to your clipboard.

### 2. Or Start Headless Server via CLI (`--server`)

You can also run the sync server standalone without starting the GUI (e.g. on headless machines, Raspberry Pi, or background terminal):

```bash
# Auto-detect connected media drive on port 8080
python main.py --server

# Specify custom port and drive path
python main.py --server --port 8080 --drive /path/to/drive
```

This immediately outputs the network IP and endpoint addresses to the console.

---

## Connecting & Using from Mobile Devices

### 1. Library Overview & Database Download

- **Server Health & Metrics**:
  Navigate to `http://<SERVER-IP>:<PORT>/` (e.g. `http://192.168.1.100:8080/`) in any mobile browser to inspect library statistics:
  ```json
  {
    "status": "online",
    "server": "Media Library Mobile Sync Server",
    "drive_name": "ExternalDrive",
    "download_url": "http://192.168.1.100:8080/download/db",
    "stats": {
      "total_items": 1420,
      "images": 1100,
      "videos": 320,
      "albums": 12,
      "tags": 25,
      "db_size_formatted": "4.2 MB"
    }
  }
  ```

- **Download SQLite Database**:
  Navigate to `http://<SERVER-IP>:<PORT>/download/db` to download a vacuumed snapshot of `media_library.db`.

---

### 2. Full Media Streaming with Video Seeking (`/media/<item_id>`)

The server streams original media files directly to the mobile device, allowing the mobile client's hardware decoder to handle playback.

- **URL Format**: `http://<SERVER-IP>:<PORT>/media/<item_id>`
- **HTTP Range Requests (Seeking)**: Full support for `Range: bytes=START-END` and `206 Partial Content`. Mobile video players (Safari iOS, Chrome Android, VLC, MX Player, AVPlayer) can seek and scrub instantly without downloading the whole file first.
- **HTML5 Video Player Example**:
  ```html
  <video controls playsinline width="100%">
    <source src="http://192.168.1.100:8080/media/42" type="video/mp4">
    Your browser does not support HTML5 video.
  </video>
  ```
- **Direct Image Display**:
  ```html
  <img src="http://192.168.1.100:8080/media/42" alt="Full Resolution Photo" />
  ```

---

### 3. On-Demand Thumbnail Generation (`/thumbnail/<item_id>`)

- **URL Format**: `http://<SERVER-IP>:<PORT>/thumbnail/<item_id>`
- **Behavior**:
  - Serves cached JPEG thumbnails from `<drive_path>/albums/thumbs/<file_hash>.jpg`.
  - If a thumbnail does not exist yet on disk, it is generated synchronously via Pillow (for images) or FFmpeg (for videos) and returned as `image/jpeg`.
- **Usage Example**:
  ```html
  <img src="http://192.168.1.100:8080/thumbnail/42" width="200" height="200" loading="lazy" />
  ```

---

## API Endpoints Reference

| Endpoint | HTTP Method | Description | Content-Type | Range / Seeking |
| :--- | :--- | :--- | :--- | :--- |
| `/` or `/api/info` | `GET`, `HEAD` | Server health, drive info, and library item breakdown. | `application/json` | No |
| `/download/db` | `GET`, `HEAD` | Generates a fresh exFAT-safe SQLite `VACUUM INTO` snapshot and streams `.media_library.db`. | `application/x-sqlite3` | No |
| `/media/<item_id>` | `GET`, `HEAD` | Streams full-resolution image or video with partial content range support. | Matches file MIME type (`video/mp4`, `image/jpeg`, etc.) | **Yes (`206 Partial Content`)** |
| `/thumbnail/<item_id>` | `GET`, `HEAD` | Retrieves or synchronously generates a 400px JPEG thumbnail. | `image/jpeg` | Yes |
| `/api/db/stats` | `GET`, `HEAD` | Alias for library metrics. | `application/json` | No |

---

## Technical Specifications & Safety Features

- **Path Traversal Protection**: Every `/media/<id>` and `/thumbnail/<id>` request resolves the target file's real path with `os.path.realpath` and strictly confirms it resides within the active `drive_path` root before opening.
- **Read-Only Non-Locking DB Snapshots**: Database downloads use SQLite's `VACUUM INTO` syntax to generate isolated snapshots, preventing file-locking conflicts with active scanner or write operations.
- **Threaded Concurrent HTTP Server**: Built on Python's `ThreadingMixIn` to handle multiple parallel video streams and thumbnail fetches.
- **CORS Enabled**: Standard `Access-Control-Allow-Origin: *`, `Access-Control-Allow-Headers: Range, Content-Type`, and `Access-Control-Expose-Headers: Content-Range, Accept-Ranges, Content-Length` headers allow web browsers and PWAs to stream seamlessly.
- **Graceful Connection Drops**: Interrupted video playback streams (e.g. scrubbing or closing browser tabs) handle `BrokenPipeError` and `ConnectionResetError` gracefully.

---

## Troubleshooting

- **Mobile Device Cannot Connect**:
  - Verify that both mobile device and Linux host are on the exact same Wi-Fi network (not isolated guest Wi-Fi).
  - If a Linux firewall (`ufw`) is active, allow the sync server port:
    ```bash
    sudo ufw allow 8080/tcp
    ```
- **Port Already in Use**:
  - If port `8080` is occupied by another local service, change the port in Settings (e.g. `8888` or `9090`) and toggle the server switch off and on again.
