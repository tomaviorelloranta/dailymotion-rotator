#!/usr/bin/env python3
"""Upload video.mp4 to Dailymotion using API v2, publish it, and rotate redirect."""

from __future__ import annotations

import logging
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent
TOKEN_URL = "https://oauth2.dailymotion.com/v2/token"
API_BASE = "https://api.dailymotion.com"
VIDEO_FILE = ROOT / "video.mp4"
COUNTER_FILE = ROOT / "counter.txt"
LAST_ID_FILE = ROOT / "last_id.txt"
REDIRECT_FILE = ROOT / "redirect.txt"
TIMEOUT = (15, 120)
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9]+$")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("dailymotion-rotator")


class RotationError(RuntimeError):
    """A failure in the rotation process."""


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RotationError(f"Required environment variable {name} is not set")
    return value


def make_session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=3,
        status=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "DELETE"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def checked_json(response: requests.Response, operation: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        body = response.text[:1000].replace("\n", " ")
        raise RotationError(
            f"{operation} failed with HTTP {response.status_code}: {body}"
        ) from exc
    try:
        result = response.json()
    except requests.exceptions.JSONDecodeError as exc:
        raise RotationError(f"{operation} returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise RotationError(f"{operation} returned an unexpected response")
    if result.get("error"):
        raise RotationError(f"{operation} returned API error: {result['error']}")
    return result


def read_counter() -> int:
    try:
        raw = COUNTER_FILE.read_text(encoding="utf-8").strip()
        value = int(raw)
    except (OSError, ValueError) as exc:
        raise RotationError(f"Could not read integer from {COUNTER_FILE.name}") from exc
    if value < 1:
        raise RotationError("counter.txt must contain a positive integer")
    return value


def read_previous_id() -> str:
    try:
        value = LAST_ID_FILE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RotationError(f"Could not read {LAST_ID_FILE.name}") from exc
    if value and not VIDEO_ID_RE.fullmatch(value):
        raise RotationError("last_id.txt contains an invalid Dailymotion video ID")
    return value


def atomic_write(path: Path, value: str) -> None:
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=ROOT,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as temp:
            temp.write(value)
            temp.flush()
            os.fsync(temp.fileno())
            temp_name = temp.name
        os.replace(temp_name, path)
    except OSError as exc:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        raise RotationError(f"Could not update {path.name}: {exc}") from exc


def get_access_token(session: requests.Session) -> str:
    LOG.info("Cer token nou prin OAuth v2 client_credentials...")
    payload = {
        "grant_type": "client_credentials",
        "client_id": required_env("DM_API_KEY"),
        "client_secret": required_env("DM_API_SECRET"),
    }
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            response = session.post(TOKEN_URL, data=payload, timeout=TIMEOUT)
            data = checked_json(response, "OAuth token request")
            token = data.get("access_token")
            if not isinstance(token, str) or not token:
                raise RotationError("OAuth response did not include access_token")
            LOG.info("Token OAuth v2 obtinut cu succes.")
            return token
        except (requests.RequestException, RotationError) as exc:
            last_error = exc
            if attempt == 3:
                break
            delay = min(2**attempt, 8)
            time.sleep(delay)
    raise RotationError(f"OAuth token request failed after retries: {last_error}")


def upload_video(session: requests.Session, token: str) -> str:
    if not VIDEO_FILE.is_file():
        raise RotationError("video.mp4 is missing; place the video beside rotatie.py")
    if VIDEO_FILE.stat().st_size == 0:
        raise RotationError("video.mp4 is empty")

    headers = {"Authorization": f"Bearer {token}"}
    response = session.post(f"{API_BASE}/v2/files/upload_sessions", headers=headers, timeout=TIMEOUT)
    upload_info = checked_json(response, "Upload URL request (V2)")
    upload_url = upload_info.get("upload_url")
    if not isinstance(upload_url, str) or not upload_url.startswith("https://"):
        raise RotationError("Dailymotion did not return a valid HTTPS upload_url")

    LOG.info("Uploadez fisierul binar pe Dailymotion CDN...")
    try:
        with VIDEO_FILE.open("rb") as video:
            upload_response = session.post(
                upload_url,
                files={"file": (VIDEO_FILE.name, video, "video/mp4")},
                timeout=TIMEOUT,
            )
    except requests.RequestException as exc:
        raise RotationError(f"Video file upload failed: {exc}") from exc
    upload_result = checked_json(upload_response, "Video file upload")
    source_url = upload_result.get("url")
    if not isinstance(source_url, str) or not source_url.startswith("https://"):
        raise RotationError("Upload response did not include a valid HTTPS video URL")
    return source_url


def get_profile_id(session: requests.Session, token: str) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = session.get(f"{API_BASE}/v2/me", headers=headers, timeout=TIMEOUT)
        data = checked_json(r, "Get profile ID")
        profiles = data.get("profiles", [])
        if profiles and isinstance(profiles, list) and "id" in profiles[0]:
            return profiles[0]["id"]
    except Exception:
        pass
    return "x1xakj1"


def publish_video(session: requests.Session, token: str, source_url: str, number: int) -> str:
    profile_id = get_profile_id(session, token)
    LOG.info("Public videoul pe profilul %s...", profile_id)

    payload = {
        "title": f"Video {number}",
        "visibility": "public",
        "category": "news",
        "is_for_kids": False,
        "source": {
            "file_url": source_url
        },
        "file_url": source_url,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        response = session.post(
            f"{API_BASE}/v2/profiles/{profile_id}/videos",
            json=payload,
            headers=headers,
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise RotationError(f"Video creation request failed: {exc}") from exc
    
    result = checked_json(response, "Video creation (V2)")
    LOG.info("Raspuns Dailymotion la creare: %s", result)

    # In v2, ID-ul poate fi in 'id', 'xid' sau 'video_id'
    video_id = result.get("id") or result.get("xid") or result.get("video_id")
    
    # Daca e un dictionar imbricat (ex: {'data': {'id': ...}})
    if not video_id and isinstance(result.get("data"), dict):
        video_id = result["data"].get("id") or result["data"].get("xid")

    if not video_id:
        raise RotationError(f"Nu am gasit ID-ul in raspuns: {result}")
        
    return str(video_id).strip()


def delete_previous(session: requests.Session, token: str, previous_id: str, new_id: str) -> None:
    if not previous_id or previous_id == new_id:
        return
    try:
        response = session.delete(
            f"{API_BASE}/v2/videos/{previous_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=TIMEOUT,
        )
        if response.status_code in (200, 204):
            LOG.info("Deleted previous Dailymotion video %s", previous_id)
        else:
            response.raise_for_status()
    except (requests.RequestException, RotationError) as exc:
        LOG.warning("Could not delete previous video %s: %s", previous_id, exc)


def main() -> int:
    number = read_counter()
    previous_id = read_previous_id()
    session = make_session()
    try:
        token = get_access_token(session)
        source_url = upload_video(session, token)
        new_id = publish_video(session, token, source_url, number)
        canonical_url = f"https://www.dailymotion.com/video/{new_id}"

        atomic_write(REDIRECT_FILE, canonical_url + "\n")
        atomic_write(LAST_ID_FILE, new_id + "\n")
        atomic_write(COUNTER_FILE, f"{number + 1}\n")
        LOG.info("Published video %s and updated redirect.txt", new_id)
        delete_previous(session, token, previous_id, new_id)
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RotationError as exc:
        LOG.error("Rotation failed: %s", exc)
        raise SystemExit(1) from exc
