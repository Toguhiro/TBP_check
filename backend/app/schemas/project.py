from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from app.models.project import ProjectStatus, DrawingType


class DrawingFileCreate(BaseModel):
    filename: str
    drawing_type: DrawingType = DrawingType.unknown


class DrawingFileOut(BaseModel):
    id: str
    filename: str
    drawing_type: DrawingType
    page_count: int
    annotated_path: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ProjectCreate(BaseModel):
    name: str


class ProjectOut(BaseModel):
    id: str
    name: str
    status: ProjectStatus
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float
    actual_input_tokens: int
    actual_output_tokens: int
    actual_cost_usd: float
    created_at: datetime
    files: list[DrawingFileOut] = []

    class Config:
        from_attributes = True


class CostEstimate(BaseModel):
    file_count: int
    total_pages: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_cost_usd: float
    free_tier_note: str = "Gemini 1.5 Flash 有料換算（無料枠利用の場合も同レートで表示）"


class CostActual(BaseModel):
    actual_input_tokens: int
    actual_output_tokens: int
    actual_cost_usd: float
    model: str
    free_tier_note: str = "Gemini 1.5 Flash 有料換算（無料枠利用の場合も同レートで表示）"


class AnnotationItem(BaseModel):
    rect: list[float]        # [x0, y0, x1, y1]
    color: str               # "yellow" | "red" | "orange"
    message: str
    check_type: str


class PageResultOut(BaseModel):
    page_number: int
    ocr_used: str
    entities: list[dict]
    annotations: list[AnnotationItem]
    uncertain_items: list[dict]


class CheckResultOut(BaseModel):
    id: str
    check_type: str
    severity: str
    file_id: Optional[str]
    page_number: Optional[int]
    location_rect: Optional[list[float]]
    message: str
    detail: Optional[dict]

    class Config:
        from_attributes = True


class AnalysisResultOut(BaseModel):
    project_id: str
    status: ProjectStatus
    cost: CostActual
    check_results: list[CheckResultOut]
    uncertain_items: list[dict]
