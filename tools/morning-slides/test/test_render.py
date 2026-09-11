import subprocess, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from render import render  # noqa: E402

SAMPLE = (Path(__file__).parent / "sample.md").read_text()

class RenderTest(unittest.TestCase):
    def test_slides_and_kpis(self):
        out = render(SAMPLE)
        self.assertEqual(out.count('<section class="slide">'), 5)   # титул + 4 раздела
        self.assertIn('<b>2</b><span>просрочено</span>', out)
        self.assertIn('class="kpi red"><b>6</b>', out)
        self.assertIn('class="kpi"><b>0</b>', out)
    def test_markup(self):
        out = render(SAMPLE)
        self.assertIn('<span class="late">−1 д</span>', out)
        self.assertIn('<span class="id">PO-105</span>', out)
        self.assertIn('<td class="high">HIGH</td>', out)
        self.assertIn('class="nodata"', out)
        self.assertIn('<ul class="decisions">', out)
        self.assertIn('<p class="kr">', out)
        self.assertNotIn('---', out.split('<div class="deck">')[1].split('<section')[0])
    def test_rejects_off_template(self):
        with self.assertRaises(ValueError):
            render("просто текст без заголовков")
    def test_cli_exit_code(self):
        r = subprocess.run([sys.executable, str(Path(__file__).parents[1] / "render.py"), "/dev/null", "--stdout"], capture_output=True)
        self.assertEqual(r.returncode, 1)

if __name__ == "__main__":
    unittest.main()

class RetroTest(unittest.TestCase):
    def test_retro_widgets(self):
        import json
        data = json.loads((Path(__file__).parent / "sample.retro.json").read_text())
        out = render(SAMPLE, data)
        self.assertEqual(out.count('<label class="row" for="task-'), 2)
        self.assertEqual(out.count('<label class="row" for="event-'), 2)
        self.assertEqual(out.count('<aside class="sheet right"'), 4)   # панели отрисованы заранее, без JS
        self.assertEqual(out.count('type="radio" name="sheet"'), 5)    # 4 строки + sheet-none
        self.assertIn('<label class="edge" for="retro-note"', out)
        self.assertIn('<input class="toggle" type="checkbox" id="retro-note">', out)
        self.assertIn('<section class="slide" id="retro" data-retro>', out)
        self.assertNotIn('href="#', out)   # никаких переходов по якорям
        self.assertNotIn('retro-summary', out)
        self.assertNotIn('data-download', out)
        self.assertIn('for="task-0"><span class="check" data-done data-priority="high"></span><span class="id">PO-105</span>', out)
        self.assertIn('for="task-1"><span class="check" data-done></span><span class="t">', out)   # без id — только заголовок
        self.assertIn('<b>Источник:</b> Backlog.md: backlog/tasks/po-105', out)
    def test_source_required(self):
        bad = {"date": "2026-09-10", "tasks": [{"title": "Фикс вебхука"}], "activity": []}
        with self.assertRaises(ValueError):
            render(SAMPLE, bad)
    def test_empty_data_not_invented(self):
        out = render(SAMPLE, {"date": "2026-09-10", "tasks": [], "activity": []})
        self.assertEqual(out.count('Данных не найдено'), 3)   # два виджета + placeholder заметки
    def test_no_json_no_widgets(self):
        out = render(SAMPLE, None)
        self.assertNotIn('id="retro-note-sheet"', out)
