import subprocess, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from render import render  # noqa: E402

SAMPLE = (Path(__file__).parent / "sample.md").read_text()

class RenderTest(unittest.TestCase):
    def test_slides_and_kpis(self):
        out = render(SAMPLE)
        self.assertEqual(out.count('<section class="slide" data-kind='), 5)   # 5 разделов, титула нет
        self.assertEqual(out.count('<section class="slide tail"'), 1)         # хвост «Комментарии для LLM»
        self.assertNotIn('<h1>Утро', out); self.assertNotIn('class="kpi', out)
        self.assertIn('<nav class="mnav"><a href="#s-1" class="d">2026-09-11</a><a href="#s-1">Ретро</a><a href="#s-2">Сегодня</a><a href="#s-3">Риски</a><a href="#s-4">Команды</a><a href="#s-5">Решения</a></nav>', out)
        self.assertIn('<section class="slide" data-kind="retro" id="s-1"><header><div><span class="kicker">Ретро</span><h2>', out)
        self.assertIn('data-kind="decisions"', out)
        self.assertIn('id="llm-sheet"', out); self.assertIn('id="llm-prompt"', out)
    def test_markup(self):
        out = render(SAMPLE)
        self.assertIn('<span class="late">−1 д</span>', out)
        self.assertIn('<span class="id">PO-105</span>', out)
        self.assertIn('<td class="high" data-label="Приоритет">HIGH</td>', out)
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
    def data(self):
        import json
        return json.loads((Path(__file__).parent / "sample.retro.json").read_text())
    def test_retro_widgets(self):
        out = render(SAMPLE, self.data())
        self.assertEqual(out.count('<label class="row" for="task-'), 2)
        self.assertEqual(out.count('<label class="row" for="event-'), 2)
        self.assertEqual(out.count('<aside class="sheet right note"'), 4)   # панели отрисованы заранее
        self.assertEqual(out.count('type="radio" name="sheet"'), 5)         # 4 строки + sheet-none
        self.assertIn('<label class="edge" data-color="red" style="top:50%" for="retro-note"', out)
        self.assertIn('<section class="slide" data-kind="retro" id="retro" data-widgets data-retro>', out)
        self.assertIn('<label class="btn close" for="sheet-none" role="button">Закрыть</label></div></aside>', out)   # «Закрыть» внизу панели
        self.assertIn('data-section="Ретро 2026-09-10 · Tasks"', out)
        self.assertNotIn('href="#', out.split('</nav>')[1])   # якоря только в навигации, панели — не ссылки
        retro = out.split('id="retro" data-widgets data-retro>')[1].split('</section>')[0]
        self.assertEqual(out.count('id="sheet-none"'), 1)
        self.assertNotIn('<table>', retro)
        # название строки — первая строка заметки; без id — только название
        self.assertIn('for="task-0"><span class="check" data-done></span><span class="id">PO-105</span><span class="t">Ишманов + Бордюг: отправить смету за август</span>', out)
        self.assertIn('for="task-1"><span class="check" data-done></span><span class="t">Заведены 5 инициатив', out)
        # статичный рендер: заголовок-название, чеклист, раздел «Источники» внутри заметки
        self.assertIn('<h1 class="title">Ишманов + Бордюг: отправить смету за август</h1>', out)
        self.assertIn('<li class="todo"><input type="checkbox" checked><span>собрать данные за август</span></li>', out)
        self.assertIn('<h2>Источники</h2>', out)
        self.assertNotIn('class="src"><b>', out)   # отдельного блока «Источник» больше нет
        # шапка панели: чек, дата, приоритет (референс TaskSheet); noscript-баннер
        sheet0 = out.split('for="task-0">')[2].split('</aside>')[0] if out.count('for="task-0">') > 2 else out.split('<label class="row" for="task-0">')[1].split('</aside>')[0]
        self.assertIn('<span class="check" data-done', sheet0)
        self.assertIn('&#128197; Вчера</span>', sheet0)
        self.assertIn('<span class="flag" data-p="high"', sheet0)
        self.assertIn('<noscript><div class="nojs">', out)
        # заготовка ретро
        for h in ('Что было сделано', 'Как это влияет на цели спринта', 'Как это влияет на цели квартала', 'Что не получилось сделать'):
            self.assertIn(f'<h2>{h}</h2>', out)
        # markdown-исходник для редактора лежит в скрытом textarea и экранирован
        self.assertIn('<textarea class="src" hidden>Ишманов + Бордюг', out)
    def test_source_section_required(self):
        bad = {"date": "2026-09-10", "tasks": [{"note": "Фикс вебхука\n- сделано"}], "activity": []}
        with self.assertRaises(ValueError):
            render(SAMPLE, bad)
        with self.assertRaises(ValueError):
            render(SAMPLE, {"date": "2026-09-10", "tasks": [{"note": ""}], "activity": []})
    def test_empty_data_not_invented(self):
        out = render(SAMPLE, {"date": "2026-09-10", "tasks": [], "activity": []})
        self.assertEqual(out.count('<div class="empty">Данных не найдено</div>'), 2)
        self.assertIn('<h1 class="title">Ретро 2026-09-10</h1>', out)
        self.assertIn('<h2>Что не получилось сделать</h2>', out)
    def test_today_widgets(self):
        import json
        today = json.loads((Path(__file__).parent / "sample.today.json").read_text())
        out = render(SAMPLE, self.data(), today)
        self.assertIn('<section class="slide" data-kind="today" id="today" data-widgets data-today>', out)
        self.assertIn('<label class="edge" data-color="green" style="top:38%" for="plan-note"', out)
        self.assertIn('>План на сегодня</label>', out)
        self.assertIn('<label class="edge" data-color="blue" style="top:62%" for="today-calendar"', out)
        self.assertIn('id="today-calendar-sheet"', out)
        self.assertEqual(out.count('<div class="ev">'), 2)                      # календарь в панели
        self.assertIn('<div class="tt">VK: бюджет Q4</div>', out)
        slide = out.split('id="today" data-widgets data-today>')[1].split('</section>')[0]
        self.assertNotIn('Созвоны', slide)                                      # созвонов на слайде нет
        self.assertNotIn('<table>', slide)
        self.assertIn('<h4><span>Мои задачи</span><span>2</span></h4>', slide)
        self.assertIn('<h4><span>Договорённости</span><span>1</span></h4>', slide)
        self.assertIn('for="todo-0"><span class="check" data-priority="high"></span><span class="id">PO-99</span>', slide)
        self.assertIn('<h1 class="title">План на сегодня 2026-09-11</h1>', out)
        self.assertEqual(out.count('id="sheet-none"'), 1)
        self.assertIn('contenteditable="true"', out)                            # правка и без скриптов
    def load(self, name):
        import json
        return json.loads((Path(__file__).parent / name).read_text())
    def test_key_meetings(self):
        out = render(SAMPLE, self.data(), self.load("sample.today.json"))
        slide = out.split('id="today" data-widgets data-today>')[1].split('</section>')[0]
        self.assertIn('<h4><span>Мои задачи</span>', slide)
        self.assertIn('<h4><span>Ключевые встречи</span><span>1</span></h4>', slide)   # дейлик (ритуал) не попал
        self.assertIn('VK: бюджет Q4', slide); self.assertNotIn('Дейлик GDS/Live', slide)
        self.assertIn('<span class="ag">Бюджет под переезд виджета', slide)
        self.assertIn('<h2>Что получить</h2>', out)
    def test_risks_slide(self):
        out = render(SAMPLE, self.data(), None, self.load("sample.risks.json"))
        slide = out.split('id="risks" data-widgets data-risks>')[1].split('</section>')[0]
        self.assertIn('<label class="edge" data-color="amber" style="top:50%" for="risks-note"', slide)
        self.assertIn('<span>OKR</span><span>Название</span><span>Последствия</span>', slide)
        self.assertEqual(slide.count('<label class="row cols"'), 3)
        self.assertIn('<span class="t h"><span class="id">PO-78</span></span><span class="c" data-label="Название">Вебхук заказов не работает, ломает CJM у VK</span><span class="c" data-label="Последствия">заказы VK без статуса', slide)
        self.assertIn('<span class="t h">—</span>', slide)   # риск без KR
        self.assertIn('<h1 class="title">Вебхук заказов не работает, ломает CJM у VK</h1>', out)
        self.assertIn('<h2>Последствия</h2>', out); self.assertIn('<h2>Источники</h2>', out)
        self.assertIn('<h1 class="title">Актуализация рисков 2026-09-11</h1>', out)
        self.assertIn('<h2>Нужно решение</h2>', out)
    def test_team_slides(self):
        out = render(SAMPLE, self.data(), None, None, self.load("sample.teams.json"))
        self.assertEqual(out.count(' data-team>'), 2)                          # слайд на команду
        self.assertIn('<h2>Команда Live</h2>', out); self.assertIn('<h2>Команда GDS</h2>', out)
        self.assertIn('<a href="#team-0">Live</a><a href="#team-1">GDS</a>', out)
        self.assertNotIn('НЕТ ДАННЫХ: историй', out)
        live = out.split('id="team-0" data-widgets data-team>')[1].split('</section>')[0]
        self.assertIn('data-kind="team" id="team-0"', out)
        self.assertIn('<span>История</span><span>Что сделано</span><span>Что осталось</span><span>Следующий шаг</span>', live)
        self.assertIn('2026-09-15 · проверить долю ошибок &lt; 0.5% в Grafana · Юмшанов', live)
        self.assertIn('for="team-0-comment"', live); self.assertIn('for="team-0-agree"', live)
        self.assertIn('<h1 class="title">Комментарий по команде Live 2026-09-11</h1>', out)
        self.assertIn('Какие есть блокаторы: ждём спецификацию TicketsCloud', out)
        self.assertIn('<h1 class="title">Договорённости с командой Live</h1>', out)
        self.assertIn('checked><span>доступ к логам MRS · от Новиков · 2026-09-12 · для команда Live</span>', out)
        self.assertIn('<input type="checkbox"><span>схема БД Live.Процессинг · от Юмшанов · 2026-09-15 · для Ишманов</span>', out)
        self.assertIn('<h1 class="title"><span class="id">PO-133</span> Переключение 50/50 на Live.Процессинг</h1>', out)
        self.assertIn('<h2>Пульс спринта</h2>', out)
        self.assertIn('<a href="#team-0">Live</a><a href="#team-1">GDS</a><a href="#s-6">Решения</a>', out)
    def test_no_json_no_widgets(self):
        out = render(SAMPLE, None)
        self.assertNotIn('id="retro-note-sheet"', out)
        self.assertEqual(out.count('id="sheet-none"'), 1)   # хвост LLM всегда есть
    def test_md_renderer(self):
        from render import md_to_html
        h = md_to_html("Название\n# T\n- [ ] a\n- [x] b\n\n1. one\n> q\n---\n**b** `c` PO-1", first_is_title=True)
        self.assertIn('<h1 class="title">Название</h1>', h); self.assertIn('<h1>T</h1>', h)
        self.assertIn('checked><span>b</span>', h); self.assertIn('<ol><li>one</li></ol>', h)
        self.assertIn('<blockquote>q</blockquote>', h); self.assertIn('<hr>', h)
        self.assertIn('<b>b</b> <code>c</code> <span class="id">PO-1</span>', h)
        self.assertEqual(md_to_html(""), '<p class="empty">Данных не найдено</p>')

if __name__ == "__main__":
    unittest.main()
