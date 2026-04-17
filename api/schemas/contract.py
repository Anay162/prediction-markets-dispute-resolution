"""
Pydantic schemas for contract input and storage.
These are the data shapes that enter the system from the outside world.
"""
from __future__ import annotations

import uuid
from datetime import datetime, date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, HttpUrl, field_validator, model_validator


class Platform(str, Enum):
    kalshi = "kalshi"
    polymarket = "polymarket"
    manifold = "manifold"
    metaculus = "metaculus"
    generic = "generic"


class ContractInput(BaseModel):
    """
    The raw contract submitted for audit.
    This is exactly what a platform operator pastes in or sends via API.
    """
    question: str
    resolution_criteria: str
    resolution_source: str          # URL or plain-text description of source
    close_date: date
    platform: Platform = Platform.generic
    metadata: dict = {}             # Platform-specific passthrough fields

    @field_validator("question")
    @classmethod
    def question_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question cannot be empty")
        if len(v) < 10:
            raise ValueError("question too short to be a valid prediction market question")
        return v

    @field_validator("resolution_criteria")
    @classmethod
    def criteria_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("resolution_criteria cannot be empty")
        return v

    @field_validator("close_date")
    @classmethod
    def close_date_in_future(cls, v: date) -> date:
        if v <= date.today():
            raise ValueError("close_date must be in the future")
        return v

    @model_validator(mode="after")
    def combined_length_check(self) -> ContractInput:
        total = len(self.question) + len(self.resolution_criteria)
        if total > 20_000:
            raise ValueError("Combined question + criteria exceeds 20,000 characters")
        return self


class ContractDB(BaseModel):
    """
    Contract as stored in the database, after being assigned an ID.
    """
    id: uuid.UUID
    question: str
    resolution_criteria: str
    resolution_source: str
    close_date: date
    platform: Platform
    metadata: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContractSummary(BaseModel):
    """Lightweight contract representation for list views."""
    id: uuid.UUID
    question: str
    platform: Platform
    close_date: date
    created_at: datetime

    model_config = {"from_attributes": True}
