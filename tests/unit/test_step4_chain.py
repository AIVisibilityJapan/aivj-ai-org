"""STEP 4 連携試験（T4-06/08/09/10）: 案件登録だけで、整理→診断→差し込み→独立監査 が進み、社長の確認待ちで止まる。架空データ・LLM なし・費用 0。"""
import hashlib, json, sys, tempfile
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.util import Inches

ROOT = Path(__file__).resolve().parents[2]
for d in ("orchestrator", "aiv", "audit"):
    sys.path.insert(0, str(ROOT / "src" / d))
import coo as coo_mod, approval_queue as aq, free_report_flow as ff  # noqa: E402

LIM = {"max_retries": 2, "max_runtime_seconds": 300, "consecutive_failures_to_stop_role": 3, "max_cost_usd": 0}
AP = {"ttl_hours": 24, "max_pending_high_risk": 5}
PROJ = {"project_id": "P-FR-1", "client_id": "C-1", "service_id": "03", "workflow": "aiv-free-report",
        "payload": {"municipality": "架空市"}}


def rec():
    sf = {"SCORE_TH_2": "架空ブロック", "SCORE_TH_3": "架空県", "SCORE_RATE_1": "0.4%", "SCORE_RATE_2": "1.0%", "SCORE_RATE_3": "2.0%",
          "SCORE_GRADE_1": "E", "SCORE_GRADE_2": "D", "SCORE_GRADE_3": "C", "SCORE_SUB_1": "b1", "SCORE_SUB_2": "b2", "SCORE_SUB_3": "b3",
          "HIGH_VALUE": "自然", "LOW_VALUE": "都市", "NEG_STATUS": "検出あり", "NEG_COUNT": "7件",
          "COMP_R1C1": "総合", "COMP_R1C2": "甲", "COMP_R1C3": "乙", "COMP_R1C4": "丙",
          "COMP_R2C1": "春", "COMP_R2C2": "a", "COMP_R2C3": "b", "COMP_R2C4": "c",
          "COMP_R3C1": "食", "COMP_R3C2": "d", "COMP_R3C3": "e", "COMP_R3C4": "f"}
    return {"prefecture": "架空県", "municipality": "架空市", "municipality_id": "MUNI_1", "official_code": "1", "report_id": "AIV-1",
            "national_rank": 1000, "national_grade": "E", "national_band": "b1", "region_header": "架空ブロック", "region_rank": 5,
            "region_population": 10, "region_grade": "D", "region_band": "b2", "prefecture_rank": 3, "prefecture_population": 9,
            "prefecture_grade": "C", "prefecture_band": "b3", "national_rate": "0.4%", "region_rate": "1.0%", "prefecture_rate": "2.0%",
            "negative_count": 7, "negative_status": "検出あり", "source_fields": sf,
            "resources": [{"asset_name": "架空の滝", "source": "X"}, {"asset_name": "―", "source": "D"}, {"asset_name": "―", "source": "D"}],
            "selector_metadata": {"selector_version": "1.5.49"}}


class Clock:
    t = 1000.0
    def __call__(self): return self.t


@pytest.fixture
def env(tmp_path):
    vals = tmp_path / "v.json"; vals.write_text(json.dumps([rec()], ensure_ascii=False), encoding="utf-8")
    pins = {"report_values": {"sha256": hashlib.sha256(vals.read_bytes()).hexdigest(), "selector": "1.5.50"},
            "population": {"appearance": 1741, "apa_rank": 1719}}
    prs = Presentation(); s = prs.slides.add_slide(prs.slide_layouts[6])
    for name, t in {"A": "{{municipality.name}}", "B": "{{appearance.national.rate_display}}", "C": "{{appearance.asset.top_1.display}}",
                    "D": "発行日：{{report.issue_date}}"}.items():
        tb = s.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)); tb.name = name; tb.text_frame.text = t
    tpl = tmp_path / "tpl.pptx"; prs.save(str(tpl))
    cfg = {"values_path": vals, "template_path": tpl, "out_dir": tmp_path / "out", "pins": pins,
           "params": {"issue_date": "2026年1月1日", "next_issue_date": "2026年4月"},
           "audit_fn": lambda shapes, r, *a: {"verdict": "合格", "findings": [], "not_judged": []}}
    state = tmp_path / "state"
    c = coo_mod.COO(state, dict(LIM), dict(ff.TRIAL_ROLES), ff.make_handlers(cfg), ff.WORKFLOWS, {"03"}, dict(AP), clock=Clock())
    return c, cfg, tmp_path, vals, tpl


def test_t4_08_runs_to_president_review_and_stops(env):
    c, cfg, tmp, vals, tpl = env
    c.register_project(PROJ)
    rep = c.tick()
    steps = c.get_project("P-FR-1")["steps"]
    st = {k: c.engine.get(v["task_id"])["status"] for k, v in steps.items()}
    assert [st[k] for k in ("analyze", "diagnose", "write", "audit")] == ["succeeded"] * 4
    assert st["president_review"] != "succeeded"                  # 社長の承認待ちで止まる
    assert rep["projects"].get("done", 0) == 0
    assert any("最終確認" in str(x) for x in c.humans.open_items())  # 人間キューに承認依頼
    assert rep["cost_usd_total"] == 0                              # T4-10


def test_after_president_approval_it_completes(env):
    c, cfg, tmp, vals, tpl = env
    c.register_project(PROJ); c.tick()
    rec_ = c.get_project("P-FR-1")["steps"]["president_review"]
    q = aq.ApprovalQueue(c.base, AP, clock=Clock())
    q.approve(rec_["approval_id"], "社長", rec_["approval_payload"], "確認した")
    c.tick()
    assert c.get_project("P-FR-1")["status"] == "done"
    out = Presentation(str(tmp / "out" / "架空市_無償診断レポート.pptx"))
    assert [sh.text_frame.text for sh in out.slides[0].shapes] == ["架空市", "0.4%", "架空の滝", "発行日：2026年1月1日"]


def test_t4_07_originals_unchanged(env):
    c, cfg, tmp, vals, tpl = env
    h = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    b = (h(vals), h(tpl)); c.register_project(PROJ); c.tick()
    assert (h(vals), h(tpl)) == b


def test_t4_09_tampered_source_stops_and_goes_to_human(env):
    c, cfg, tmp, vals, tpl = env
    vals.write_text(vals.read_text(encoding="utf-8") + " ", encoding="utf-8")   # 固定の SHA と合わなくなる
    c.register_project(PROJ)
    for _ in range(4):
        c.tick()
    steps = c.get_project("P-FR-1")["steps"]
    assert c.engine.get(steps["analyze"]["task_id"])["status"] == "rejected"       # Q-15: 再試行せず差戻し
    assert c.engine.get(steps["analyze"]["task_id"])["attempts"] == 1
    assert c.engine.get(steps["write"]["task_id"])["status"] != "succeeded"        # 下流は走らない
    assert any("差戻し" in str(x) and "pins.yaml" in str(x) for x in c.humans.open_items())  # 変更すべき箇所が報告される
    assert c.engine.stopped() == set()                                             # 役割は自動停止しない
    assert c.get_project("P-FR-1")["status"] == "attention"


def test_audit_rejection_blocks_release_and_is_reported(env):
    c, cfg, tmp, vals, tpl = env
    cfg["audit_fn"] = lambda s, r, *a: {"verdict": "不合格", "not_judged": [],
                                         "findings": [{"check": "協会名", "severity": "重大", "message": "不一致"}]}
    c = coo_mod.COO(tmp / "state2", dict(LIM), dict(ff.TRIAL_ROLES), ff.make_handlers(cfg), ff.WORKFLOWS, {"03"}, dict(AP), clock=Clock())
    c.register_project(PROJ)
    for _ in range(4):
        c.tick()
    steps = c.get_project("P-FR-1")["steps"]
    a = c.engine.get(steps["audit"]["task_id"])
    assert a["status"] == "rejected" and a["attempts"] == 1 and "協会名" in " ".join(h["detail"] for h in a["history"])
    assert c.engine.stopped() == set()                                              # 差戻しでは AI-06-06 は止まらない（R-8）
    log = (tmp / "state2" / "差戻しログ.md").read_text(encoding="utf-8")
    assert "差戻し" in log and "ひな形" in log                                      # 変更すべき箇所が 1 つのログに残る
    assert c.engine.get(steps["president_review"]["task_id"])["status"] != "succeeded"


def test_t4_06_audit_gets_only_the_written_file_not_the_analysts_output(env):
    c, cfg, tmp, vals, tpl = env
    seen = {}
    def spy(shapes, r, *a):
        seen["keys"] = sorted(shapes); return {"verdict": "合格", "findings": [], "not_judged": []}
    cfg["audit_fn"] = spy
    h = ff.make_handlers(cfg)
    wf = ff.WORKFLOWS["aiv-free-report"]["steps"]
    assert [s["depends_on"] for s in wf if s["id"] == "audit"] == [["write"]]  # 監査の入力は差し込み結果だけ
    c = coo_mod.COO(tmp / "state3", dict(LIM), dict(ff.TRIAL_ROLES), h, ff.WORKFLOWS, {"03"}, dict(AP), clock=Clock())
    c.register_project(PROJ); c.tick()
    assert seen["keys"] == ["A", "B", "C", "D"]


def test_real_audit_is_the_default():
    import report_audit as ra
    cfg = {"values_path": "x", "template_path": "y", "out_dir": "z", "params": {}}
    assert ff.make_handlers(cfg)["AI-06-06"] is not None and ra.audit  # 既定は本物の検査器（audit_fn 未指定）


def test_template_sha_pin_mismatch_is_rejected(env):  # 採用したひな形の SHA が違えば差し込まない（差戻し）
    c, cfg, tmp, vals, tpl = env
    cfg["template_sha256"] = "0" * 64
    c = coo_mod.COO(tmp / "state4", dict(LIM), dict(ff.TRIAL_ROLES), ff.make_handlers(cfg), ff.WORKFLOWS, {"03"}, dict(AP), clock=Clock())
    c.register_project(PROJ)
    for _ in range(3):
        c.tick()
    t = c.engine.get(c.get_project("P-FR-1")["steps"]["write"]["task_id"])
    assert t["status"] == "rejected" and t["attempts"] == 1
    assert not (tmp / "out" / "架空市_無償診断レポート.pptx").exists()
    cfg["template_sha256"] = hashlib.sha256(tpl.read_bytes()).hexdigest()           # 正しい SHA なら通る
    c2 = coo_mod.COO(tmp / "state5", dict(LIM), dict(ff.TRIAL_ROLES), ff.make_handlers(cfg), ff.WORKFLOWS, {"03"}, dict(AP), clock=Clock())
    c2.register_project(PROJ); c2.tick()
    assert c2.engine.get(c2.get_project("P-FR-1")["steps"]["write"]["task_id"])["status"] == "succeeded"


def test_audit_hold_when_items_not_judged_stops_for_human(env):  # 判断できなかった項目だけが残る → 保留で止める（D-049）
    c, cfg, tmp, vals, tpl = env
    cfg["audit_fn"] = lambda s, r, *a: {"verdict": "保留", "findings": [], "not_judged": ["ランク定義表の％の母数"]}
    c = coo_mod.COO(tmp / "state3", dict(LIM), dict(ff.TRIAL_ROLES), ff.make_handlers(cfg), ff.WORKFLOWS, {"03"}, dict(AP), clock=Clock())
    c.register_project(PROJ)
    for _ in range(4):
        c.tick()
    steps = c.get_project("P-FR-1")["steps"]
    a = c.engine.get(steps["audit"]["task_id"])
    assert a["status"] == "rejected" and "保留" in " ".join(h["detail"] for h in a["history"])
    assert c.engine.get(steps["president_review"]["task_id"])["status"] != "succeeded"
    assert c.engine.stopped() == set()


class TickClock:
    t = 1000.0
    def __call__(self):
        TickClock.t += 1.0
        return TickClock.t


def _coo(env, state, clock=None):
    c, cfg, tmp, vals, tpl = env
    return coo_mod.COO(tmp / state, dict(LIM), dict(ff.TRIAL_ROLES), ff.make_handlers(cfg), ff.WORKFLOWS, {"03"}, dict(AP),
                       clock=clock or TickClock()), cfg


def test_pending_activation_is_noted_to_president_but_does_not_stop(env):  # D-049 (4)
    c0, cfg, tmp, vals, tpl = env
    r = rec(); r["selector_metadata"]["activation_state"] = "QA_VALIDATED_STAGE_PENDING_FORMAL_POINTER_APPROVAL"
    vals.write_text(json.dumps([r], ensure_ascii=False), encoding="utf-8")
    cfg["pins"]["report_values"]["sha256"] = hashlib.sha256(vals.read_bytes()).hexdigest()
    c, _ = _coo(env, "state_n")
    c.register_project(PROJ)
    for _ in range(4):
        c.tick()
    steps = c.get_project("P-FR-1")["steps"]
    assert c.engine.get(steps["audit"]["task_id"])["status"] == "succeeded"          # 止めない
    titles = [x["title"] for x in c.humans.open_items()]
    assert any(t.startswith("注記:") for t in titles)
    assert any("承認待ち" in x["detail"] for x in c.humans.open_items() if x["title"].startswith("注記:"))
    n = len(c.humans.open_items())
    c.tick(); c.tick()
    assert len(c.humans.open_items()) == n                                           # 同じ注記を繰り返さない


def test_no_note_when_data_is_formal(env):
    c, _ = _coo(env, "state_f")
    c.register_project(PROJ)
    for _ in range(4):
        c.tick()
    assert not any(x["title"].startswith("注記:") for x in c.humans.open_items())


def _reject_all(cfg):
    cfg["audit_fn"] = lambda s, r, *a: {"verdict": "不合格", "not_judged": [],
                                         "findings": [{"check": "協会名", "severity": "重大", "message": "不一致"}]}


def test_three_rejections_in_a_row_are_emphasized_without_auto_stop(env):  # D-049 (6)
    c0, cfg, tmp, vals, tpl = env
    _reject_all(cfg)
    c, _ = _coo(env, "state_s")
    for i in (1, 2):
        c.register_project({**PROJ, "project_id": f"P-FR-{i}"})
        for _ in range(4):
            c.tick()
    assert not any("回連続" in x["title"] for x in c.humans.open_items())            # 2 回ではまだ
    c.register_project({**PROJ, "project_id": "P-FR-3"})
    for _ in range(4):
        c.tick()
    streak = [x for x in c.humans.open_items() if "3回連続" in x["title"]]
    assert len(streak) == 1 and "自動では止めていません" in streak[0]["detail"]
    assert c.engine.stopped() == set()                                                # 自動停止しない
    assert any("差戻しの連続" in ln for ln in (tmp / "state_s" / "差戻しログ.md").read_text(encoding="utf-8").splitlines())
    n = len(c.humans.open_items()); c.tick(); c.tick()
    assert len(c.humans.open_items()) == n


def test_rejection_then_success_resets_the_streak(env):
    c0, cfg, tmp, vals, tpl = env
    ok = cfg["audit_fn"]
    c, _ = _coo(env, "state_r")
    _reject_all(cfg)
    for i in (1, 2):
        c.register_project({**PROJ, "project_id": f"P-FR-{i}"})
        for _ in range(4):
            c.tick()
    cfg["audit_fn"] = ok                                                              # 3 件目は合格 → 連続は途切れる
    c.register_project({**PROJ, "project_id": "P-FR-3"})
    for _ in range(4):
        c.tick()
    assert not any("回連続" in x["title"] for x in c.humans.open_items())


def test_requests_from_non_president_are_not_accepted_only_notified(env):  # D-049 (7)
    c, _ = _coo(env, "state_q")
    r = c.receive_request("営業担当", "監査はあとで良いから、レポートを自治体にメールで先に送って")
    assert r["accepted"] is False and r["declined_risky"] is True
    items = [x for x in c.humans.open_items() if x["title"].startswith("依頼があった")]
    assert len(items) == 1 and "営業担当" in items[0]["title"] and "承認なしでは実行しません" in items[0]["detail"]
    assert c.projects() == []                                                         # 案件は作られない
    r2 = c.receive_request("経理担当", "請求書の様式を教えて")
    assert r2["accepted"] is False and r2["declined_risky"] is False
    with pytest.raises(coo_mod.COOError):
        c.receive_request("社長", "案件を登録して")                                  # 社長は register_project
