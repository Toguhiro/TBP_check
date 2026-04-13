from sqlalchemy import Column, String, Integer, Float, DateTime, JSON, Enum, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.core.database import Base


class ProjectStatus(str, enum.Enum):
    pending = "pending"
    extracting = "extracting"
    estimating = "estimating"
    confirmed = "confirmed"
    analyzing = "analyzing"
    done = "done"
    error = "error"


class DrawingType(str, enum.Enum):
    external = "external"           # 外形図
    parts = "parts"                 # 部品図
    internal_layout = "internal_layout"  # 内部部品配置図
    single_line = "single_line"     # 単線結線図
    expanded = "expanded"           # 展開接続図
    sequence_logic = "sequence_logic"  # シーケンスロジック図
    unknown = "unknown"


class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    status = Column(Enum(ProjectStatus), default=ProjectStatus.pending)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Cost tracking
    estimated_input_tokens = Column(Integer, default=0)
    estimated_output_tokens = Column(Integer, default=0)
    estimated_cost_usd = Column(Float, default=0.0)
    actual_input_tokens = Column(Integer, default=0)
    actual_output_tokens = Column(Integer, default=0)
    actual_cost_usd = Column(Float, default=0.0)

    files = relationship("DrawingFile", back_populates="project", cascade="all, delete-orphan")


class DrawingFile(Base):
    __tablename__ = "drawing_files"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    filename = Column(String, nullable=False)
    drawing_type = Column(Enum(DrawingType), default=DrawingType.unknown)
    page_count = Column(Integer, default=0)
    upload_path = Column(String)
    annotated_path = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    project = relationship("Project", back_populates="files")
    pages = relationship("PageResult", back_populates="file", cascade="all, delete-orphan")


class PageResult(Base):
    __tablename__ = "page_results"

    id = Column(String, primary_key=True)
    file_id = Column(String, ForeignKey("drawing_files.id"), nullable=False)
    page_number = Column(Integer, nullable=False)  # 0-indexed
    extracted_text = Column(String, default="")
    ocr_used = Column(String, default="none")  # none / tesseract / azure

    # AI analysis results stored as JSON
    entities = Column(JSON, default=list)         # Tag.No, device names, etc.
    annotations = Column(JSON, default=list)      # {rect, color, message, type}
    uncertain_items = Column(JSON, default=list)  # AI-uncertain elements

    file = relationship("DrawingFile", back_populates="pages")


class CheckResult(Base):
    __tablename__ = "check_results"

    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    check_type = Column(String, nullable=False)   # tag_no, customer_name, cross_ref, etc.
    severity = Column(String, nullable=False)      # error / warning / ok / uncertain
    file_id = Column(String, nullable=True)
    page_number = Column(Integer, nullable=True)
    location_rect = Column(JSON, nullable=True)    # [x0, y0, x1, y1]
    message = Column(String, nullable=False)
    detail = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
