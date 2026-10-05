from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Candidate, Hall
from app.services.generation_store import SnapshotIntegrityError, commit_new_generation
from app.services.read_model import (
    GenerationNotFoundError,
    ReadModelInconsistent,
    get_by_generation,
    get_current,
    project_stats,
    project_violations,
)

router = APIRouter(prefix="/seating", tags=["seating"])


def _hall_or_404(db: Session, hall_id: int) -> Hall:
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    return hall


def _current_snapshot_or_raise(db: Session, hall_id: int) -> dict:
    """读模型统一入口：只回指针所指世代的快照；对不齐整场失败。"""
    try:
        return get_current(db, hall_id)
    except GenerationNotFoundError as exc:
        raise HTTPException(404, "尚无已落代的排座，请先运行排座") from exc
    except ReadModelInconsistent as exc:
        # 三处数字对不齐：整场失败，绝不回算或拼半套数据
        raise HTTPException(500, f"排座读模型对不齐：{exc}") from exc


@router.post("/run")
def run_seating(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = _hall_or_404(db, hall_id)
    cands = [
        {"id": c.id, "name": c.name, "ticket_no": c.ticket_no, "paper_id": c.paper_id}
        for c in db.scalars(select(Candidate).where(Candidate.hall_id == hall_id)).all()
    ]
    try:
        snapshot = commit_new_generation(db, hall, cands)
    except SnapshotIntegrityError as exc:
        # 失败的一次：无世代行、无半张方案、指针不前移
        raise HTTPException(500, f"排座失败，未落代：{exc}") from exc
    except Exception as exc:  # 引擎/提交任何异常：store 已整体回滚，不落代
        raise HTTPException(500, f"排座失败，未落代：{exc}") from exc
    return snapshot


@router.get("/latest")
def latest(hall_id: int = 1, db: Session = Depends(get_db)):
    _hall_or_404(db, hall_id)
    # 只读指针所指世代，绝不在读路径里触发重排
    return _current_snapshot_or_raise(db, hall_id)


@router.get("/generations/{generation}")
def read_generation(generation: int, hall_id: int = 1, db: Session = Depends(get_db)):
    """按世代号读取旧世代：只回该代快照。纯读，不插新方案行、不改指针、不重算。"""
    _hall_or_404(db, hall_id)
    try:
        return get_by_generation(db, hall_id, generation)
    except GenerationNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ReadModelInconsistent as exc:
        raise HTTPException(500, f"排座读模型对不齐：{exc}") from exc


@router.get("/violations")
def violations(hall_id: int = 1, db: Session = Depends(get_db)):
    _hall_or_404(db, hall_id)
    snapshot = _current_snapshot_or_raise(db, hall_id)
    return project_violations(hall_id, snapshot)


@router.get("/stats")
def stats(hall_id: int = 1, db: Session = Depends(get_db)):
    _hall_or_404(db, hall_id)
    snapshot = _current_snapshot_or_raise(db, hall_id)
    return project_stats(hall_id, snapshot)
