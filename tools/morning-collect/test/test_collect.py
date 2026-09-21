import json, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from collect import classify, parse_prev_report, msk_date  # noqa: E402

TODAY, YESTERDAY = "2026-09-21", "2026-09-20"


def task(id, type="potask", status="To Do", labels=(), due=None, assignees=(), created="2026-09-01T10:00:00Z", updated="2026-09-01T10:00:00Z", **kw):
    return {"id": id, "title": f"Задача {id}", "type": type, "status": status, "labels": list(labels), "dueDate": due,
            "assignees": list(assignees), "priority": kw.get("priority"), "milestone": kw.get("milestone"),
            "createdAt": created, "updatedAt": updated}


TASKS = [
    task("PO-1", labels=["okr-kind:task", "okr-kr:PO-78"], due="2026-09-10"),                  # просрочена 11 д
    task("PO-2", labels=["okr-kind:task"], due=TODAY),                                          # сегодня
    task("PO-3", labels=["okr-kind:task"], due="2026-09-30"),                                   # позже → в «прочее»
    task("PO-4", labels=[], due="2026-09-19"),                                                  # без kind = задача, просрочена
    task("PO-5", labels=["okr-kind:task"], status="Done", due="2026-09-11", updated="2026-09-20T21:30:00Z"),  # закрыта вчера по МСК (00:30 21.09 МСК? нет: 21:30Z = 00:30 МСК 21.09)
    task("PO-6", labels=["okr-kind:task"], status="Done", updated="2026-09-20T12:00:00Z"),      # закрыта вчера
    task("PO-10", labels=["okr-kind:control"], due="2026-09-16"),                                # просроченная договорённость
    task("PO-11", labels=["okr-kind:control"], due="2026-09-27", assignees=["@Иванов"]),        # в 7 днях
    task("PO-12", labels=["okr-kind:control"], due="2026-10-15"),                                # за горизонтом
    task("PO-13", labels=["okr-kind:control"]),                                                  # без срока → ближайшие
    task("PO-20", labels=["okr-kind:risk", "okr-kr:PO-78"], priority="high"),
    task("PO-21", labels=["okr-kind:risk", "okr-kr:PO-78"], assignees=["@Петров"]),
    task("PO-22", labels=["okr-kind:risk"]),
    task("PO-23", labels=["okr-kind:risk"], status="Done"),
    task("PO-78", type="okr", milestone="m-4"),
    task("PO-30", type="bft", status="DEEP-REVIEW"),
    task("PO-31", type="bft", status="Done"),
    task("PO-40", type="story", labels=["team:Live", "sprint:2026Q3-S5"]),
    task("PO-50", labels=["okr-kind:task"], created="2026-09-20T09:00:00Z", updated="2026-09-20T09:00:00Z"),  # заведена вчера
]


class ClassifyTest(unittest.TestCase):
    def setUp(self):
        self.d = classify(TASKS, TODAY, YESTERDAY, plan_ids=["PO-1", "PO-3", "PO-5", "PO-99"])

    def test_kpi(self):
        self.assertEqual(self.d["kpi"], {"overdue": 2, "today": 3, "risks_without_owner": 2, "closed_yesterday": 1, "overdue_controls": 1})

    def test_tasks_today_sorted_overdue_first(self):
        ids = [(t["id"], t["overdue_days"]) for t in self.d["tasks_today"]]
        self.assertEqual(ids, [("PO-1", 11), ("PO-4", 2), ("PO-2", 0)])
        self.assertEqual([t["id"] for t in self.d["tasks_later"]], ["PO-3", "PO-50"])

    def test_controls_horizon(self):
        self.assertEqual([c["id"] for c in self.d["controls_soon"]], ["PO-10", "PO-11", "PO-13"])
        self.assertEqual([c["id"] for c in self.d["controls_later"]], ["PO-12"])

    def test_risk_groups(self):
        groups = {g["kr"]: g for g in self.d["risks"]["groups"]}
        self.assertEqual(groups["PO-78"]["count"], 2)
        self.assertEqual(groups["PO-78"]["without_owner"], 1)
        self.assertEqual(groups["PO-78"]["kr_title"], "Задача PO-78")
        self.assertEqual(groups[None]["count"], 1)
        self.assertEqual(self.d["risks"]["open_total"], 3)

    def test_retro(self):
        r = self.d["retro"]
        self.assertEqual(r["counts"], {"done": 1, "moved": 1, "failed": 1, "missing": 1, "plan": 4})
        self.assertEqual({p["id"]: p["outcome"] for p in r["plan"]}, {"PO-1": "failed", "PO-3": "moved", "PO-5": "done", "PO-99": "missing"})
        self.assertEqual([t["id"] for t in r["done_yesterday"]], ["PO-6"])       # PO-5 закрыта уже 21.09 по МСК
        self.assertEqual([t["id"] for t in r["created_yesterday"]], ["PO-50"])

    def test_misc(self):
        self.assertEqual(self.d["bft"], {"open_total": 1, "by_status": {"DEEP-REVIEW": 1}})
        self.assertEqual(self.d["stories"][0]["team"], "Live")
        self.assertEqual(self.d["stories"][0]["sprint"], "2026Q3-S5")
        self.assertEqual(list(self.d["krs"]), ["PO-78"])
        self.assertEqual(self.d["totals"]["task_open"], 5)


class HelpersTest(unittest.TestCase):
    def test_msk_date(self):
        self.assertEqual(msk_date("2026-09-20T21:30:00Z"), "2026-09-21")
        self.assertEqual(msk_date("2026-09-20T20:59:00Z"), "2026-09-20")
        self.assertIsNone(msk_date(None))

    def test_parse_prev_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a" / "b" / "c" / "2026-09-11.md"
            p.parent.mkdir(parents=True)
            p.write_text("# Утро 2026-09-11\nKPI: просрочено 2 · сегодня 4 · рисков без владельца 7 · закрыто вчера 0\n\n"
                         "## Сегодня\n### Созвоны\n| Время |\n|---|\n| 11:00 |\n### Задачи\n| Задача | Кому · что | KR |\n|---|---|---|\n"
                         "| PO-99 сетевая · −1 д | — | — |\n| PO-105 смета | Бордюг | PO-78 |\n\n## Статус по командам\n| a |\n\n## Нужны решения\n- x\n")
            r = parse_prev_report(p)
        self.assertEqual(r["plan_ids"], ["PO-99", "PO-105"])
        self.assertEqual(r["date"], "2026-09-11")
        self.assertTrue(r["kpi"].startswith("KPI:"))
        self.assertEqual(r["teams_section"], "| a |")


class CliTest(unittest.TestCase):
    def test_refuses_outside_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, str(Path(__file__).parents[1] / "collect.py"), "--workspace", tmp], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("backlog/", r.stderr)


if __name__ == "__main__":
    unittest.main()
