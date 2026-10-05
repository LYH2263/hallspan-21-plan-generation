"""世代指针/快照仓/读模型的语义测试(内存 sqlite)。"""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import Candidate, Hall, PaperSet, SeatGeneration, SeatPointer, SeatReadModel
from app.services import seating_store
from app.services.seat_engine import place_candidates as real_place

ROSTER = 6


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    hall = Hall(code="H1", name="一考室", rows=5, cols=6, min_manhattan=2)
    session.add(hall)
    session.flush()
    paper = PaperSet(code="P-A", title="语文 A 卷")
    session.add(paper)
    session.flush()
    for i in range(ROSTER):
        session.add(Candidate(hall_id=hall.id, name=f"考生{i}", ticket_no=f"T{i}", paper_id=paper.id))
    session.commit()
    yield session
    session.close()


def gen_rows(db):
    return db.scalars(select(SeatGeneration).order_by(SeatGeneration.generation)).all()


def test_two_successful_runs_leave_two_generations_pointer_at_latest(db):
    seating_store.run_generation(db, 1)
    seating_store.run_generation(db, 1)
    assert [g.generation for g in gen_rows(db)] == [1, 2]
    assert db.get(SeatPointer, 1).generation == 2
    assert db.get(SeatReadModel, 1).generation == 2
    snaps = [seating_store.generation_snapshot(db, 1, g) for g in (1, 2)]
    assert all(s and s["assignments"] for s in snaps)


def test_failed_run_leaves_no_generation_no_half_plan_pointer_unmoved(db, monkeypatch):
    seating_store.run_generation(db, 1)

    def boom(*_a, **_k):
        raise RuntimeError("引擎爆炸")

    monkeypatch.setattr(seating_store, "place_candidates", boom)
    with pytest.raises(RuntimeError):
        seating_store.run_generation(db, 1)
    assert [g.generation for g in gen_rows(db)] == [1]      # 没留下世代号
    assert db.get(SeatPointer, 1).generation == 1           # 指针没前移
    assert db.get(SeatReadModel, 1).generation == 1         # 没留下半张方案

    monkeypatch.undo()
    out = seating_store.run_generation(db, 1)
    assert out["generation"] == 2                           # 失败的一次没吃掉世代号


def test_inconsistent_result_fails_and_leaves_nothing(db, monkeypatch):
    def drop_one(rows, cols, min_dist, cands):
        assigns, unplaced = real_place(rows, cols, min_dist, cands)
        return (assigns[:-1], unplaced) if not unplaced else (assigns, unplaced[:-1])

    monkeypatch.setattr(seating_store, "place_candidates", drop_one)
    with pytest.raises(seating_store.SeatingFailedError):
        seating_store.run_generation(db, 1)
    assert gen_rows(db) == []
    assert db.get(SeatPointer, 1) is None
    assert db.get(SeatReadModel, 1) is None


def test_old_generation_reads_snapshot_not_recompute(db):
    out1 = seating_store.run_generation(db, 1)
    # 现网变化:最小距调大、名册加人
    hall = db.get(Hall, 1)
    hall.min_manhattan = 4
    db.add(Candidate(hall_id=1, name="插班生", ticket_no="T999", paper_id=1))
    db.commit()
    out2 = seating_store.run_generation(db, 1)
    assert out2["generation"] == 2

    rows_before = len(gen_rows(db))
    snap = seating_store.generation_snapshot(db, 1, 1)
    assert snap["generation"] == 1
    assert snap["hall"]["min_manhattan"] == 2                       # 当时的参数,不是现网参数
    assert snap["stats"]["seated"] == out1["stats"]["seated"]
    assert all(a["name"] != "插班生" for a in snap["assignments"])  # 不掺现网名单
    # 按世代读是纯读:不插入新方案行,也不改指针
    assert len(gen_rows(db)) == rows_before
    assert db.get(SeatPointer, 1).generation == 2


def test_three_views_same_generation_same_numbers(db):
    out = seating_store.run_generation(db, 1)
    view = seating_store.current_view(db, 1)
    stats = seating_store.current_stats(db, 1)
    viol = seating_store.current_violations(db, 1)
    assert view["generation"] == stats["generation"] == viol["generation"] == out["generation"]
    assert stats["seated"] == len(view["assignments"]) == out["stats"]["seated"]
    assert stats["unplaced"] == len(view["unplaced"]) == len(viol["unplaced"])
    assert stats["violations"] == len(view["violations"]) == len(viol["violations"])
    assert stats["seated"] + stats["unplaced"] == ROSTER


def test_views_none_before_first_run_and_write_nothing(db):
    assert seating_store.current_view(db, 1) is None
    assert seating_store.current_stats(db, 1) is None
    assert seating_store.current_violations(db, 1) is None
    assert gen_rows(db) == []
    assert db.get(SeatPointer, 1) is None


def test_misaligned_pointer_and_read_model_fails_loudly(db):
    seating_store.run_generation(db, 1)
    db.get(SeatReadModel, 1).generation = 999
    db.commit()
    with pytest.raises(seating_store.ReadModelMisalignedError):
        seating_store.current_view(db, 1)


def test_api_current_404_before_first_run_and_does_not_write(db):
    from fastapi import HTTPException
    from app.api import seating as seating_api

    with pytest.raises(HTTPException) as exc:
        seating_api.current(hall_id=1, db=db)
    assert exc.value.status_code == 404
    assert gen_rows(db) == []          # 读路径没有顺手排一把
    assert db.get(SeatPointer, 1) is None
