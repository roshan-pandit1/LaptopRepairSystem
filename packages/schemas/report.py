"""Versioned wire contracts shared by collector and API. No implicit sensor defaults."""
from datetime import datetime, timezone
from typing import List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CATEGORIES = ['battery', 'storage', 'cooling', 'ram', 'system']

def now():
    return datetime.now(timezone.utc).isoformat()

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)

class Device(StrictModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    manufacturer: str = Field(min_length=1, max_length=200)
    model: str = Field(min_length=1, max_length=200)
    os: str = Field(min_length=1, max_length=300)
    demo: bool = False

class Measurement(StrictModel):
    key: str = Field(pattern=r'^[a-z0-9_]{1,80}$')
    component: Literal['battery', 'storage', 'cooling', 'ram', 'system']
    value: Optional[Union[float, str]] = None
    unit: Optional[str] = Field(default=None, max_length=50)
    timestamp: datetime
    source: str = Field(min_length=1, max_length=500)
    status: Literal['available', 'unknown', 'unsupported', 'permission_denied', 'collection_failed']
    limitation: str = Field(min_length=1, max_length=2000)

    @field_validator('timestamp')
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError('timestamp must include timezone')
        if value > datetime.now(timezone.utc).replace(microsecond=0) + __import__('datetime').timedelta(minutes=5):
            raise ValueError('timestamp is in the future')
        return value

    @model_validator(mode='after')
    def availability(self):
        if self.status == 'available' and self.value is None:
            raise ValueError('available requires a value (zero is valid)')
        if self.status != 'available' and self.value is not None:
            raise ValueError('unavailable measurements must have null value')
        if isinstance(self.value, str) and len(self.value) > 4000:
            raise ValueError('measurement text too long')
        return self

class Report(StrictModel):
    schema_version: Literal['1.0']
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    device: Device
    started_at: datetime
    completed_at: datetime
    status: Literal['completed', 'cancelled', 'failed']
    categories: List[Literal['battery', 'storage', 'cooling', 'ram', 'system']] = Field(min_length=1, max_length=5)
    measurements: List[Measurement] = Field(max_length=2000)

    @model_validator(mode='after')
    def coherence(self):
        if self.started_at.tzinfo is None or self.completed_at.tzinfo is None:
            raise ValueError('report times require timezone')
        if self.completed_at < self.started_at:
            raise ValueError('report ends before it starts')
        if len(set(self.categories)) != len(self.categories):
            raise ValueError('duplicate categories')
        if any(m.component not in self.categories for m in self.measurements):
            raise ValueError('measurement outside selected categories')
        if any(m.timestamp < self.started_at or m.timestamp > self.completed_at for m in self.measurements):
            raise ValueError('measurement outside report time range')
        if self.status == 'completed' and set(self.categories) != {m.component for m in self.measurements}:
            raise ValueError('completed reports need an availability result for every category')
        return self
