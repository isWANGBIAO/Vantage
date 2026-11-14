"""Bounded, UI-neutral clothing records; private records stay in the workbook."""

from typing import Annotated, Literal
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

Part = Literal["外壳", "内胆", "整件", "未知"]
Measurement = Annotated[float, Field(strict=True, gt=0, le=500, allow_inf_nan=False)]
Text = Annotated[str, Field(max_length=2000)]


class ClothingRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    row: Annotated[int, Field(strict=True, ge=2)] | None = None
    garment: Text = ""
    brand: Text = ""
    style_code: Text = ""
    category: Text = "未知"
    size: Text = ""
    component: Part = "未知"
    length_cm: Measurement | None = None
    chest_cm: Measurement | None = None
    chest_width_cm: Measurement | None = None
    shoulder_cm: Measurement | None = None
    sleeve_cm: Measurement | None = None
    length_basis: Literal["后肩衣长", "未知"] = "未知"
    sleeve_basis: Literal["肩点袖长", "连肩袖长", "未知"] = "未知"
    measurement_source: Text = "历史未确认"
    measurement_tolerance_cm: Annotated[float, Field(strict=True, ge=0, le=20, allow_inf_nan=False)] | None = None
    trial_date: str | None = None
    feedback_scope: Part = "未知"
    shoulder_feedback: Text = ""
    sleeve_feedback: Text = ""
    length_feedback: Text = ""
    chest_feedback: Text = ""
    mobility_feedback: Text = ""
    overall_feedback: Text = ""
    layering: Text = ""
    notes: Text = ""
    warnings: list[Annotated[str, Field(max_length=1000)]] = Field(default_factory=list, max_length=50)
    record_kind: Literal["garment", "body", "unclassified"] = "garment"

    @field_validator("trial_date")
    @classmethod
    def valid_date(cls, value):
        if value in (None, ""):
            return None
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError("Use YYYY-MM-DD for the trial date.")
        return value

    @field_validator("chest_width_cm")
    @classmethod
    def bounded_width(cls, value):
        if value is not None and value > 250:
            raise ValueError("Flat chest width must not exceed 250 cm.")
        return value
