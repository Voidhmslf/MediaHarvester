import unittest

from tests.gui_helpers import GUI_AVAILABLE, AppHarness


@unittest.skipUnless(GUI_AVAILABLE, "нужен рабочий стол Windows")
class MouseWheelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.harness = AppHarness()
        cls.app = cls.harness.app
        cls.app.update()

    @classmethod
    def tearDownClass(cls):
        cls.harness.close()

    def setUp(self):
        self.app.show_downloader_view()
        self.app.update()
        self.canvas = self.app.main_scroll._parent_canvas
        self.canvas.yview_moveto(0)
        self.app.update()
        self.app.main_scroll._shift_pressed = False
        self.app.main_scroll._wheel_remainder = 0.0

    def wheel(self, delta, source=None, x=None, y=None):
        """Событие колеса: source — виджет, которому оно доставлено (как фокус), x/y — положение указателя."""
        source = source or self.canvas
        x = self.canvas.winfo_rootx() + 60 if x is None else x
        y = self.canvas.winfo_rooty() + 60 if y is None else y
        source.event_generate("<MouseWheel>", delta=delta, rootx=x, rooty=y)
        self.app.update()

    def test_content_is_taller_than_viewport(self):
        self.assertNotEqual(self.canvas.yview(), (0.0, 1.0), "нечего прокручивать — тест не имеет смысла")

    def test_wheel_down_scrolls_and_wheel_up_returns(self):
        self.wheel(-120)
        moved = self.canvas.yview()[0]
        self.assertGreater(moved, 0)
        self.wheel(120)
        self.assertLess(self.canvas.yview()[0], moved)

    def test_scrolls_when_focus_is_on_widget_outside_the_area(self):
        # Событие колеса приходит виджету с фокусом: кнопка закреплена вне прокручиваемой области
        self.wheel(-120, source=self.app.btn_download)
        self.assertGreater(self.canvas.yview()[0], 0)
        self.canvas.yview_moveto(0)
        self.wheel(-120, source=self.app.btn_theme)
        self.assertGreater(self.canvas.yview()[0], 0)

    def test_stuck_shift_flag_does_not_block_scrolling(self):
        # Флаг Shift залипает, когда отпускание клавиши перехватил переключатель раскладки
        self.app.main_scroll._shift_pressed = True
        self.wheel(-120)
        self.assertGreater(self.canvas.yview()[0], 0)

    def test_small_touchpad_steps_accumulate(self):
        for _ in range(12):
            self.wheel(-10)
        self.assertGreater(self.canvas.yview()[0], 0)

    def test_pointer_outside_scroll_area_does_not_scroll(self):
        header_y = self.app.lbl_header_sub.winfo_rooty()
        self.wheel(-120, y=header_y, x=self.canvas.winfo_rootx() + 60)
        self.assertEqual(self.canvas.yview()[0], 0.0)

    def test_one_notch_moves_a_visible_distance(self):
        self.wheel(-120)
        region = self.canvas.bbox("all")
        total = region[3] - region[1]
        shift = self.canvas.yview()[0] * total
        self.assertGreater(shift, 40)
        self.assertLess(shift, 140)

    def test_info_screen_scrolls_too(self):
        self.app.show_info_view()
        self.app.update()
        canvas = self.app.info_scroll._parent_canvas
        canvas.yview_moveto(0)
        self.app.update()
        self.app.btn_nav_info.event_generate(
            "<MouseWheel>", delta=-120, rootx=canvas.winfo_rootx() + 60, rooty=canvas.winfo_rooty() + 60)
        self.app.update()
        self.assertGreater(canvas.yview()[0], 0)
        # скрытый главный экран не должен реагировать
        self.assertEqual(self.app.main_scroll._parent_canvas.yview()[0], 0.0)

    def test_tracklist_textbox_scrolls_itself_when_it_overflows(self):
        self.app.combo_mode.set(next(m for m in self.app.combo_mode.cget("values") if "по списку" in m))
        self.app.on_mode_change(self.app.combo_mode.get())
        self.app.update()
        self.app.txt_tracks.insert("1.0", "\n".join(f"Artist {i} — Song {i}" for i in range(200)))
        self.app.update()
        box = self.app.txt_tracks
        self.assertNotEqual(box.yview(), (0.0, 1.0))
        x, y = box.winfo_rootx() + 40, box.winfo_rooty() + 40
        before = self.canvas.yview()[0]
        self.wheel(-120, source=box._textbox, x=x, y=y)
        self.assertEqual(self.canvas.yview()[0], before, "пока в поле есть что листать, страница стоит на месте")


if __name__ == "__main__":
    unittest.main()
