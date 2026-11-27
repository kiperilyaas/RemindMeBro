"""
Exam dates in course files: the date reader and the checks. No AI and no network.
Run from the project folder:  .runtime/venv/bin/python -m unittest discover -s tests -v
"""
import unittest
from datetime import date

from app.services.exam_dates.dates import find_dates, find_times
from app.services.exam_dates.finder import excerpts, find_in_file, split_pages, verify


def dates(text):
    return [(d.day, d.month, d.year) for d in find_dates(text)]


def times(text):
    return [t.strftime("%H:%M") for t in find_times(text)]


class DateReader(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(dates("Final exam: 16.12.2026 at 14:00"), [(16, 12, 2026)])
        self.assertEqual(dates("Exam 16. 12. 2026"), [(16, 12, 2026)])
        self.assertEqual(dates("Mid-term progress report (3.11.)"), [(3, 11, None)])
        self.assertEqual(dates("13 16.12 FINAL EXAM"), [(16, 12, None)])
        self.assertEqual(dates("2026-12-16"), [(16, 12, 2026)])
        self.assertEqual(dates("16/12/2026 exam"), [(16, 12, 2026)])
        self.assertEqual(dates("16 December 2026"), [(16, 12, 2026)])
        self.assertEqual(dates("16th of December"), [(16, 12, None)])
        self.assertEqual(dates("December 16, 2026"), [(16, 12, 2026)])
        self.assertEqual(dates("TEST I - November 11th,"), [(11, 11, None)])
        self.assertEqual(dates("zkouška 16. prosince 2026"), [(16, 12, 2026)])
        self.assertEqual(dates("esame 16 dicembre"), [(16, 12, None)])
        self.assertEqual(dates("16.12.26"), [(16, 12, 2026)])

    def test_never_a_wrong_date(self):
        self.assertEqual(dates("05/06/2026"), [])                      # day or month first? not a date for us
        self.assertEqual(dates("exam period 16.12.-31.1."), [])        # a range, not a date
        self.assertEqual(dates("16 to 18 December"), [])
        self.assertEqual(dates("see chapter 1.2.3"), [])
        self.assertEqual(dates("31.2.2026"), [])
        self.assertEqual(dates("Week 12, end of semester, TBA"), [])
        self.assertEqual(dates("Wednesday 09.15-12.30 RB 211"), [])     # times
        self.assertEqual(dates("11. 02.12 Sem Paper Presentations"), [(2, 12, None)])   # row 11, not 11 Feb 2012
        self.assertEqual(dates("12. 09..12 Sem Paper presentations"), [])               # row 12 + a broken date
        self.assertEqual(dates("9. 18.11 MID TERM EXAM"), [(18, 11, None)])

    def test_times(self):
        self.assertEqual(times("Final exam: 16.12.2026 at 14:00"), ["14:00"])
        self.assertEqual(times("Mid-term 3.11."), [])
        self.assertEqual(times("exam period 16.12.-31.1."), [])
        self.assertEqual(times("at 2 pm"), ["14:00"])
        self.assertEqual(times("14.00 h, room NB 470"), ["14:00"])
        self.assertEqual(times("16.12. 10.00"), ["10:00"])


SYLLABUS = """[Page 1]
Week Datum Topic Lecturer
8. 11.11 Org strategy Doc. Pichanic
9. 18.11 MID TERM EXAM Doc. Pichanic
10. 25.11 Strategy 2 Dr. Pernica
13 16.12 FINAL EXAM Doc. Pichanic

[Page 2]
TEST I - chapter 1,2,3 - November 11th,
Lectures start on 23.09
"""
TODAY = date(2026, 9, 25)


class Checks(unittest.TestCase):
    pages = split_pages(SYLLABUS)

    def test_excerpts_only_with_exam_words(self):
        text = " ".join(t for _, t in excerpts(self.pages))
        self.assertIn("MID TERM EXAM", text)
        self.assertEqual(excerpts(split_pages("[Page 1]\nLectures start on 23.09\nRoom NB 470")), [])

    def test_heading_above_counts(self):
        pages = split_pages("[Page 1]\nFinal exam dates:\n16.12. 9:00 NB 470\n20.1. 9:00 NB 470")
        f, _ = verify({"kind": "exam", "date": "2026-12-16", "time": "09:00", "quote": "16.12. 9:00 NB 470", "page": "Page 1"}, pages, TODAY)
        self.assertIsNotNone(f)
        self.assertEqual(f.at_time, "09:00")

    def test_quote_must_be_in_the_file(self):
        f, why = verify({"kind": "exam", "date": "2026-12-16", "quote": "Final exam on 16.12", "page": "Page 1"}, self.pages, TODAY)
        self.assertIsNone(f)
        self.assertEqual(why, "quote not in the file")

    def test_ai_date_must_be_written_in_the_quote(self):
        f, why = verify({"kind": "exam", "date": "2026-12-17", "quote": "13 16.12 FINAL EXAM", "page": "Page 1"}, self.pages, TODAY)
        self.assertIsNone(f)
        self.assertEqual(why, "the date is not written in the quote")

    def test_good_proposal(self):
        f, _ = verify({"kind": "exam", "title": "Final exam", "date": "2026-12-16", "time": "14:00",
                       "quote": "13 16.12 FINAL EXAM Doc. Pichanic", "page": "Page 1"}, self.pages, TODAY)
        self.assertIsNotNone(f)
        self.assertEqual(f.on_date, date(2026, 12, 16))
        self.assertIsNone(f.at_time)          # 14:00 is not written in the file
        self.assertFalse(f.year_written)

    def test_mid_term_exam_is_a_midterm(self):
        f, _ = verify({"kind": "exam", "date": "2026-11-18", "quote": "9. 18.11 MID TERM EXAM Doc. Pichanic", "page": "Page 1"}, self.pages, TODAY)
        self.assertEqual(f.kind, "midterm")

    def test_kind_must_be_written(self):
        f, why = verify({"kind": "exam", "date": "2026-11-25", "quote": "10. 25.11 Strategy 2 Dr. Pernica", "page": "Page 1"}, self.pages, TODAY)
        self.assertIsNone(f)
        self.assertEqual(why, "no exam word next to the date")

    def test_past_dates_left_out(self):
        f, why = verify({"kind": "exam", "date": "2026-12-16", "quote": "13 16.12 FINAL EXAM", "page": "Page 1"}, self.pages, date(2026, 12, 20))
        self.assertIsNone(f)
        self.assertEqual(why, "in the past")

    def test_second_check_can_say_no(self):
        answers = iter(['{"items": [{"kind": "midterm", "title": "Mid term exam", "date": "2026-11-18", "quote": "9. 18.11 MID TERM EXAM", "page": "Page 1"}]}',
                        '{"answer": "no"}'])
        import json
        found, thrown, calls = find_in_file(SYLLABUS, "f.pdf", "IM", TODAY, lambda m, fast: next(answers), json.loads)
        self.assertEqual((found, thrown, calls), ([], 1, 2))

    def test_no_dates_no_ai_call(self):
        import json
        found, thrown, calls = find_in_file("[Page 1]\nThere is no final exam.", "f.pdf", "CG", TODAY, lambda m, f: 1 / 0, json.loads)
        self.assertEqual(calls, 0)


if __name__ == "__main__":
    unittest.main()
