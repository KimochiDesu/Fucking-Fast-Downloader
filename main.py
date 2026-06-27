#!/usr/bin/env python3
"""
Fucking Fast Downloader
A PyQt5 application to download files from provided links.

Usage:
  - Click "Load Links" to import download links from input.txt.
  - Double-click any link in the list to copy it to clipboard.
  - Click "Download All" to start downloading.
  - Use the Pause/Resume buttons to control downloads.
"""

import os
import re
import sys
import json
import time
import threading
import webbrowser
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ.setdefault('QT_API', 'pyqt5')

import requests
from bs4 import BeautifulSoup

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QFontDatabase
from qt_material import apply_stylesheet

# Global configuration
INPUT_FILE = "input.txt"
DOWNLOADS_FOLDER = "downloads"
SETTINGS_FILE = "settings.json"


def load_settings():
    defaults = {"simultaneous_download": False}
    try:
        with open(SETTINGS_FILE, 'r') as f:
            defaults.update(json.load(f))
    except Exception:
        pass
    return defaults


def save_settings(settings):
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
    except Exception:
        pass

if not os.path.exists(DOWNLOADS_FOLDER):
    os.makedirs(DOWNLOADS_FOLDER)

HEADERS = {
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'accept-language': 'en-US,en;q=0.5',
    'referer': 'https://fitgirl-repacks.site/',
    'sec-ch-ua': '"Brave";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'user-agent': (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}

# ---------------------------------------------------------------------------
# Helper function to colorize log messages based on content.
def colorize_log_message(message):
    """
    Return the message wrapped in an HTML span with a color and emoji
    based on keywords in the message.
    """
    msg_lower = message.lower()
    emoji = ""
    
    if "error" in msg_lower or "❌" in message:
        color = "#FF6347"  # Tomato
        if "❌" not in message:
            emoji = "❌ "
    elif "completed" in msg_lower or "✅" in message:
        color = "#32CD32"  # LimeGreen
        if "✅" not in message:
            emoji = "✅ "
    elif "paused" in msg_lower:
        color = "#FFD700"  # Gold
        if "⏸️" not in message:
            emoji = "⏸️ "
    elif "resumed" in msg_lower:
        color = "#00BFFF"  # DeepSkyBlue
        if "▶️" not in message:
            emoji = "▶️ "
    elif "downloading" in msg_lower or "⬇️" in message:
        color = "#1E90FF"  # DodgerBlue
        if "⬇️" not in message:
            emoji = "⬇️ "
    elif "processing link" in msg_lower:
        color = "#40E0D0"  # Turquoise
        if "🔗" not in message:
            emoji = "🔗 "
    elif "loaded" in msg_lower:
        color = "#DA70D6"  # Orchid
        if "📥" not in message:
            emoji = "📥 "
    else:
        color = "#FFFFFF"  # Default to white if no keywords match

    return f"<span style='color:{color};'>{emoji}{message}</span>"

def resolve_cdn_url(link):
    """Resolve a fuckingfast.co link to (filename, cdn_url) using a headless browser.
    The site executes JS to call window.open() with the real CDN URL; we intercept that."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise Exception(
            "playwright not installed. Run: pip install playwright && playwright install chromium"
        )

    page_url = link.split('#')[0]
    captured = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=HEADERS['user-agent'])
        page = ctx.new_page()
        page.expose_function('_captureWindowOpen', lambda u: captured.append(u))
        page.add_init_script("""
            const _orig = window.open;
            window.open = function(url, ...args) {
                if (url) window._captureWindowOpen(String(url));
                return _orig.apply(this, [url, ...args]);
            };
        """)
        try:
            page.goto(page_url, wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(1500)

            content = page.content()
            soup = BeautifulSoup(content, 'html.parser')

            download_url = None
            for script in soup.find_all('script'):
                text = script.string or ''
                m = re.search(r'window\.open\(["\']?(https?://[^\s"\')\]]+)', text)
                if m:
                    download_url = m.group(1)
                    break

            if not download_url:
                for sel in [
                    '#download', '.download-btn', '[id*="download"]',
                    'a[download]', 'button:text("Download")', 'a:text("Download")',
                ]:
                    try:
                        btn = page.query_selector(sel)
                        if btn:
                            btn.click()
                            page.wait_for_timeout(2000)
                            break
                    except Exception:
                        continue

            if captured:
                download_url = captured[0]

            if not download_url:
                raise Exception("Could not find download URL on page")

            try:
                meta = soup.find('meta', {'name': 'title'})
                if meta and meta.get('content'):
                    filename = re.sub(r'[\\/*?:"<>|]', "", meta['content'])
                else:
                    filename = os.path.basename(page_url.rstrip('/')).split('?')[0][:120] or 'download'
            except Exception:
                filename = 'download'

            return filename, download_url
        finally:
            browser.close()


# ----------------------- GUI Code -----------------------
class DownloaderWorker(QtCore.QThread):
    """
    Thread-safe worker with proper signal handling
    """
    log_signal = QtCore.pyqtSignal(str)
    progress_signal = QtCore.pyqtSignal(int, int)
    file_signal = QtCore.pyqtSignal(str)
    status_signal = QtCore.pyqtSignal(str)
    speed_signal = QtCore.pyqtSignal(float)
    link_removed_signal = QtCore.pyqtSignal(str)
    link_failed_signal = QtCore.pyqtSignal(str)
    error_signal = QtCore.pyqtSignal(str)

    def __init__(self, links, simultaneous=False, parent=None):
        super().__init__(parent)
        self.links = links
        self.simultaneous = simultaneous
        self._is_paused = False
        self._lock = QtCore.QMutex()
        self.active = True

    def pause(self):
        with QtCore.QMutexLocker(self._lock):
            self._is_paused = True
        self.status_signal.emit("Paused")
        self.log_signal.emit("⏸ Download paused")

    def resume_download(self):
        with QtCore.QMutexLocker(self._lock):
            self._is_paused = False
        self.status_signal.emit("Resuming...")
        self.log_signal.emit("▶ Download resumed")

    def stop(self):
        self.active = False
        self.terminate()

    def run(self):
        mode = "simultaneous" if self.simultaneous else "sequential"
        self.log_signal.emit(f"🚀 Starting download session  [{mode} mode]")
        start_session = time.time()
        links = self.links.copy()

        try:
            # Phase 1: resolve all CDN URLs in parallel (max 3 browser instances)
            self.log_signal.emit(f"🔍 Resolving {len(links)} URLs in parallel...")
            self.status_signal.emit("Resolving URLs...")
            resolved = {}  # link -> (filename, cdn_url)

            with ThreadPoolExecutor(max_workers=3) as ex:
                futs = {ex.submit(resolve_cdn_url, lnk): lnk for lnk in links}
                done = 0
                for fut in as_completed(futs):
                    if not self.active:
                        break
                    lnk = futs[fut]
                    done += 1
                    try:
                        fname, cdn = fut.result()
                        resolved[lnk] = (fname, cdn)
                        self.log_signal.emit(f"🔗 [{done}/{len(links)}] Resolved: {fname}")
                    except Exception as e:
                        self.link_failed_signal.emit(lnk)
                        self.log_signal.emit(f"❌ [{done}/{len(links)}] Resolve failed: {lnk[:60]}\n   {e}")

            if not resolved or not self.active:
                return

            total = len(resolved)
            ordered = [lnk for lnk in links if lnk in resolved]

            if self.simultaneous:
                self.log_signal.emit(f"⬇️ Downloading {total} files simultaneously...")
                self.status_signal.emit("Downloading (simultaneous)...")

                with ThreadPoolExecutor(max_workers=4) as ex:
                    futs = {
                        ex.submit(self._download_one, lnk, fn, url, i + 1, total): lnk
                        for i, lnk in enumerate(ordered)
                        for fn, url in [resolved[lnk]]
                    }
                    for fut in as_completed(futs):
                        if not self.active:
                            break
                        lnk = futs[fut]
                        try:
                            fut.result()
                            self.link_removed_signal.emit(lnk)
                        except Exception as e:
                            self.link_failed_signal.emit(lnk)
                            self.log_signal.emit(f"❌ Download failed: {lnk[:60]}\n   {e}")
            else:
                self.log_signal.emit(f"⬇️ Downloading {total} files one by one...")
                self.status_signal.emit("Downloading...")

                for idx, lnk in enumerate(ordered, 1):
                    if not self.active:
                        break
                    fn, url = resolved[lnk]
                    try:
                        self._download_one(lnk, fn, url, idx, total)
                        self.link_removed_signal.emit(lnk)
                    except Exception as e:
                        self.link_failed_signal.emit(lnk)
                        self.log_signal.emit(f"❌ [{idx}/{total}] Download failed: {lnk[:60]}\n   {e}")

        finally:
            elapsed = time.time() - start_session
            self.log_signal.emit(
                f"🏁 Session finished\n"
                f"   Duration: {elapsed:.1f}s  |  Files: {len(links)}"
            )
            self.status_signal.emit("Idle")

    def get_remote_size(self, url):
        """Get file size in megabytes"""
        head = requests.head(url, headers=HEADERS, timeout=10)
        size_bytes = int(head.headers.get('content-length', 0))
        return size_bytes / (1024 * 1024)

    def download_file(self, url, path):
        """Download dispatcher with enhanced speed tracking"""
        try:
            head = requests.head(url, headers=HEADERS, timeout=10)
            total_size = int(head.headers.get('content-length', 0))
            accept_ranges = 'bytes' in head.headers.get('Accept-Ranges', '')

            # Initialize speed calculation
            self.dl_start_time = time.time()
            self.last_update = self.dl_start_time
            self.total_paused_time = 0.0
            self.last_bytes = 0
            
            if total_size > 1024*1024 and accept_ranges:
                self.chunked_download(url, path, total_size)
            else:
                self.single_thread_download(url, path)

        except requests.RequestException as e:
            raise Exception(f"Connection error: {str(e)}")

    def chunked_download(self, url, path, total_size):
        """Threaded download with accurate speed updates"""
        chunk_size = 4 * 1024 * 1024  # 4MB chunks
        chunks = range(0, total_size, chunk_size)
        
        with open(path, 'wb') as f:
            f.truncate(total_size)

        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = [executor.submit(
                self.download_chunk,
                url, start, min(start+chunk_size-1, total_size-1), path, i+1, len(chunks)
            ) for i, start in enumerate(chunks)]

            downloaded = 0
            for future in as_completed(futures):
                if not self.active:
                    executor.shutdown(wait=False)
                    break
                
                try:
                    chunk_size = future.result()
                    downloaded += chunk_size
                    self.update_speed_metrics(downloaded, total_size)
                    
                except Exception as e:
                    self.log_signal.emit(f"⚠️ Chunk failed: {str(e)}")

    def update_speed_metrics(self, downloaded, total_size):
        """Calculate and emit speed/progress updates"""
        now = time.time()
        if now - self.last_update > 0.2:  # Update every 200ms
            elapsed = now - self.dl_start_time - self.total_paused_time
            speed = downloaded / elapsed if elapsed > 0 else 0
            
            # Convert units
            speed_mb = speed / (1024 * 1024)
            downloaded_mb = downloaded / (1024 * 1024)
            total_mb = total_size / (1024 * 1024)
            
            # Emit updates
            self.speed_signal.emit(speed_mb)
            self.progress_signal.emit(downloaded, total_size)
            
            # Calculate ETA
            remaining = total_size - downloaded
            eta = remaining / speed if speed > 0 else 0
            
            self.log_signal.emit(
                f"📊 Progress update\n"
                f"   Speed: {speed_mb:.1f} MB/s\n"
                f"   ETA: {self.format_eta(eta)}\n"
                f"   Downloaded: {downloaded_mb:.1f}/{total_mb:.1f} MB"
            )
            
            self.last_update = now

    def format_eta(self, seconds):
        """Convert seconds to human-readable ETA"""
        if seconds <= 0:
            return "--:--"
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}"

    def download_chunk(self, url, start, end, path, chunk_num, total_chunks):
        """Chunk downloader with detailed logging"""
        self.log_signal.emit(
            f"🔽 Starting chunk {chunk_num}/{total_chunks}\n"
            f"   Range: {start}-{end} bytes"
        )
        
        for attempt in range(3):
            try:
                if self.should_pause():
                    self.wait_while_paused()

                headers = HEADERS.copy()
                headers['Range'] = f'bytes={start}-{end}'
                
                response = requests.get(url, headers=headers, stream=True, timeout=15)
                response.raise_for_status()
                
                chunk_data = bytearray()
                for data in response.iter_content(1024 * 256):  # 256KB blocks
                    if self.should_pause():
                        pause_start = time.time()
                        self.wait_while_paused()
                        self.total_paused_time += time.time() - pause_start
                    
                    chunk_data.extend(data)
                
                with open(path, 'r+b') as f:
                    f.seek(start)
                    f.write(chunk_data)
                
                self.log_signal.emit(
                    f"✅ Chunk {chunk_num}/{total_chunks} completed\n"
                    f"   Size: {len(chunk_data)//1024//1024} MB"
                )
                return len(chunk_data)
                
            except Exception as e:
                if attempt == 2:
                    raise Exception(f"Chunk failed after 3 attempts: {str(e)}")
                
                self.log_signal.emit(
                    f"🔄 Retrying chunk {chunk_num} (attempt {attempt+1}/3)\n"
                    f"   Error: {str(e)}"
                )
                time.sleep(1.5 ** attempt)

    def _download_one(self, link, file_name, download_url, idx=1, total=1):
        """Download a single file. All state is local so this is safe to run concurrently."""
        output_path = os.path.join(DOWNLOADS_FOLDER, file_name)
        self.file_signal.emit(f"[{idx}/{total}] {file_name}")
        self.log_signal.emit(f"⬇️ [{idx}/{total}] Downloading: {file_name}")
        dl_start = time.time()
        downloaded = 0

        with requests.get(download_url, headers=HEADERS, stream=True, timeout=30) as resp:
            resp.raise_for_status()
            total_size = int(resp.headers.get('content-length', 0))
            size_mb = total_size / 1024 / 1024
            if total_size:
                self.log_signal.emit(f"📦 [{idx}/{total}] Size: {size_mb:.1f} MB")

            with open(output_path, 'wb') as f:
                for chunk in resp.iter_content(1024 * 1024):
                    if not self.active:
                        return
                    while self.should_pause() and self.active:
                        time.sleep(0.1)
                    f.write(chunk)
                    downloaded += len(chunk)
                    elapsed = time.time() - dl_start
                    if elapsed > 0:
                        self.speed_signal.emit(downloaded / elapsed / 1024 / 1024)
                    if total_size:
                        self.progress_signal.emit(downloaded, total_size)

        elapsed = time.time() - dl_start
        self.log_signal.emit(
            f"✅ [{idx}/{total}] Completed: {file_name}  ({elapsed:.1f}s)"
        )

    def download_file(self, url, path):
        """Main download handler with thread safety"""
        try:
            head = requests.head(url, headers=HEADERS, timeout=10)
            total_size = int(head.headers.get('content-length', 0))
            accept_ranges = 'bytes' in head.headers.get('Accept-Ranges', '')

            if total_size > 1024*1024 and accept_ranges:  # Multi-thread for >1MB
                self.chunked_download(url, path, total_size)
            else:
                self.single_thread_download(url, path)

        except requests.RequestException as e:
            raise Exception(f"Connection error: {str(e)}")

    def single_thread_download(self, url, path):
        """Fallback single-thread download"""
        downloaded = 0
        start_time = time.time()
        
        with requests.get(url, stream=True, timeout=15) as response:
            response.raise_for_status()
            total_size = int(response.headers.get('content-length', 0))
            
            with open(path, 'wb') as f:
                for data in response.iter_content(1024 * 1024):  # 1MB chunks
                    if self.should_pause():
                        self.wait_while_paused()
                    
                    f.write(data)
                    downloaded += len(data)
                    
                    # Update from main thread
                    elapsed = time.time() - start_time
                    speed = (downloaded / elapsed) / 1024 / 1024 if elapsed > 0 else 0
                    self.speed_signal.emit(speed)
                    self.progress_signal.emit(downloaded, total_size)

    def should_pause(self):
        with QtCore.QMutexLocker(self._lock):
            return self._is_paused

    def wait_while_paused(self):
        while self.should_pause() and self.active:
            time.sleep(0.1)


class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️ Settings")
        self.setMinimumWidth(380)
        self.setModal(True)
        self.settings = dict(settings)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)

        # Download mode group
        group = QtWidgets.QGroupBox("Download Mode")
        group_layout = QtWidgets.QVBoxLayout(group)
        group_layout.setSpacing(8)

        self.seq_radio = QtWidgets.QRadioButton("Sequential — one file at a time  (Recommended)")
        self.sim_radio = QtWidgets.QRadioButton("Simultaneous — all files at once")

        if self.settings.get("simultaneous_download", False):
            self.sim_radio.setChecked(True)
        else:
            self.seq_radio.setChecked(True)

        note = QtWidgets.QLabel(
            "Sequential gives each file the full connection bandwidth.\n"
            "Simultaneous splits bandwidth across all active downloads."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #888; font-size: 11px; padding-top: 4px;")

        group_layout.addWidget(self.seq_radio)
        group_layout.addWidget(self.sim_radio)
        group_layout.addWidget(note)
        layout.addWidget(group)

        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        save_btn = QtWidgets.QPushButton("Save")
        cancel_btn = QtWidgets.QPushButton("Cancel")
        save_btn.clicked.connect(self._save)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _save(self):
        self.settings["simultaneous_download"] = self.sim_radio.isChecked()
        save_settings(self.settings)
        self.accept()

    def get_settings(self):
        return self.settings


class URLExportWorker(QtCore.QThread):
    """Resolves all links to real CDN URLs and writes them to output_links.txt."""
    log_signal = QtCore.pyqtSignal(str)
    finished_signal = QtCore.pyqtSignal(str)  # path to output file

    def __init__(self, links, parent=None):
        super().__init__(parent)
        self.links = links
        self.active = True

    def stop(self):
        self.active = False
        self.terminate()

    def run(self):
        self.log_signal.emit(f"🔍 Resolving {len(self.links)} URLs for FDM export...")
        resolved_urls = []

        def resolve(link):
            try:
                _, cdn_url = resolve_cdn_url(link)
                return cdn_url
            except Exception as e:
                self.log_signal.emit(f"❌ Failed: {link[:60]}\n   {e}")
                return None

        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(resolve, lnk): lnk for lnk in self.links}
            for fut in as_completed(futs):
                if not self.active:
                    break
                cdn = fut.result()
                if cdn:
                    resolved_urls.append(cdn)
                    self.log_signal.emit(f"✅ Resolved: {cdn[:70]}...")

        output_path = os.path.join(os.path.abspath('.'), 'output_links.txt')
        with open(output_path, 'w') as f:
            f.write('\n'.join(resolved_urls) + '\n')

        self.log_signal.emit(
            f"📄 Saved {len(resolved_urls)}/{len(self.links)} URLs → output_links.txt\n"
            f"   Import this file into Free Download Manager."
        )
        self.finished_signal.emit(output_path)


class MainWindow(QtWidgets.QMainWindow):
    """
    Main application window for the downloader.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Fucking Fast Downloader")
        self.resize(850, 600)
        self.setStatusBar(QtWidgets.QStatusBar(self))  # For transient notifications

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QVBoxLayout(central)

        # Determine base path for resources.
        self.base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))

        try:
            icon_path = os.path.join(self.base_path, "icons", "fuckingfast.ico")
            self.setWindowIcon(QtGui.QIcon(icon_path))
        except Exception as e:
            print(f"Error loading icon: {e}")

        # Set the default application font.
        nice_font = "Roboto" if "Roboto" in QFontDatabase().families() else "Segoe UI"
        QtWidgets.QApplication.setFont(QFont(nice_font, 10))

        self.settings = load_settings()

        # Top buttons.
        top_button_layout = QtWidgets.QHBoxLayout()
        self.load_btn = QtWidgets.QPushButton("Load Links")
        self.download_btn = QtWidgets.QPushButton("Download All")
        self.export_fdm_btn = QtWidgets.QPushButton("📋 Export URLs for FDM")
        self.export_fdm_btn.setObjectName("export_fdm_btn")
        self.export_fdm_btn.setToolTip(
            "Resolve all links to real CDN URLs and save to output_links.txt.\n"
            "Then import that file into Free Download Manager."
        )
        self.settings_btn = QtWidgets.QPushButton("⚙️ Settings")
        self.settings_btn.setObjectName("settings_btn")
        top_button_layout.addWidget(self.load_btn)
        top_button_layout.addWidget(self.download_btn)
        top_button_layout.addWidget(self.export_fdm_btn)
        top_button_layout.addWidget(self.settings_btn)
        main_layout.addLayout(top_button_layout)

        # Main content layout.
        content_layout = QtWidgets.QHBoxLayout()
        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setToolTip("List of download links. Double-click an item to copy the link.")
        content_layout.addWidget(self.list_widget, 1)
        self.list_widget.itemDoubleClicked.connect(self.copy_link_to_clipboard)

        # Right-side layout for progress and logs.
        right_layout = QtWidgets.QVBoxLayout()
        self.file_label = QtWidgets.QLabel("📁 Current File: None")
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setFormat("%v / %m bytes")

        pause_resume_layout = QtWidgets.QHBoxLayout()
        self.pause_btn = QtWidgets.QPushButton("▶ Pause")
        self.pause_btn.setObjectName("pause_btn")
        self.resume_btn = QtWidgets.QPushButton("⏸ Resume")
        self.resume_btn.setObjectName("resume_btn")
        pause_resume_layout.addWidget(self.pause_btn)
        pause_resume_layout.addWidget(self.resume_btn)

        self.status_label = QtWidgets.QLabel("🟢 Status: Idle")
        self.status_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #4CAF50;")

        self.progress_detail_label = QtWidgets.QLabel(
            "⬇️ Downloaded: 0.00 MB\n"
            "📦 Total: 0.00 MB\n"
            "⏳ Remaining: 0.00 MB"
        )
        self.progress_detail_label.setStyleSheet("font-weight: 500;")

        self.speed_label = QtWidgets.QLabel("🚀 Speed: 0.00 KB/s")
        self.speed_label.setStyleSheet("font-weight: 500; color: #FF5722;")

        self.log_text = QtWidgets.QTextEdit()
        self.log_text.setReadOnly(True)
        # Enable rich text for HTML content.
        self.log_text.setAcceptRichText(True)
        self.log_text.setFont(QtGui.QFont("Segoe UI", 12))

        right_layout.addWidget(self.file_label)
        right_layout.addWidget(self.progress_bar)
        right_layout.addLayout(pause_resume_layout)
        right_layout.addWidget(self.progress_detail_label)
        right_layout.addWidget(self.speed_label)
        right_layout.addWidget(self.status_label)
        right_layout.addWidget(self.log_text, 1)
        content_layout.addLayout(right_layout, 2)
        main_layout.addLayout(content_layout)

        # Bottom layout for support buttons.
        self.github_button = QtWidgets.QPushButton()
        github_icon = os.path.join(self.base_path, "icons", "github.png")
        self.github_button.setIcon(QtGui.QIcon(github_icon))
        self.github_button.setIconSize(QtCore.QSize(64, 64))
        self.github_button.setToolTip("View Source Code on Github 🐙")
        self.github_button.setStyleSheet("""
            QPushButton {
                border: none;
                margin: 10px;
                padding: 5px 0;
                background-color: transparent;
            }
            QPushButton:hover { background-color: rgba(255, 255, 255, 0.1); }
        """)
        self.github_button.clicked.connect(
            lambda: webbrowser.open("https://github.com/Riteshp2001/Fucking-Fast-Downloader")
        )

        self.buymecoffee_button = QtWidgets.QPushButton()
        buymecoffee_icon = os.path.join(self.base_path, "icons", "buymecoffee.png")
        self.buymecoffee_button.setIcon(QtGui.QIcon(buymecoffee_icon))
        self.buymecoffee_button.setIconSize(QtCore.QSize(64, 64))
        self.buymecoffee_button.setToolTip("Just Buy me a Coffee ☕ Already !!")
        self.buymecoffee_button.setStyleSheet("""
            QPushButton {
                border: none;
                margin: 10px;
                padding: 5px 0;
                background-color: transparent;
            }
            QPushButton:hover { background-color: rgba(255, 255, 255, 0.1); }
        """)
        self.buymecoffee_button.clicked.connect(
            lambda: webbrowser.open("https://buymeacoffee.com/riteshp2001/e/367661")
        )

        self.support = QtWidgets.QLabel(
            "Support My Work on Buy Me a Coffee & Check Out What I've Been Up To on Github! 🫡"
        )
        self.support.setAlignment(Qt.AlignCenter)
        self.support.setStyleSheet("font-size: 14px; font-weight: bold; margin-top: 10px;")

        bottom_layout = QtWidgets.QHBoxLayout()
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.github_button)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.support)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.buymecoffee_button)
        bottom_layout.addStretch()
        main_layout.addLayout(bottom_layout)

        self.credits_label = QtWidgets.QLabel(
            "Made with <span style='color: #FF6347; font-weight: bold;'>❤️</span> by "
            "<a style='color: #1E90FF; text-decoration: none;' href='https://riteshpandit.vercel.app'>Ritesh Pandit</a>"
        )
        self.credits_label.setOpenExternalLinks(True)
        self.credits_label.setAlignment(Qt.AlignCenter)
        self.credits_label.setStyleSheet("font-size: 14px; font-weight: bold; margin-top: 10px;")
        main_layout.addWidget(self.credits_label)

        # Set cursors for interactive elements.
        self.load_btn.setCursor(Qt.PointingHandCursor)
        self.download_btn.setCursor(Qt.PointingHandCursor)
        self.export_fdm_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.pause_btn.setCursor(Qt.PointingHandCursor)
        self.resume_btn.setCursor(Qt.PointingHandCursor)
        self.github_button.setCursor(Qt.PointingHandCursor)
        self.buymecoffee_button.setCursor(Qt.PointingHandCursor)
        self.list_widget.setCursor(Qt.ArrowCursor)

        # Application-wide stylesheet.
        self.setStyleSheet("""
            QPushButton {
                background-color: #2B579A;
                color: white;
                border: 1px solid #1D466B;
                border-radius: 4px;
                padding: 8px 16px;
                margin: 2px;
            }
            QPushButton:hover {
                background-color: #3C6AAA;
                border: 1px solid #2B579A;
            }
            QPushButton:pressed { background-color: #1D466B; }
            QPushButton#pause_btn { background-color: #FF5722; }
            QPushButton#pause_btn:hover { background-color: #FF7043; }
            QPushButton#resume_btn { background-color: #4CAF50; }
            QPushButton#resume_btn:hover { background-color: #66BB6A; }
            QPushButton#export_fdm_btn { background-color: #7B2FBE; }
            QPushButton#export_fdm_btn:hover { background-color: #9B4FDE; }
            QPushButton#export_fdm_btn:disabled { background-color: #4A1F7A; color: #888; }
            QPushButton#settings_btn { background-color: #455A64; }
            QPushButton#settings_btn:hover { background-color: #607D8B; }
            QListWidget {
                background-color: #1E1E1E;
                color: #FFFFFF;
                border: 1px solid #3C3C3C;
                border-radius: 4px;
            }
            QListWidget::item:hover { background-color: #3C3C3C; }
            QListWidget::item:selected { background-color: #2B579A; }
            QProgressBar {
                border: 1px solid #3C3C3C;
                border-radius: 4px;
                text-align: center;
                background-color: #1E1E1E;
            }
            QProgressBar::chunk {
                background-color: #2B579A;
                border-radius: 4px;
            }
            QTextEdit {
                background-color: #1E1E1E;
                color: #FFFFFF;
                border: 1px solid #3C3C3C;
                border-radius: 4px;
            }
            QLabel { color: #FFFFFF; }
        """)

        # Connect button signals.
        self.load_btn.clicked.connect(self.load_links)
        self.download_btn.clicked.connect(self.download_all)
        self.export_fdm_btn.clicked.connect(self.export_for_fdm)
        self.settings_btn.clicked.connect(self.open_settings)
        self.pause_btn.clicked.connect(self.pause_download)
        self.resume_btn.clicked.connect(self.resume_download)

        self.worker = None
        self.url_export_worker = None

    def load_links(self):
        if not os.path.exists(INPUT_FILE):
            with open(INPUT_FILE, 'w') as f:
                f.write("# Add download links here (remove this line and add links only)\n")
            QtWidgets.QMessageBox.information(self, "Info", f"Input file '{INPUT_FILE}' not found. It has been created.")
            return

        self.list_widget.clear()
        with open(INPUT_FILE, 'r') as f:
            links = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]
        for idx, link in enumerate(links, start=1):
            self.list_widget.addItem(f"{idx}. {link}")
        self.log(f"Loaded {len(links)} link(s) from {INPUT_FILE}")

    def copy_link_to_clipboard(self, item):
        parts = item.text().split(". ", 1)
        link = parts[1] if len(parts) == 2 else item.text()
        QtWidgets.QApplication.clipboard().setText(link)
        self.statusBar().showMessage("Link copied to clipboard", 2000)

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        colored_message = colorize_log_message(message)
        self.log_text.append(f"<p style='font-weight:600; font-family: \"Segoe UI\"; font-size:12px;'><span style='color:gray;'>[{timestamp}]</span> {colored_message}</p>")

    def download_all(self):
        # Stop any existing worker and start a new one.    
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
        links = []
        for i in range(self.list_widget.count()):
            item_text = self.list_widget.item(i).text()
            parts = item_text.split(". ", 1)
            links.append(parts[1] if len(parts) == 2 else item_text)

        if not links:
            QtWidgets.QMessageBox.information(self, "Info", "No links to download.")
            return

        simultaneous = self.settings.get("simultaneous_download", False)
        mode_label = "simultaneous" if simultaneous else "sequential"
        self.log(f"📋 Download mode: {mode_label}")
        self.worker = DownloaderWorker(links, simultaneous=simultaneous)
        self.worker.log_signal.connect(self.log)
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.file_signal.connect(self.update_file)
        self.worker.status_signal.connect(self.update_status)
        self.worker.speed_signal.connect(self.update_speed)
        self.worker.link_removed_signal.connect(self.remove_link_from_list)
        self.worker.link_failed_signal.connect(self.mark_link_failed)  # Connect the failure signal
        self.worker.start()
        # Add error handling connection
        # self.worker.error_signal.connect(self.handle_critical_error)

    def pause_download(self):
        if self.worker and self.worker.isRunning():
            self.worker.pause()

    def resume_download(self):
        if self.worker and self.worker.isRunning():
            self.worker.resume_download()

    def update_progress(self, downloaded, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(downloaded)
        # Convert bytes to megabytes using floating-point division
        downloaded_mb = downloaded / (1024 * 1024)
        total_mb = total / (1024 * 1024)
        # Ensure remaining value doesn't go negative
        remaining_mb = max(total_mb - downloaded_mb, 0)
        self.progress_detail_label.setText(
            f"<b>Download Progress</b><br>"
            f"⬇️ <span style='color:#1E90FF;'>Downloaded:</span> {downloaded_mb} MB<br>"
            f"📦 <span style='color:#32CD32;'>Total:</span> {total_mb} MB<br>"
            f"⏳ <span style='color:#FFD700;'>Remaining:</span> {remaining_mb} MB"
            f"</div>"
        )


    def handle_critical_error(self, message):
        QtWidgets.QMessageBox.critical(
            self, 
            "Critical Error", 
            f"Application will stop:\n{message}"
        )
        if self.worker:
            self.worker.stop()

    def open_settings(self):
        dialog = SettingsDialog(self.settings, parent=self)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            self.settings = dialog.get_settings()
            mode = "simultaneous" if self.settings.get("simultaneous_download") else "sequential"
            self.log(f"⚙️ Settings saved — download mode: {mode}")

    def export_for_fdm(self):
        links = []
        for i in range(self.list_widget.count()):
            text = self.list_widget.item(i).text()
            parts = text.split(". ", 1)
            links.append(parts[1] if len(parts) == 2 else text)

        if not links:
            QtWidgets.QMessageBox.information(self, "Info", "No links loaded.")
            return

        if self.url_export_worker and self.url_export_worker.isRunning():
            self.url_export_worker.stop()
            self.url_export_worker.wait()

        self.export_fdm_btn.setEnabled(False)
        self.export_fdm_btn.setText("⏳ Resolving URLs...")

        self.url_export_worker = URLExportWorker(links)
        self.url_export_worker.log_signal.connect(self.log)
        self.url_export_worker.finished_signal.connect(self._on_export_done)
        self.url_export_worker.start()

    def _on_export_done(self, output_path):
        self.export_fdm_btn.setEnabled(True)
        self.export_fdm_btn.setText("📋 Export URLs for FDM")
        QtWidgets.QMessageBox.information(
            self,
            "Export Complete",
            f"URLs saved to:\n{output_path}\n\n"
            "In Free Download Manager:\n"
            "  Import → From a text file → select output_links.txt"
        )

    def closeEvent(self, event):
        """Cleanup on window close"""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        if self.url_export_worker and self.url_export_worker.isRunning():
            self.url_export_worker.stop()
            self.url_export_worker.wait(3000)
        event.accept()

    def update_file(self, filename):
        self.file_label.setText(f"📁 Current File: {filename}")

    def update_status(self, status):
        self.status_label.setText(f"Status: {status}")

    def update_speed(self, speed_mb):
        """Handle speed updates with proper unit formatting"""
        if speed_mb >= 1.0:
            self.speed_label.setText(f"🚀 Speed: {speed_mb:.1f} MB/s")
        else:
            speed_kb = speed_mb * 1024
            self.speed_label.setText(f"🚀 Speed: {speed_kb:.0f} KB/s")


    def remove_link_from_list(self, link):
        for i in range(self.list_widget.count()):
            item_text = self.list_widget.item(i).text()
            if item_text.split(". ", 1)[-1] == link:
                self.list_widget.takeItem(i)
                break
        if os.path.exists(INPUT_FILE):
            with open(INPUT_FILE, 'r') as f:
                lines = f.readlines()
            with open(INPUT_FILE, 'w') as f:
                for line in lines:
                    if line.strip() != link:
                        f.write(line)

    def mark_link_failed(self, link):
        """
        Change the color of the link in the list widget to red if it fails after 3 attempts.
        """
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            parts = item.text().split(". ", 1)
            if len(parts) == 2 and parts[1] == link:
                # Change the text color to red
                item.setForeground(QtGui.QColor("red"))
                break

# --------------------- End of GUI Code ---------------------

def main():
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)
    app = QtWidgets.QApplication(sys.argv)
    default_font = QFont("Roboto" if "Roboto" in QFontDatabase().families() else "Segoe UI", 10)
    app.setFont(default_font)
    apply_stylesheet(app, theme='dark_blue.xml')
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
