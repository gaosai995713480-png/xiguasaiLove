"""TripStar 请求与响应模型。"""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator


class TripStarRequest(BaseModel):
    city: str = Field(..., min_length=1, max_length=80)
    start_date: str = Field(..., min_length=4, max_length=32)
    end_date: str = Field(..., min_length=4, max_length=32)
    travel_days: int = Field(..., ge=1, le=30)
    preferences: list[str] = Field(default_factory=list, max_length=10)
    language: str = Field(default="zh", max_length=10)
    departure_city: str | None = Field(default=None, max_length=80)
    budget: str | None = Field(default=None, max_length=80)
    companions: str | None = Field(default=None, max_length=80)
    special_requirements: str | None = Field(default=None, max_length=500)

    @field_validator("city", "start_date", "end_date", "language")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("字段不能为空")
        return cleaned

    @field_validator("start_date", "end_date")
    @classmethod
    def validate_iso_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("日期必须为 YYYY-MM-DD 格式") from exc
        return value

    @field_validator("preferences", mode="before")
    @classmethod
    def normalize_preferences(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    @field_validator("preferences")
    @classmethod
    def validate_preferences(cls, value: list[str]) -> list[str]:
        if len(value) > 10:
            raise ValueError("偏好最多 10 项")
        if any(len(item) > 50 for item in value):
            raise ValueError("单项偏好不能超过 50 个字符")
        return value


class TripStarSubmitResponse(BaseModel):
    task_id: str
    plan_id: str
    status: str
    ws_url: str
    message: str


class TripStarTaskStatus(BaseModel):
    task_id: str
    plan_id: str
    status: str
    stage: str
    progress: int
    message: str
    result: dict[str, Any] | None = None
    error: str | None = None
    request_payload: dict[str, Any] | None = None


class TripStarMapPoint(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    longitude: float
    latitude: float


class TripStarRouteRequest(BaseModel):
    points: list[TripStarMapPoint] = Field(..., min_length=2, max_length=20)
    mode: str = Field(default="walking", max_length=20)
