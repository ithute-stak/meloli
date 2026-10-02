import json
import mimetypes
import os
from dataclasses import dataclass
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


@dataclass
class MetaPerformanceResult:
    impressions: int | None = None
    reach: int | None = None
    engaged_users: int | None = None
    clicks: int | None = None
    reactions: int | None = None
    comments: int | None = None
    shares: int | None = None
    video_views: int | None = None


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


def fetch_post_performance(post_id: str, access_token: str, version: str) -> MetaPerformanceResult:
    """Fetch the metrics Meta exposes for a published Page post.

    Interaction totals and Insights are queried separately. Insights metric
    availability changes by Graph API version and Page/app permissions, so an
    unavailable Insights metric never discards interaction data that Meta did
    return successfully.
    """
    result = MetaPerformanceResult()
    try:
        response = httpx.get(
            f"{graph_base(version)}/{post_id}",
            params={
                "fields": "shares,comments.limit(0).summary(true),reactions.limit(0).summary(true)",
                "access_token": access_token,
            },
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise MetaError(f"Unable to reach Meta: {exc}") from exc
    payload = _json(response)
    if response.is_error:
        raise MetaError(_meta_message(payload, response.status_code))

    shares = payload.get("shares")
    if isinstance(shares, dict):
        result.shares = _as_int(shares.get("count"))
    result.comments = _summary_total(payload.get("comments"))
    result.reactions = _summary_total(payload.get("reactions"))

    # Common Page-post Insights metrics. Meta may retire or restrict individual
    # metrics; failures here are tolerated and the API returns the interaction
    # totals above. This keeps the portal compatible across Graph API versions.
    insight_names = [
        "post_impressions",
        "post_impressions_unique",
        "post_engaged_users",
        "post_clicks",
        "post_video_views",
    ]
    try:
        insights_response = httpx.get(
            f"{graph_base(version)}/{post_id}/insights",
            params={"metric": ",".join(insight_names), "access_token": access_token},
            timeout=30.0,
        )
        insights_payload = _json(insights_response)
        if not insights_response.is_error:
            metrics = _insight_map(insights_payload)
            result.impressions = metrics.get("post_impressions")
            result.reach = metrics.get("post_impressions_unique")
            result.engaged_users = metrics.get("post_engaged_users")
            result.clicks = metrics.get("post_clicks")
            result.video_views = metrics.get("post_video_views")
    except httpx.HTTPError:
        pass

    return result


def publish_campaign(
    *,
    page_id: str,
    access_token: str,
    version: str,
    message: str,
    media_url: str | None,
    destination_url: str | None,
    media_items: list[tuple[str, str]] | None = None,
) -> MetaPublishResult:
    items = list(media_items or [])
    if len(items) > 1:
        if any(not content_type.startswith("image/") for _, content_type in items):
            raise MetaError("Facebook carousel publishing currently supports images only")
        return _publish_carousel(page_id, access_token, version, message, [url for url, _ in items])
    if len(items) == 1:
        item_url, content_type = items[0]
        if content_type.startswith("image/"):
            return _publish_photo(page_id, access_token, version, message, item_url)
        if content_type.startswith("video/"):
            return _publish_video(page_id, access_token, version, message, item_url)
    if media_url:
        content_type = mimetypes.guess_type(media_url.split("?", 1)[0])[0] or ""
        if content_type.startswith("image/"):
            return _publish_photo(page_id, access_token, version, message, media_url)
        if content_type.startswith("video/"):
            return _publish_video(page_id, access_token, version, message, media_url)
    return _publish_feed(page_id, access_token, version, message, destination_url)


def _publish_carousel(page_id: str, token: str, version: str, message: str, media_urls: list[str]) -> MetaPublishResult:
    if len(media_urls) < 2 or len(media_urls) > 10:
        raise MetaError("Facebook carousel posts require between 2 and 10 images")
    photo_ids: list[str] = []
    for media_url in media_urls:
        response = httpx.post(
            f"{graph_base(version)}/{page_id}/photos",
            data={
                "url": _public_media_url(media_url),
                "published": "false",
                "access_token": token,
            },
            timeout=45.0,
        )
        payload = _json(response)
        if response.is_error:
            raise MetaError(_meta_message(payload, response.status_code))
        photo_id = str(payload.get("id") or "")
        if not photo_id:
            raise MetaError("Meta accepted a carousel image but returned no photo id")
        photo_ids.append(photo_id)

    data: dict[str, str] = {"message": message, "access_token": token}
    for index, photo_id in enumerate(photo_ids):
        data[f"attached_media[{index}]"] = json.dumps({"media_fbid": photo_id})
    response = httpx.post(f"{graph_base(version)}/{page_id}/feed", data=data, timeout=45.0)
    payload = _json(response)
    if response.is_error:
        raise MetaError(_meta_message(payload, response.status_code))
    post_id = str(payload.get("id") or "")
    if not post_id:
        raise MetaError("Meta accepted the carousel but returned no post id")
    return MetaPublishResult(post_id=post_id, post_url=_post_url(post_id))


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
    if "_" not in post_id:
        return None
    page_id, object_id = post_id.split("_", 1)
    return f"https://www.facebook.com/{page_id}/posts/{object_id}"


def _summary_total(value: object) -> int | None:
    if not isinstance(value, dict):
        return None
    summary = value.get("summary")
    if not isinstance(summary, dict):
        return None
    return _as_int(summary.get("total_count"))


def _insight_map(payload: dict) -> dict[str, int]:
    values: dict[str, int] = {}
    data = payload.get("data")
    if not isinstance(data, list):
        return values
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        entries = item.get("values")
        if not isinstance(name, str) or not isinstance(entries, list) or not entries:
            continue
        latest = entries[-1]
        if isinstance(latest, dict):
            value = latest.get("value")
            if isinstance(value, dict):
                value = sum(v for v in value.values() if isinstance(v, (int, float)))
            number = _as_int(value)
            if number is not None:
                values[name] = number
    return values


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


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
