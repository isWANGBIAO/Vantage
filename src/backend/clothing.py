"""One-workbook clothing sizing, reviewed extraction and local comparison API."""

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from src.core import user_config
from src.services.clothing_models import ClothingRecord
from src.services.clothing_workbook import read_workbook, save_records, WorkbookError, WorkbookConflict, WorkbookBusy
from src.services.clothing_comparison import compare_clothing
from src.services.clothing_vision import extract_clothing, vision_status, ClothingVisionError
from src.utils.data_loader import DataLoader

class PrivateInputRoute(APIRoute):
    """Never echo uploaded screenshots or private trial text in validation errors."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def guarded(request):
            try:
                return await original(request)
            except RequestValidationError:
                raise HTTPException(422, detail={"code": "clothing_invalid_input",
                    "message": "请核对衣服字段、图片大小、日期和厘米单位；原表未改动。"}) from None

        return guarded


router = APIRouter(tags=["Clothing fit"], route_class=PrivateInputRoute)


class ClothingConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workbook_path: str = Field(max_length=4096)


class ClothingExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_data_url: str = Field(max_length=11_200_000)
    provider_route: str = Field(min_length=1, max_length=256)
    model: str = Field(min_length=1, max_length=256)


class ReviewedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: StrictBool

    @field_validator("confirmed")
    @classmethod
    def require_review(cls, value):
        if not value:
            raise ValueError("请先核对尺码数据。")
        return value


class ClothingCompareRequest(ReviewedRequest):
    candidate: ClothingRecord
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class ClothingSaveRequest(ReviewedRequest):
    records: Annotated[list[ClothingRecord], Field(min_length=1, max_length=40)]
    expected_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


def _path():
    configured = user_config.load_settings().get("clothing_workbook_path", "")
    return Path(configured).expanduser() if configured else DataLoader.resolve_data_root() / "衣服尺寸.xlsx"


def _error(error):
    if isinstance(error, WorkbookBusy):
        return HTTPException(409, detail={"code": "workbook_busy", "message": "Excel正在使用该文件，请先保存并关闭Excel，再刷新重试。"})
    if isinstance(error, WorkbookConflict):
        return HTTPException(409, detail={"code": "workbook_changed", "message": "Excel文件已变化，未覆盖任何修改。请刷新历史后重新核对。"})
    if isinstance(error, WorkbookError):
        return HTTPException(422, detail={"code": "workbook_invalid", "message": str(error)})
    return HTTPException(503, detail={"code": "workbook_unavailable", "message": "暂时无法读取或保存工作簿，原文件未被强制覆盖。"})


def _state(workbook_state=None, path=None):
    settings = user_config.load_settings()
    path = path or _path()
    base = {"workbook_path": str(path), "configured_path": settings.get("clothing_workbook_path", ""),
            "vision": vision_status(), "revision": None, "sheet": "Sheet1", "records": [], "warnings": []}
    try:
        return {**base, **(workbook_state if workbook_state is not None else read_workbook(path))}
    except (WorkbookError, OSError) as error:
        return {**base, "error": _error(error).detail["message"]}


@router.get("/api/v1/clothing/state")
async def clothing_state():
    return await asyncio.to_thread(_state)


def _configure(path):
    value = path.strip()
    if value:
        selected = Path(value).expanduser()
        if not selected.is_absolute():
            raise HTTPException(422, detail={"code": "workbook_invalid", "message": "请填写现有Excel文件的完整路径。"})
        try:
            read_workbook(selected)
        except (WorkbookError, OSError) as error:
            raise _error(error) from None
        value = str(selected)
    with user_config.USER_CONFIG_LOCK:
        settings = user_config.load_settings()
        settings["clothing_workbook_path"] = value
        user_config.save_settings(settings)
    return _state()


@router.put("/api/v1/clothing/config")
async def clothing_config(request: ClothingConfigRequest):
    return await asyncio.to_thread(_configure, request.workbook_path)


@router.post("/api/v1/clothing/extract")
async def clothing_extract(request: ClothingExtractRequest):
    try:
        return await asyncio.to_thread(extract_clothing, request.image_data_url,
                                       expected_route=request.provider_route, expected_model=request.model)
    except ClothingVisionError as error:
        raise HTTPException(422, detail={"code": "extraction_failed", "message": str(error)}) from None


def _compare(request):
    try:
        history = read_workbook(_path())
        if history["revision"] != request.revision:
            raise WorkbookConflict("Workbook changed")
        return compare_clothing(request.candidate.model_dump(), history["records"])
    except (WorkbookError, OSError) as error:
        raise _error(error) from None


@router.post("/api/v1/clothing/compare")
async def clothing_compare(request: ClothingCompareRequest):
    return await asyncio.to_thread(_compare, request)


def _save(request):
    try:
        path = _path()
        saved = save_records(path, [record.model_dump(exclude_unset=True) for record in request.records], request.expected_revision)
        return _state(saved, path)
    except (WorkbookError, OSError) as error:
        raise _error(error) from None


@router.post("/api/v1/clothing/records")
async def clothing_save(request: ClothingSaveRequest):
    return await asyncio.to_thread(_save, request)
