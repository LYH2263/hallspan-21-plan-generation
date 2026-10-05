import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import Candidate, Hall, PaperSet, SeatGeneration, SeatGenerationPointer


@pytest.fixture()
def db_env():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    db = Session()
    hall = Hall(code="H101", name="一号考室", rows=5, cols=6, min_manhattan=2)
    db.add(hall)
    db.flush()
    paper_ids = []
    for code, title in (("P-A", "语文A卷"), ("P-B", "语文B卷"), ("P-C", "语文C卷")):
        p = PaperSet(code=code, title=title)
        db.add(p)
        db.flush()
        paper_ids.append(p.id)
    names = ["陈一", "李二", "张三", "赵四", "钱五", "孙六",
             "周七", "吴八", "郑九", "王十", "冯十一", "陈十二"]
    for i, name in enumerate(names):
        db.add(Candidate(hall_id=hall.id, name=name, ticket_no=f"T{2026001+i}",
                         paper_id=paper_ids[i % 3]))
    db.commit()
    hall_id = hall.id
    paper_ids = list(paper_ids)
    db.close()

    yield {"client": client, "Session": Session, "hall_id": hall_id, "paper_ids": paper_ids}

    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _generation_rows(Session, hall_id):
    db = Session()
    try:
        return db.scalars(
            select(SeatGeneration).where(SeatGeneration.hall_id == hall_id)
            .order_by(SeatGeneration.generation)
        ).all()
    finally:
        db.close()


def _pointer(Session, hall_id):
    db = Session()
    try:
        p = db.get(SeatGenerationPointer, hall_id)
        return None if p is None else p.generation
    finally:
        db.close()


def test_two_successes_leave_two_distinct_generations_pointer_latest(db_env):
    client, hall_id = db_env["client"], db_env["hall_id"]
    r1 = client.post(f"/api/seating/run?hall_id={hall_id}")
    r2 = client.post(f"/api/seating/run?hall_id={hall_id}")
    assert r1.status_code == 200 and r2.status_code == 200
    g1, g2 = r1.json()["generation"], r2.json()["generation"]
    assert g1 == 1 and g2 == 2 and g1 != g2

    rows = _generation_rows(db_env["Session"], hall_id)
    assert [r.generation for r in rows] == [1, 2]  # 连续两次成功留两代
    assert rows[0].snapshot_json != rows[1].snapshot_json or rows[0].id != rows[1].id

    latest = client.get(f"/api/seating/latest?hall_id={hall_id}").json()
    assert latest["generation"] == 2  # 指针只认最新一代
    assert _pointer(db_env["Session"], hall_id) == 2


def test_read_old_generation_returns_snapshot_only_not_recompute(db_env):
    """读旧世代只回快照：改现网最小距/名单后，旧代数字不变。"""
    client, Session, hall_id = db_env["client"], db_env["Session"], db_env["hall_id"]
    gen1 = client.post(f"/api/seating/run?hall_id={hall_id}").json()

    # 现网变更：收紧最小距 + 追加考生
    db = Session()
    hall = db.get(Hall, hall_id)
    hall.min_manhattan = 5
    db.add(Candidate(hall_id=hall_id, name="新增十三", ticket_no="T9999",
                     paper_id=db_env["paper_ids"][0]))
    db.commit()
    db.close()

    # 按世代号读旧代：必须原样回快照，绝不拿现网最小距/名单重算
    old = client.get(f"/api/seating/generations/1?hall_id={hall_id}")
    assert old.status_code == 200
    old = old.json()
    assert old["generation"] == 1
    assert old["stats"]["seated"] == gen1["stats"]["seated"]
    assert old["stats"]["unplaced"] == gen1["stats"]["unplaced"]
    assert old["stats"]["violations"] == gen1["stats"]["violations"]
    assert old["assignments"] == gen1["assignments"]
    assert old["hall"]["min_manhattan"] == 2  # 不是现网的 5

    # 纯读：没插新方案行、指针没动
    assert len(_generation_rows(Session, hall_id)) == 1
    assert _pointer(Session, hall_id) == 1


def test_read_by_generation_does_not_insert_or_move_pointer(db_env):
    client, Session, hall_id = db_env["client"], db_env["Session"], db_env["hall_id"]
    client.post(f"/api/seating/run?hall_id={hall_id}")
    client.post(f"/api/seating/run?hall_id={hall_id}")
    assert _pointer(Session, hall_id) == 2

    for _ in range(3):
        r = client.get(f"/api/seating/generations/1?hall_id={hall_id}")
        assert r.status_code == 200 and r.json()["generation"] == 1

    assert len(_generation_rows(Session, hall_id)) == 2  # 读旧代不插行
    assert _pointer(Session, hall_id) == 2               # 读旧代不改指针


def test_map_violations_stats_share_one_consistent_set_of_numbers(db_env):
    client, hall_id = db_env["client"], db_env["hall_id"]
    run = client.post(f"/api/seating/run?hall_id={hall_id}").json()
    latest = client.get(f"/api/seating/latest?hall_id={hall_id}").json()
    viols = client.get(f"/api/seating/violations?hall_id={hall_id}").json()
    stats = client.get(f"/api/seating/stats?hall_id={hall_id}").json()

    gen = run["generation"]
    assert latest["generation"] == viols["generation"] == stats["generation"] == gen
    # 排座图 / 违规列表 / 统计三处同一套已座、未排、违规数字
    assert stats["seated"] == len(latest["assignments"]) == run["stats"]["seated"]
    assert stats["unplaced"] == len(viols["unplaced"]) == run["stats"]["unplaced"]
    assert stats["violations"] == len(viols["violations"]) == run["stats"]["violations"]


def test_tampered_snapshot_makes_all_reads_fail(db_env):
    """快照对不齐：latest/violations/stats/按代读 整场失败，不回算、不拼半套。"""
    import json
    client, Session, hall_id = db_env["client"], db_env["Session"], db_env["hall_id"]
    client.post(f"/api/seating/run?hall_id={hall_id}")

    db = Session()
    row = db.scalars(select(SeatGeneration).where(SeatGeneration.hall_id == hall_id)).one()
    snap = json.loads(row.snapshot_json)
    snap["stats"]["violations"] = snap["stats"]["violations"] + 99  # 与列表长度对不上
    row.snapshot_json = json.dumps(snap, ensure_ascii=False)
    db.commit()
    db.close()

    assert client.get(f"/api/seating/latest?hall_id={hall_id}").status_code == 500
    assert client.get(f"/api/seating/violations?hall_id={hall_id}").status_code == 500
    assert client.get(f"/api/seating/stats?hall_id={hall_id}").status_code == 500
    assert client.get(f"/api/seating/generations/1?hall_id={hall_id}").status_code == 500


def test_latest_before_any_run_is_404_and_does_not_auto_run(db_env):
    client, Session, hall_id = db_env["client"], db_env["Session"], db_env["hall_id"]
    assert client.get(f"/api/seating/latest?hall_id={hall_id}").status_code == 404
    assert client.get(f"/api/seating/violations?hall_id={hall_id}").status_code == 404
    assert client.get(f"/api/seating/stats?hall_id={hall_id}").status_code == 404
    # 读路径绝不隐式排座：无世代行、无指针
    assert _generation_rows(Session, hall_id) == []
    assert _pointer(Session, hall_id) is None


def test_failed_run_leaves_no_generation_no_half_plan_pointer_unchanged(db_env, monkeypatch):
    """失败的一次：不留世代号、不留半张方案、指针不前移。"""
    from app.services import generation_store
    client, Session, hall_id = db_env["client"], db_env["Session"], db_env["hall_id"]
    client.post(f"/api/seating/run?hall_id={hall_id}")
    assert _pointer(Session, hall_id) == 1

    # 失败注入点 1：重算阶段直接炸
    monkeypatch.setattr(generation_store, "find_violations",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("engine boom")))
    r = client.post(f"/api/seating/run?hall_id={hall_id}")
    assert r.status_code == 500
    monkeypatch.undo()

    assert [r.generation for r in _generation_rows(Session, hall_id)] == [1]
    assert _pointer(Session, hall_id) == 1

    # 失败注入点 2：快照行 flush 之后、commit 时炸，半张方案必须随回滚消失
    db = Session()
    from app.models.models import Hall as _Hall
    hall = db.get(_Hall, hall_id)
    cands = [{"id": c.id, "name": c.name, "ticket_no": c.ticket_no, "paper_id": c.paper_id}
             for c in db.scalars(select(Candidate).where(Candidate.hall_id == hall_id)).all()]
    real_commit = db.commit

    def exploding_commit():
        raise RuntimeError("commit disk full")

    db.commit = exploding_commit
    with pytest.raises(RuntimeError):
        generation_store.commit_new_generation(db, hall, cands)
    db.commit = real_commit
    db.close()

    assert [r.generation for r in _generation_rows(Session, hall_id)] == [1]
    assert _pointer(Session, hall_id) == 1

    # 系统恢复后仍能正常落下一代
    r = client.post(f"/api/seating/run?hall_id={hall_id}")
    assert r.status_code == 200 and r.json()["generation"] == 2
    assert _pointer(Session, hall_id) == 2


def test_successful_run_after_list_change_is_a_new_distinct_generation(db_env):
    client, Session, hall_id = db_env["client"], db_env["Session"], db_env["hall_id"]
    g1 = client.post(f"/api/seating/run?hall_id={hall_id}").json()
    db = Session()
    db.add(Candidate(hall_id=hall_id, name="加塞考生", ticket_no="T8888",
                     paper_id=db_env["paper_ids"][1]))
    db.commit()
    db.close()
    g2 = client.post(f"/api/seating/run?hall_id={hall_id}").json()
    assert g2["generation"] == g1["generation"] + 1
    assert g2["assignments"] != g1["assignments"]
    # 旧一代仍在快照仓，且可原样读回
    old = client.get(f"/api/seating/generations/1?hall_id={hall_id}").json()
    assert old["assignments"] == g1["assignments"]
