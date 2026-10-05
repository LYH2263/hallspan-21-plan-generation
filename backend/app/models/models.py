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
    """快照仓：每次成功排座落下的一整代不可变快照，只追加，不更新、不删除。

    世代号 generation 在同一考室内单调递增；快照内部自带已座/未排/违规三份
    数据与统计，任何读模型都只能从这一份 JSON 投影，禁止回算。
    """
    __tablename__ = "seat_generations"
    __table_args__ = (UniqueConstraint("hall_id", "generation", name="uq_seat_generation_hall_gen"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"), index=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    snapshot_json: Mapped[str] = mapped_column(Text, default="{}")

class SeatGenerationPointer(Base):
    """世代指针：每个考室至多一行，指向快照仓中的当前世代。

    只有成功落代的写事务可以把它拨到新一代；失败排座绝不前移。
    """
    __tablename__ = "seat_generation_pointers"
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
