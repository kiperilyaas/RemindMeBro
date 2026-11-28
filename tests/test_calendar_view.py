"""
One calendar entry per event, and a message moves an official date only when the titles match. No AI, no database.
Run from the project folder:  .runtime/venv/bin/python -m unittest discover -s tests -v
"""
import unittest
from datetime import datetime

from app.database.models import Announcement, Deadline, Event, SourceType
from app.services.calendar_view import merge, same_event
from app.services.llm_extractor import titles_match


def deadline(i, title, when, ai=False, found_in=None, message_from=None, time_known=True, course=1):
    d = Deadline(id=i, course_id=course, title=title, due_date=datetime.fromisoformat(when), source=SourceType.MOODLE,
                 extracted_by_ai=ai, found_in=found_in, time_known=time_known)
    if message_from:
        d.announcement_id = 100 + i
        d.announcement = Announcement(id=100 + i, author=message_from, content="…", source=SourceType.EMAIL)
    return d


class OneEntryPerEvent(unittest.TestCase):
    def test_file_and_email_are_one_entry_with_the_time_of_the_email(self):
        from_file = deadline(1, "Final exam", "2026-12-18T23:59", ai=True, found_in="Prez1.pdf · page 5", time_known=False)
        from_email = deadline(2, "Final Exam", "2026-12-18T09:15", ai=True, message_from="Prof. Chiara Neri")
        out, _ = merge([from_email, from_file], [])
        self.assertEqual(len(out), 1)
        primary, also, timed = out[0]
        self.assertIs(primary, from_file)                 # the course file is more official than an email
        self.assertEqual(also, ["Outlook · Prof. Chiara Neri"])
        self.assertEqual(timed.due_date.strftime("%H:%M"), "09:15")

    def test_unisis_exam_wins_over_every_deadline_that_day(self):
        exam = Event(id=5, course_id=1, title="Exam: Written exam", kind="exam",
                     start_time=datetime(2026, 12, 16, 9, 15), end_time=datetime(2026, 12, 16, 11, 0))
        from_email = deadline(3, "Final exam", "2026-12-16T23:59", ai=True, message_from="Prof. Giovanni Verdi")
        from_file = deadline(4, "FINAL EXAM", "2026-12-16T23:59", ai=True, found_in="IM.pdf · page 1", time_known=False)
        out, event_also = merge([from_email, from_file], [exam])
        self.assertEqual(out, [])
        self.assertEqual(sorted(event_also[5]), ["Course file · IM.pdf · page 1", "Outlook · Prof. Giovanni Verdi"])

    def test_different_things_on_the_same_day_stay_apart(self):
        a = deadline(6, "Midterm II", "2026-12-15T23:59")
        b = deadline(7, "Final test", "2026-12-15T23:59", course=2)              # another course
        c = deadline(8, "Seminar paper submission", "2026-12-15T23:59")       # same course, not the same event
        out, _ = merge([a, b, c], [])
        self.assertEqual(len(out), 3)

    def test_same_event(self):
        self.assertTrue(same_event("MID TERM EXAM", "Midterm"))
        self.assertTrue(same_event("Sem Paper Presentations", "Semester paper presentations"))
        self.assertFalse(same_event("Presentation slides", "SteerCo 2 on Growth Options"))


class MovesOnlyWhenTitlesMatch(unittest.TestCase):
    def test_titles(self):
        self.assertTrue(titles_match("Problem Set 2", "problem set deadline moved"))
        self.assertFalse(titles_match("Presentation slides", "SteerCo 2 on Growth Options"))   # the real wrong move


if __name__ == "__main__":
    unittest.main()
