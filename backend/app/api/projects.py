"""
プロジェクト管理 API エンドポイント
"""
import os
import uuid
import logging
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import get_db
from app.models.project import Project, DrawingFile, PageResult, CheckResult, ProjectStatus, DrawingType
from app.schemas.project import (
    ProjectCreate, ProjectOut, CostEstimate, AnalysisResultOut,
    CheckResultOut, CostActual,
)
from app.services.analysis_pipeline import estimate_project_cost, run_analysis

router = APIRouter(prefix="/api/projects", tags=["projects"])
logger = logging.getLogger(__name__)
settings = get_settings()


@router.post("", response_model=ProjectOut)
async def create_project(
    data: ProjectCreate,
    db: AsyncSession = Depends(get_db),
):
    """新規プロジェクトを作成する"""
    project = Project(id=str(uuid.uuid4()), name=data.name)
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
async def list_projects(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).order_by(Project.created_at.desc()))
    return result.scalars().all()


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    project = await _get_project_or_404(project_id, db)
    return project


@router.post("/{project_id}/files")
async def upload_files(
    project_id: str,
    files: list[UploadFile] = File(...),
    drawing_types: Optional[str] = Form(None),  # JSON: {"filename": "drawing_type"}
    db: AsyncSession = Depends(get_db),
):
    """PDFファイルをアップロードする"""
    import json
    project = await _get_project_or_404(project_id, db)

    type_map: dict[str, str] = {}
    if drawing_types:
        try:
            type_map = json.loads(drawing_types)
        except Exception:
            pass

    upload_dir = os.path.join(settings.upload_dir, project_id)
    os.makedirs(upload_dir, exist_ok=True)

    uploaded = []
    for upload in files:
        if not upload.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"{upload.filename} はPDFファイルではありません")

        file_id = str(uuid.uuid4())
        save_path = os.path.join(upload_dir, f"{file_id}_{upload.filename}")

        content = await upload.read()
        with open(save_path, "wb") as f:
            f.write(content)

        drawing_type_str = type_map.get(upload.filename, "unknown")
        try:
            drawing_type = DrawingType(drawing_type_str)
        except ValueError:
            drawing_type = DrawingType.unknown

        db_file = DrawingFile(
            id=file_id,
            project_id=project_id,
            filename=upload.filename,
            drawing_type=drawing_type,
            upload_path=save_path,
        )
        db.add(db_file)
        uploaded.append({"file_id": file_id, "filename": upload.filename})

    await db.commit()
    return {"uploaded": uploaded}


@router.post("/{project_id}/estimate", response_model=CostEstimate)
async def estimate_cost(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """解析前のコスト推定を返す"""
    project = await _get_project_or_404(project_id, db)

    result = await db.execute(
        select(DrawingFile).where(DrawingFile.project_id == project_id)
    )
    files = result.scalars().all()
    if not files:
        raise HTTPException(status_code=400, detail="ファイルがアップロードされていません")

    file_list = [
        {"path": f.upload_path, "drawing_type": f.drawing_type.value, "file_id": f.id}
        for f in files
    ]

    estimate = await estimate_project_cost(file_list)

    # DB更新
    project.estimated_input_tokens = estimate["estimated_input_tokens"]
    project.estimated_output_tokens = estimate["estimated_output_tokens"]
    project.estimated_cost_usd = estimate["estimated_cost_usd"]
    project.status = ProjectStatus.estimating
    await db.commit()

    return CostEstimate(**estimate)


@router.post("/{project_id}/analyze")
async def start_analysis(
    project_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """解析を開始する（バックグラウンド実行）"""
    project = await _get_project_or_404(project_id, db)

    if project.status == ProjectStatus.analyzing:
        raise HTTPException(status_code=409, detail="すでに解析中です")

    project.status = ProjectStatus.analyzing
    await db.commit()

    background_tasks.add_task(_run_analysis_task, project_id)
    return {"message": "解析を開始しました", "project_id": project_id}


@router.get("/{project_id}/results", response_model=AnalysisResultOut)
async def get_results(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """解析結果を取得する"""
    project = await _get_project_or_404(project_id, db)

    if project.status not in (ProjectStatus.done, ProjectStatus.error):
        raise HTTPException(
            status_code=202,
            detail={"status": project.status.value, "message": "解析中です"}
        )

    result = await db.execute(
        select(CheckResult).where(CheckResult.project_id == project_id)
    )
    check_results = result.scalars().all()

    return AnalysisResultOut(
        project_id=project_id,
        status=project.status,
        cost=CostActual(
            actual_input_tokens=project.actual_input_tokens,
            actual_output_tokens=project.actual_output_tokens,
            actual_cost_usd=project.actual_cost_usd,
            model=settings.gemini_model,
        ),
        check_results=[CheckResultOut.model_validate(r) for r in check_results],
        uncertain_items=[],
    )


@router.get("/{project_id}/files/{file_id}/annotated")
async def download_annotated_pdf(
    project_id: str,
    file_id: str,
    db: AsyncSession = Depends(get_db),
):
    """アノテーション済みPDFをダウンロードする"""
    result = await db.execute(
        select(DrawingFile).where(
            DrawingFile.id == file_id,
            DrawingFile.project_id == project_id
        )
    )
    db_file = result.scalar_one_or_none()
    if not db_file:
        raise HTTPException(status_code=404, detail="ファイルが見つかりません")
    if not db_file.annotated_path or not os.path.exists(db_file.annotated_path):
        raise HTTPException(status_code=404, detail="アノテーション済みPDFはまだ生成されていません")

    return FileResponse(
        db_file.annotated_path,
        media_type="application/pdf",
        filename=f"annotated_{db_file.filename}",
    )


async def _get_project_or_404(project_id: str, db: AsyncSession) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="プロジェクトが見つかりません")
    return project


async def _run_analysis_task(project_id: str):
    """バックグラウンドで解析タスクを実行する"""
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(DrawingFile).where(DrawingFile.project_id == project_id)
            )
            files = result.scalars().all()

            file_list = [
                {
                    "path": f.upload_path,
                    "drawing_type": f.drawing_type.value,
                    "file_id": f.id,
                    "filename": f.filename,
                }
                for f in files
            ]

            analysis = await run_analysis(file_list)

            # 結果をDBに保存
            for cr in analysis["check_results"]:
                check = CheckResult(
                    id=str(uuid.uuid4()),
                    project_id=project_id,
                    check_type=cr["check_type"],
                    severity=cr["severity"],
                    file_id=cr.get("file_id"),
                    page_number=cr.get("page_number"),
                    location_rect=cr.get("location_rect"),
                    message=cr["message"],
                    detail=cr.get("detail"),
                )
                db.add(check)

            # アノテーション済みパスを更新
            for file_id, annotated_path in analysis["annotated_files"].items():
                result = await db.execute(select(DrawingFile).where(DrawingFile.id == file_id))
                db_file = result.scalar_one_or_none()
                if db_file:
                    db_file.annotated_path = annotated_path

            # プロジェクトのコスト・ステータス更新
            proj_result = await db.execute(select(Project).where(Project.id == project_id))
            project = proj_result.scalar_one_or_none()
            if project:
                usage = analysis["usage"]
                project.actual_input_tokens = usage["input_tokens"]
                project.actual_output_tokens = usage["output_tokens"]
                project.actual_cost_usd = usage["cost_usd"]
                project.status = ProjectStatus.done

            await db.commit()

        except Exception as e:
            logger.error(f"Analysis failed for project {project_id}: {e}", exc_info=True)
            proj_result = await db.execute(select(Project).where(Project.id == project_id))
            project = proj_result.scalar_one_or_none()
            if project:
                project.status = ProjectStatus.error
            await db.commit()
