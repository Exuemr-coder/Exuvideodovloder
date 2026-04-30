import os
import re
import shutil
import tempfile
import threading
from urllib.parse import urlparse

from flask import Flask, render_template, request, send_file, jsonify, after_this_request, Response
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True


@app.after_request
def _no_cache_html(resp):
    ct = (resp.headers.get("Content-Type") or "").lower()
    if "text/html" in ct or "application/manifest" in ct:
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


def _is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def _safe_filename(name: str) -> str:
    name = re.sub(r"[^\w\-. ]+", "_", name).strip()
    return name or "video"


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/manifest.webmanifest", methods=["GET"])
def manifest():
    data = {
        "name": "EXUEMR // Video Grabber",
        "short_name": "EXUEMR",
        "description": "Hızlı ve sessiz video indirici by Exuemr.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#05070a",
        "theme_color": "#00ff88",
        "lang": "tr",
        "icons": [
            {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any maskable"},
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"}
        ]
    }
    return jsonify(data), 200, {"Content-Type": "application/manifest+json"}


_ICON_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512'>
  <defs>
    <radialGradient id='g' cx='50%' cy='40%' r='65%'>
      <stop offset='0%' stop-color='#0a1410'/>
      <stop offset='100%' stop-color='#02060a'/>
    </radialGradient>
    <linearGradient id='t' x1='0' y1='0' x2='0' y2='1'>
      <stop offset='0%' stop-color='#aaffd0'/>
      <stop offset='60%' stop-color='#00ff88'/>
      <stop offset='100%' stop-color='#008f57'/>
    </linearGradient>
    <filter id='glow'>
      <feGaussianBlur stdDeviation='6' result='b'/>
      <feMerge><feMergeNode in='b'/><feMergeNode in='SourceGraphic'/></feMerge>
    </filter>
  </defs>
  <rect width='512' height='512' rx='96' fill='url(#g)'/>
  <rect x='14' y='14' width='484' height='484' rx='86' fill='none' stroke='#00ff88' stroke-opacity='0.35' stroke-width='3'/>
  <g font-family='JetBrains Mono, Menlo, Consolas, monospace' font-weight='800' text-anchor='middle' filter='url(#glow)'>
    <text x='256' y='305' font-size='220' fill='url(#t)' letter-spacing='10'>EX</text>
  </g>
  <g fill='#00ff88' opacity='0.85'>
    <rect x='80' y='420' width='10' height='30'/>
    <rect x='100' y='420' width='10' height='30' opacity='0.6'/>
    <rect x='120' y='420' width='10' height='30' opacity='0.3'/>
    <rect x='402' y='420' width='30' height='10'/>
    <rect x='402' y='405' width='20' height='10' opacity='0.6'/>
    <rect x='402' y='390' width='10' height='10' opacity='0.3'/>
  </g>
</svg>"""


@app.route("/icon.svg", methods=["GET"])
def icon_svg():
    return Response(_ICON_SVG, mimetype="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.route("/icon-192.png", methods=["GET"])
@app.route("/icon-512.png", methods=["GET"])
def icon_png_redirect():
    return Response(_ICON_SVG, mimetype="image/svg+xml")


@app.route("/sw.js", methods=["GET"])
def service_worker():
    js = """
const CACHE = 'exuemr-grabber-v1';
const ASSETS = ['/', '/icon.svg', '/manifest.webmanifest'];
self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).catch(()=>{}));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(self.clients.claim());
});
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.pathname === '/download' || url.pathname === '/info') return;
  e.respondWith(
    fetch(req).then(r => {
      const copy = r.clone();
      caches.open(CACHE).then(c => c.put(req, copy)).catch(()=>{});
      return r;
    }).catch(() => caches.match(req).then(r => r || caches.match('/')))
  );
});
"""
    return Response(js, mimetype="application/javascript",
                    headers={"Cache-Control": "no-cache"})


@app.route("/info", methods=["POST"])
def info():
    url = (request.form.get("url") or "").strip()
    if not _is_valid_url(url):
        return jsonify({"error": "Please enter a valid http(s) URL."}), 400

    try:
        with YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
            data = ydl.extract_info(url, download=False)
    except DownloadError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"Could not fetch info: {e}"}), 500

    return jsonify({
        "title": data.get("title"),
        "uploader": data.get("uploader") or data.get("channel"),
        "duration": data.get("duration"),
        "thumbnail": data.get("thumbnail"),
        "webpage_url": data.get("webpage_url") or url,
    })


@app.route("/download", methods=["POST"])
def download():
    url = (request.form.get("url") or "").strip()
    quality = (request.form.get("quality") or "best").strip()
    audio_only = request.form.get("audio_only") == "on"

    if not _is_valid_url(url):
        return jsonify({"error": "Please enter a valid http(s) URL."}), 400

    tmpdir = tempfile.mkdtemp(prefix="ytdlp_")
    outtmpl = os.path.join(tmpdir, "%(title).200B [%(id)s].%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": False,
        "merge_output_format": "mp4",
    }

    if audio_only:
        ydl_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
    else:
        if quality == "best":
            ydl_opts["format"] = "bv*+ba/b"
        elif quality.isdigit():
            h = int(quality)
            ydl_opts["format"] = f"bv*[height<={h}]+ba/b[height<={h}]"
        else:
            ydl_opts["format"] = "bv*+ba/b"

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            filepath = ydl.prepare_filename(info_dict)
            if audio_only:
                base, _ = os.path.splitext(filepath)
                filepath = base + ".mp3"
            elif not os.path.exists(filepath):
                base, _ = os.path.splitext(filepath)
                for ext in (".mp4", ".mkv", ".webm"):
                    if os.path.exists(base + ext):
                        filepath = base + ext
                        break
    except DownloadError as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({"error": f"Download failed: {e}"}), 500

    if not os.path.exists(filepath):
        shutil.rmtree(tmpdir, ignore_errors=True)
        return jsonify({"error": "Download finished but file was not found."}), 500

    download_name = _safe_filename(os.path.basename(filepath))

    @after_this_request
    def _cleanup(response):
        def _later():
            shutil.rmtree(tmpdir, ignore_errors=True)
        threading.Timer(5.0, _later).start()
        return response

    return send_file(filepath, as_attachment=True, download_name=download_name)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
