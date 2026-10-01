import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import httpx


class MetaError(RuntimeError):
    pass


@dataclass
class MetaPage:
    id: str
    name: str


@dataclass
class MetaPublishResult:
    post_id: str
    post_url: str | None = None


def graph_base(version: str) -> str:
    normalized = version.strip().lstrip("/")
    if not normalized:
        raise MetaError("Graph API version is required in System Configuration")
    if not normalized.startswith("v"):
        normalized = f"v{normalized}"
    return f"https://graph.facebook.com/{normalized}"


def verify_page(page_id: str, access_token: str, version: str) -> MetaPage:
    try:
        response = httpx.get(
            f"{graph_base(version)}/{page_id}",
            params={"fields": "id,name", "access_token": access_token},
            timeout=20.0,
        )
    except httpx.HTTPError as exc:
        raise MetaError(f"Unable to reach Meta: {exc}") from exc
    payload = _json(response)
    if response.is_error:
        raise MetaError(_meta_message(payload, response.status_code))
    return MetaPage(id=str(payload.get("id") or page_id), name=str(payload.get("name") or "Facebook Page"))


def publish_campaign(
    *,
    page_id: str,
    access_token: str,
    version: str,
    message: str,
    media_url: str | None,
    destination_url: str | None,
) -> MetaPublishResult:
    if media_url:
        content_type = mimetypes.guess_type(media_url.split("?", 1)[0])[0] or ""
        if content_type.startswith("image/"):
            return _publish_photo(page_id, access_token, version, message, media_url)
        if content_type.startswith("video/"):
            return _publish_video(page_id, access_token, version, message, media_url)
    return _publish_feed(page_id, access_token, version, message, destination_url)


def _publish_feed(page_id: str, token: str, version: str, message: str, link: str | None) -> MetaPublishResult:
    data = {"message": message, "access_token": token}
    if link:
        data["link"] = link
    response = httpx.post(f"{graph_base(version)}/{page_id}/feed", data=data, timeout=30.0)
    payload = _json(response)
    if response.is_error:
        raise MetaError(_meta_message(payload, response.status_code))
    post_id = str(payload.get("id") or "")
    if not post_id:
        raise MetaError("Meta accepted the request but returned no post id")
    return MetaPublishResult(post_id=post_id, post_url=_post_url(post_id))


def _publish_photo(page_id: str, token: str, version: str, message: str, media_url: str) -> MetaPublishResult:
    public_url = _public_media_url(media_url)
    response = httpx.post(
        f"{graph_base(version)}/{page_id}/photos",
        data={"url": public_url, "caption": message, "published": "true", "access_token": token},
        timeout=45.0,
    )
    payload = _json(response)
    if response.is_error:
        raise MetaError(_meta_message(payload, response.status_code))
    post_id = str(payload.get("post_id") or payload.get("id") or "")
    if not post_id:
        raise MetaError("Meta accepted the photo but returned no post id")
    return MetaPublishResult(post_id=post_id, post_url=_post_url(post_id))


def _publish_video(page_id: str, token: str, version: str, message: str, media_url: str) -> MetaPublishResult:
    public_url = _public_media_url(media_url)
    response = httpx.post(
        f"{graph_base(version)}/{page_id}/videos",
        data={"file_url": public_url, "description": message, "access_token": token},
        timeout=90.0,
    )
    payload = _json(response)
    if response.is_error:
        raise MetaError(_meta_message(payload, response.status_code))
    post_id = str(payload.get("id") or "")
    if not post_id:
        raise MetaError("Meta accepted the video but returned no video id")
    return MetaPublishResult(post_id=post_id, post_url=_post_url(post_id))


def _public_media_url(media_url: str) -> str:
    if media_url.startswith("https://") or media_url.startswith("http://"):
        return media_url
    base = os.getenv("PUBLIC_BACKEND_URL", "").strip()
    if not base:
        raise MetaError("PUBLIC_BACKEND_URL must be configured before publishing uploaded media")
    return urljoin(base.rstrip("/") + "/", media_url.lstrip("/"))


def _post_url(post_id: str) -> str | None:
    # Meta post ids frequently use PAGEID_POSTID. This URL is a convenience only;
    # the canonical id returned by Meta is retained even if the browser URL shape changes.
    if "_" not in post_id:
        return None
    page_id, object_id = post_id.split("_", 1)
    return f"https://www.facebook.com/{page_id}/posts/{object_id}"


def _json(response: httpx.Response) -> dict:
    try:
        body = response.json()
        return body if isinstance(body, dict) else {}
    except ValueError:
        return {}


def _meta_message(payload: dict, status_code: int) -> str:
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = error.get("message")
        code = error.get("code")
        if message:
            return f"Meta error{f' {code}' if code is not None else ''}: {message}"
    return f"Meta request failed with HTTP {status_code}"
