import argparse
import unittest

from top_common import (
    WatchDisplay,
    clip_terminal_line,
    human_size,
    positive_interval,
    watch_page,
)


class WatchDisplayTests(unittest.TestCase):
    def setUp(self):
        self.output = '\n'.join(['Heading'] + [f'row {index}' for index in range(20)])

    def test_scroll_retains_header_and_reaches_last_row(self):
        page, offset, capacity = watch_page(self.output, 1000, 8)

        self.assertTrue(page.startswith('Heading\nrow 14\n'))
        self.assertIn('row 19\nRows 15-20 of 20', page)
        self.assertEqual(offset, 14)
        self.assertEqual(capacity, 6)

    def test_resize_clamps_offset_and_process_view_keeps_both_headings(self):
        output = 'Process title\n' + self.output
        page, offset, capacity = watch_page(output, 19, 12, header_lines=2)

        self.assertTrue(page.startswith('Process title\nHeading\nrow 11\n'))
        self.assertEqual(offset, 11)
        self.assertEqual(capacity, 9)

    def test_notes_stay_visible_and_do_not_count_as_rows_when_scrolling(self):
        output = self.output + '\nMemory explanation\nCache explanation'
        page, offset, capacity = watch_page(output, 1000, 8, footer_lines=2)

        self.assertTrue(page.startswith('Heading\nrow 16\n'))
        self.assertIn('row 19\nMemory explanation\nCache explanation\nRows 17-20 of 20', page)
        self.assertEqual(offset, 16)
        self.assertEqual(capacity, 4)
        self.assertEqual(len(page.splitlines()), 8)

    def test_short_terminal_keeps_a_data_row_without_scrolling_notes_into_data(self):
        output = self.output + '\nMemory explanation\nCache explanation'
        page, offset, capacity = watch_page(output, 1000, 4, footer_lines=2)

        self.assertTrue(page.startswith('Heading\nrow 19\nMemory explanation\nRows 20-20 of 20'))
        self.assertEqual(len(page.splitlines()), 4)
        self.assertEqual(offset, 19)
        self.assertEqual(capacity, 1)

    def test_navigation_moves_by_rows_and_pages_and_quits(self):
        display = WatchDisplay(enabled=False)
        display.output = self.output
        display.capacity = 6

        self.assertTrue(display.handle_key('\033[6~'))
        self.assertEqual(display.offset, 6)
        self.assertTrue(display.handle_key('k'))
        self.assertEqual(display.offset, 5)
        self.assertTrue(display.handle_key('G'))
        page, offset, _capacity = watch_page(self.output, display.offset, 8)
        self.assertEqual(offset, 14)
        self.assertIn('row 19', page)
        self.assertTrue(display.handle_key('g'))
        self.assertEqual(display.offset, 0)
        self.assertFalse(display.handle_key('q'))

    def test_styled_rows_do_not_wrap_and_reset_after_clipping(self):
        clipped = clip_terminal_line('abc\033[1mdefghijkl\033[22m', 6)
        self.assertEqual(clipped, 'abc\033[1mdef\033[0m')


class MemoryFormattingTests(unittest.TestCase):
    def test_signed_values_have_the_same_precision(self):
        self.assertEqual(human_size(512 * 1024), '512KiB')
        self.assertEqual(human_size(1536 * 1024), '1.5MiB')
        self.assertEqual(human_size(-1536 * 1024), '-1.5MiB')
        self.assertEqual(human_size(None), '?')

    def test_interval_rejects_nonfinite_values(self):
        for value in ('nan', 'inf', '-inf', '0', '-1'):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                positive_interval(value)


if __name__ == '__main__':
    unittest.main()
