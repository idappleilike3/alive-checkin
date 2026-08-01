"""推播管理中心的不可變活動與狀態轉換核心。"""

from __future__ import annotations

import copy
from datetime import datetime
from uuid import uuid4


CAMPAIGN_STATUSES = {
    "draft",
    "pending_schedule",
    "scheduled",
    "sending",
    "completed",
    "partially_failed",
    "fully_failed",
    "cancelled",
}

CAMPAIGN_STATUS_LABELS_ZH = {
    "draft": "草稿",
    "pending_schedule": "待排程",
    "scheduled": "已排程",
    "sending": "發送中",
    "completed": "已完成",
    "partially_failed": "部分失敗",
    "fully_failed": "全部失敗",
    "cancelled": "已取消",
}

APPROVED_PUSH_TEMPLATES = {
    "day7_pin_reminder",
    "beta_day2_private_note",
}

_VERSION_FIELDS = (
    "name",
    "content_type",
    "text",
    "template_key",
    "template_variables",
    "plan_audiences",
    "explicit_member_ids",
)


class CampaignError(ValueError):
    """Base error for invalid push campaign operations."""


class CampaignNotFoundError(CampaignError):
    """Raised when a campaign ID does not exist."""


class CampaignValidationError(CampaignError):
    """Raised when campaign input is incomplete or invalid."""


class CampaignConflictError(CampaignError):
    """Raised when an operation conflicts with the campaign state."""


def _iso(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise CampaignValidationError("now must be a datetime")
    return value.isoformat(timespec="seconds")


def _new_id() -> str:
    return str(uuid4())


def ensure_push_state(state: dict) -> dict:
    if not isinstance(state, dict):
        raise CampaignValidationError("state must be a dictionary")
    state.setdefault("push_campaigns", [])
    state.setdefault("push_campaign_versions", [])
    state.setdefault("push_delivery_records", [])
    state.setdefault("push_campaign_events", [])
    return state


def _campaign(state: dict, campaign_id: str) -> dict:
    ensure_push_state(state)
    for item in state["push_campaigns"]:
        if str(item.get("id") or "") == str(campaign_id or ""):
            return item
    raise CampaignNotFoundError("campaign not found")


def _current_version(state: dict, campaign: dict) -> dict:
    version_number = int(campaign.get("current_version") or 0)
    for version in state["push_campaign_versions"]:
        if (
            version.get("campaign_id") == campaign.get("id")
            and int(version.get("version") or 0) == version_number
        ):
            return version
    raise CampaignConflictError("current campaign version is missing")


def _clean_list(values) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    return list(dict.fromkeys(str(value or "").strip() for value in values if str(value or "").strip()))


def _version_snapshot(payload: dict, previous: dict | None = None) -> dict:
    snapshot = {
        "name": "",
        "content_type": "text",
        "text": "",
        "template_key": "",
        "template_variables": {},
        "plan_audiences": [],
        "explicit_member_ids": [],
    }
    if previous:
        snapshot.update({key: copy.deepcopy(previous.get(key)) for key in _VERSION_FIELDS})
    for key in _VERSION_FIELDS:
        if key in payload:
            snapshot[key] = copy.deepcopy(payload.get(key))

    snapshot["name"] = str(snapshot.get("name") or "").strip()[:120]
    snapshot["content_type"] = str(snapshot.get("content_type") or "text").strip().lower()
    snapshot["text"] = str(snapshot.get("text") or "").strip()
    snapshot["template_key"] = str(snapshot.get("template_key") or "").strip()
    snapshot["template_variables"] = (
        copy.deepcopy(snapshot.get("template_variables"))
        if isinstance(snapshot.get("template_variables"), dict)
        else {}
    )
    snapshot["plan_audiences"] = _clean_list(snapshot.get("plan_audiences"))
    snapshot["explicit_member_ids"] = _clean_list(snapshot.get("explicit_member_ids"))

    if not snapshot["name"]:
        raise CampaignValidationError("campaign name is required")
    if snapshot["content_type"] not in {"text", "template"}:
        raise CampaignValidationError("content type is invalid")
    if "flex" in payload or "flex_json" in payload:
        raise CampaignValidationError("arbitrary Flex JSON is not allowed")
    if snapshot["content_type"] == "text" and not snapshot["text"]:
        raise CampaignValidationError("text content is required")
    if snapshot["content_type"] == "template":
        if snapshot["template_key"] not in APPROVED_PUSH_TEMPLATES:
            raise CampaignValidationError("template is not approved")
        snapshot["text"] = ""
    return snapshot


def _append_event(
    state: dict,
    campaign: dict,
    event_type: str,
    actor: str,
    now: datetime,
    **detail,
) -> dict:
    event = {
        "id": _new_id(),
        "campaign_id": campaign["id"],
        "event_type": event_type,
        "actor": str(actor or "system"),
        "created_at": _iso(now),
        **copy.deepcopy(detail),
    }
    state["push_campaign_events"].append(event)
    return event


def _append_version(
    state: dict,
    campaign: dict,
    payload: dict,
    actor: str,
    now: datetime,
    previous: dict | None = None,
) -> dict:
    snapshot = _version_snapshot(payload, previous=previous)
    number = int(campaign.get("current_version") or 0) + 1
    version = {
        "id": _new_id(),
        "campaign_id": campaign["id"],
        "version": number,
        **snapshot,
        "created_by": str(actor or ""),
        "created_at": _iso(now),
    }
    state["push_campaign_versions"].append(version)
    campaign["current_version"] = number
    campaign["name"] = version["name"]
    campaign["updated_by"] = str(actor or "")
    campaign["updated_at"] = _iso(now)
    return version


def create_campaign(state: dict, payload: dict, actor: str, now: datetime) -> dict:
    ensure_push_state(state)
    campaign = {
        "id": _new_id(),
        "name": "",
        "status": "draft",
        "current_version": 0,
        "scheduled_at": None,
        "created_by": str(actor or ""),
        "created_at": _iso(now),
        "updated_by": str(actor or ""),
        "updated_at": _iso(now),
        "sent_count": 0,
        "failed_count": 0,
    }
    _append_version(state, campaign, payload or {}, actor, now)
    state["push_campaigns"].append(campaign)
    _append_event(state, campaign, "created", actor, now, version=1)
    return campaign


def update_campaign(
    state: dict,
    campaign_id: str,
    payload: dict,
    actor: str,
    now: datetime,
) -> dict:
    campaign = _campaign(state, campaign_id)
    if campaign["status"] not in {"draft", "pending_schedule", "scheduled"}:
        raise CampaignConflictError("campaign can no longer be edited")
    previous = _current_version(state, campaign)
    version = _append_version(state, campaign, payload or {}, actor, now, previous=previous)
    schedule_invalidated = campaign["status"] == "scheduled"
    if schedule_invalidated:
        campaign["status"] = "pending_schedule"
        campaign["scheduled_at"] = None
    _append_event(
        state,
        campaign,
        "updated",
        actor,
        now,
        version=version["version"],
        schedule_invalidated=schedule_invalidated,
    )
    return campaign


def prepare_campaign(state: dict, campaign_id: str, actor: str, now: datetime) -> dict:
    campaign = _campaign(state, campaign_id)
    if campaign["status"] not in {"draft", "pending_schedule"}:
        raise CampaignConflictError("campaign cannot be prepared from this state")
    version = _current_version(state, campaign)
    if not version["plan_audiences"] and not version["explicit_member_ids"]:
        raise CampaignValidationError("at least one audience is required")
    campaign["status"] = "pending_schedule"
    campaign["updated_by"] = str(actor or "")
    campaign["updated_at"] = _iso(now)
    _append_event(state, campaign, "prepared", actor, now, version=version["version"])
    return campaign


def schedule_campaign(
    state: dict,
    campaign_id: str,
    scheduled_at: datetime,
    actor: str,
    now: datetime,
) -> dict:
    campaign = _campaign(state, campaign_id)
    if campaign["status"] != "pending_schedule":
        raise CampaignConflictError("campaign must be prepared before scheduling")
    if not isinstance(scheduled_at, datetime) or scheduled_at <= now:
        raise CampaignValidationError("scheduled time must be in the future")
    campaign["status"] = "scheduled"
    campaign["scheduled_at"] = _iso(scheduled_at)
    campaign["updated_by"] = str(actor or "")
    campaign["updated_at"] = _iso(now)
    _append_event(
        state,
        campaign,
        "scheduled",
        actor,
        now,
        scheduled_at=campaign["scheduled_at"],
    )
    return campaign


def mark_campaign_sending(state: dict, campaign_id: str, now: datetime) -> dict:
    campaign = _campaign(state, campaign_id)
    if campaign["status"] != "scheduled":
        raise CampaignConflictError("only scheduled campaigns can start sending")
    campaign["status"] = "sending"
    campaign["sending_started_at"] = _iso(now)
    campaign["updated_at"] = _iso(now)
    _append_event(state, campaign, "sending_started", "system", now)
    return campaign


def finalize_campaign(
    state: dict,
    campaign_id: str,
    sent_count: int,
    failed_count: int,
    now: datetime,
) -> dict:
    campaign = _campaign(state, campaign_id)
    if campaign["status"] != "sending":
        raise CampaignConflictError("only sending campaigns can be finalized")
    sent = max(0, int(sent_count or 0))
    failed = max(0, int(failed_count or 0))
    if sent and failed:
        status = "partially_failed"
    elif failed:
        status = "fully_failed"
    else:
        status = "completed"
    campaign["status"] = status
    campaign["sent_count"] = sent
    campaign["failed_count"] = failed
    campaign["completed_at"] = _iso(now)
    campaign["updated_at"] = _iso(now)
    _append_event(
        state,
        campaign,
        "finalized",
        "system",
        now,
        status=status,
        sent_count=sent,
        failed_count=failed,
    )
    return campaign


def cancel_campaign(
    state: dict,
    campaign_id: str,
    reason_zh: str,
    actor: str,
    now: datetime,
) -> dict:
    campaign = _campaign(state, campaign_id)
    if campaign["status"] not in {"draft", "pending_schedule", "scheduled"}:
        raise CampaignConflictError("campaign can no longer be cancelled")
    reason = str(reason_zh or "").strip()
    if not reason:
        raise CampaignValidationError("cancellation reason is required")
    campaign["status"] = "cancelled"
    campaign["cancelled_at"] = _iso(now)
    campaign["cancelled_by"] = str(actor or "")
    campaign["cancellation_reason_zh"] = reason[:500]
    campaign["updated_by"] = str(actor or "")
    campaign["updated_at"] = _iso(now)
    _append_event(state, campaign, "cancelled", actor, now, reason_zh=reason[:500])
    return campaign
