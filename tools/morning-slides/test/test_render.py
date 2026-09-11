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
