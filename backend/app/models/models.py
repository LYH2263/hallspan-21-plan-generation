from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class Hall(Base):
    __tablename__ = "halls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    rows: Mapped[int] = mapped_column(Integer)
    cols: Mapped[int] = mapped_column(Integer)
    min_manhattan: Mapped[int] = mapped_column(Integer, default=2)

class PaperSet(Base):
    __tablename__ = "paper_sets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(128))

class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"))
    name: Mapped[str] = mapped_column(String(64))
    ticket_no: Mapped[str] = mapped_column(String(32))
    paper_id: Mapped[int] = mapped_column(ForeignKey("paper_sets.id"))

class SeatGeneration(Base):
    """快照仓:每一次成功排座落下的一代完整快照,只增不改,世代号按考室单调递增。"""
    __tablename__ = "seat_generations"
    __table_args__ = (UniqueConstraint("hall_id", "generation", name="uq_seat_generations_hall_gen"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"))
    generation: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    snapshot_json: Mapped[str] = mapped_column(Text)

class SeatPointer(Base):
    """世代指针:每个考室恰好一行,指向当前生效的世代;只在成功排座的事务里前移。"""
    __tablename__ = "seat_pointer"
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class SeatReadModel(Base):
    """读模型:排座图/违规/统计三个读端点共用的一份投影,与指针同代重建。"""
    __tablename__ = "seat_read_model"
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer)
    seated: Mapped[int] = mapped_column(Integer)
    unplaced: Mapped[int] = mapped_column(Integer)
    violations: Mapped[int] = mapped_column(Integer)
    capacity: Mapped[int] = mapped_column(Integer)
    view_json: Mapped[str] = mapped_column(Text)
