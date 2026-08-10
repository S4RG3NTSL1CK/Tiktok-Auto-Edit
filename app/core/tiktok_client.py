import hashlib
import http.server
import math
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlparse, parse_qs

import requests

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
INBOX_UPLOAD_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
STATUS_FETCH_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"

# Fixed so the redirect URI you register in your TikTok developer app never
# changes. TikTok's desktop OAuth flow explicitly supports a 127.0.0.1
# redirect (unlike most of their other flows, which require public HTTPS).
REDIRECT_PORT = 58642
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
SCOPES = "video.upload,user.info.basic"

MAX_STANDARD_CHUNK = 64 * 1024 * 1024
DEFAULT_CHUNK_SIZE = 10 * 1024 * 1024


class TikTokError(RuntimeError):
    pass


@dataclass
class TikTokTokens:
    access_token: str
    refresh_token: str
    open_id: str
    expires_at: float  # absolute unix timestamp, with a safety buffer already subtracted

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at


def generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)[:128]


def code_challenge_from_verifier(verifier: str) -> str:
    # TikTok's desktop OAuth docs explicitly specify hex-encoded SHA256 here,
    # not the base64url encoding standard PKCE (RFC 7636) normally uses.
    return hashlib.sha256(verifier.encode("utf-8")).hexdigest()


def build_authorize_url(client_key: str, state: str, code_challenge: str) -> str:
    params = {
        "client_key": client_key,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _parse_token_response(resp: requests.Response) -> TikTokTokens:
    if resp.status_code != 200:
        raise TikTokError(f"TikTok token request failed: HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if data.get("error"):
        raise TikTokError(f"TikTok token error: {data.get('error_description', data['error'])}")
    if "access_token" not in data:
        raise TikTokError(f"Unexpected TikTok token response: {data}")
    return TikTokTokens(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", ""),
        open_id=data.get("open_id", ""),
        expires_at=time.time() + float(data.get("expires_in", 0)) - 60,
    )


def exchange_code_for_token(client_key: str, client_secret: str, code: str, code_verifier: str) -> TikTokTokens:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    return _parse_token_response(resp)


def refresh_access_token(client_key: str, client_secret: str, refresh_token: str) -> TikTokTokens:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    return _parse_token_response(resp)


def _compute_chunks(video_size: int):
    if video_size <= MAX_STANDARD_CHUNK:
        return video_size, 1
    chunk_size = DEFAULT_CHUNK_SIZE
    total_chunk_count = math.ceil(video_size / chunk_size)
    return chunk_size, total_chunk_count


def upload_video_to_inbox(access_token: str, video_path: str, progress_cb=None) -> str:
    """Uploads a video to the connected TikTok account's inbox as a draft —
    it does NOT publish anything. The user has to open TikTok themselves to
    review and post it. Returns TikTok's publish_id."""
    video_size = Path(video_path).stat().st_size
    chunk_size, total_chunk_count = _compute_chunks(video_size)

    init_resp = requests.post(
        INBOX_UPLOAD_INIT_URL,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
        json={"source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunk_count,
        }},
        timeout=30,
    )
    if init_resp.status_code != 200:
        raise TikTokError(f"TikTok upload init failed: HTTP {init_resp.status_code}: {init_resp.text[:300]}")
    init_data = init_resp.json()
    error = init_data.get("error") or {}
    if error.get("code") not in (None, "ok"):
        raise TikTokError(f"TikTok upload init error: {error.get('message', error.get('code'))}")

    publish_id = init_data["data"]["publish_id"]
    upload_url = init_data["data"]["upload_url"]

    with open(video_path, "rb") as f:
        for i in range(total_chunk_count):
            start = i * chunk_size
            f.seek(start)
            chunk_bytes = f.read(chunk_size)
            end = start + len(chunk_bytes) - 1
            put_resp = requests.put(
                upload_url,
                data=chunk_bytes,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes {start}-{end}/{video_size}",
                },
                timeout=120,
            )
            if put_resp.status_code not in (200, 201, 206):
                raise TikTokError(f"TikTok chunk upload failed: HTTP {put_resp.status_code}: {put_resp.text[:300]}")
            if progress_cb:
                progress_cb(i + 1, total_chunk_count)

    return publish_id


def get_display_name(access_token: str) -> str:
    resp = requests.get(
        USER_INFO_URL,
        params={"fields": "display_name"},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    if resp.status_code != 200:
        return ""
    data = resp.json()
    return ((data.get("data") or {}).get("user") or {}).get("display_name", "")


def check_publish_status(access_token: str, publish_id: str) -> dict:
    resp = requests.post(
        STATUS_FETCH_URL,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
        json={"publish_id": publish_id},
        timeout=15,
    )
    if resp.status_code != 200:
        raise TikTokError(f"TikTok status check failed: HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    error = data.get("error") or {}
    if error.get("code") not in (None, "ok"):
        raise TikTokError(f"TikTok status check error: {error.get('message', error.get('code'))}")
    return data.get("data", {})


class _CallbackServer(http.server.HTTPServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.callback_result = None


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = parse_qs(parsed.query)
        self.server.callback_result = {
            "code": params.get("code", [None])[0],
            "state": params.get("state", [None])[0],
            "error": params.get("error", [None])[0],
        }
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body style='font-family: sans-serif; padding: 2em;'>"
            b"<h2>Tiktok Auto Edit</h2><p>Login complete. You can close this tab "
            b"and return to the app.</p></body></html>"
        )

    def log_message(self, format, *args):
        pass  # silence default request logging to stderr


def wait_for_oauth_callback(timeout: float = 180.0) -> dict:
    """Starts a local server on 127.0.0.1:REDIRECT_PORT and blocks until
    TikTok redirects back to it (or the timeout elapses). Returns
    {"code": ..., "state": ...}. Raises TikTokError on timeout, the port
    being unavailable, or TikTok reporting the user denied access."""
    try:
        server = _CallbackServer(("127.0.0.1", REDIRECT_PORT), _CallbackHandler)
    except OSError as exc:
        raise TikTokError(
            f"Could not start the local login server on port {REDIRECT_PORT}: {exc}. "
            "Something else may already be using that port."
        ) from exc

    server.timeout = timeout
    try:
        server.handle_request()
    finally:
        server.server_close()

    result = server.callback_result
    if result is None:
        raise TikTokError("Timed out waiting for TikTok login. Please try again.")
    if result.get("error"):
        raise TikTokError(f"TikTok login was not completed: {result['error']}")
    if not result.get("code"):
        raise TikTokError("TikTok redirected back without an authorization code.")
    return result
