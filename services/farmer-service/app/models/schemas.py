from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, field_validator


class FarmerCreate(BaseModel):
    phone: str
    name: str
    village: str
    district: str
    state: str
    land_acres: float
    crops: list[str]
    language: str = "hi"
    consent_channel: str = "WHATSAPP"

    @field_validator("phone")
    @classmethod
    def validate_e164(cls, v: str) -> str:
        normalized = v.strip().replace(" ", "").replace("-", "")
        if not normalized.startswith("+"):
            normalized = "+91" + normalized
        # E.164: + followed by 7–15 digits
        digits = normalized[1:]
        if not digits.isdigit() or not (7 <= len(digits) <= 15):
            raise ValueError(
                f"Phone must be E.164 format (e.g. +919876543210). Got: {v!r}"
            )
        return normalized

    @field_validator("land_acres")
    @classmethod
    def positive_acres(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("land_acres must be greater than 0")
        return v

    @field_validator("crops")
    @classmethod
    def non_empty_crops(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("crops list must not be empty")
        return [c.strip() for c in v if c.strip()]


class FarmerResponse(BaseModel):
    id: UUID
    village: str
    district: str
    state: str
    land_acres: float
    crops: list[str]
    language: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class FarmerUpdate(BaseModel):
    village: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    land_acres: Optional[float] = None
    crops: Optional[list[str]] = None
    language: Optional[str] = None

    @field_validator("land_acres")
    @classmethod
    def positive_acres(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError("land_acres must be greater than 0")
        return v

    @field_validator("crops")
    @classmethod
    def non_empty_crops(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is not None:
            if not v:
                raise ValueError("crops list must not be empty")
            return [c.strip() for c in v if c.strip()]
        return v


class FarmerCountResponse(BaseModel):
    total: int
    by_district: dict[str, int]
