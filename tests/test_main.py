import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path

import main


class MainTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.original_database_path = main.DATABASE_PATH
        main.DATABASE_PATH = Path(self.temp_directory.name) / "jobs.sqlite3"
        main.initialise_database()

    def tearDown(self):
        main.DATABASE_PATH = self.original_database_path
        self.temp_directory.cleanup()

    def test_jobs_ch_parser_prefers_non_empty_duplicate_title(self):
        message = EmailMessage()
        message.add_alternative(
            """
            <a href="https://www.jobs.ch/en/vacancies/detail/abc/?tracking=1"></a>
            <a href="https://www.jobs.ch/en/vacancies/detail/abc/?tracking=1">
              IT Application-Support Specialist 80-100%
            </a>
            """,
            subtype="html",
        )

        self.assertEqual(
            main.extract_jobs_ch_alert_links(message),
            [
                (
                    "https://www.jobs.ch/en/vacancies/detail/abc",
                    ("IT Application-Support Specialist 80-100%", "", ""),
                )
            ],
        )

    def test_jobs_ch_parser_extracts_company_and_location_from_row(self):
        message = EmailMessage()
        message.add_alternative(
            """
            <table><tr>
              <td><a href="https://www.jobs.ch/en/vacancies/detail/abc"> </a></td>
              <td><a href="https://www.jobs.ch/en/vacancies/detail/abc">IT Application-Support Specialist 80-100%</a></td>
              <td>Homburger AG, Zürich</td>
            </tr></table>
            """,
            subtype="html",
        )

        self.assertEqual(
            main.extract_jobs_ch_alert_links(message),
            [
                (
                    "https://www.jobs.ch/en/vacancies/detail/abc",
                    ("IT Application-Support Specialist 80-100%", "Homburger AG", "Zürich"),
                )
            ],
        )

    def test_jobs_ch_parser_extracts_labeled_metadata_and_removes_location_from_title(self):
        message = EmailMessage()
        message.add_alternative(
            """
            <table><tr><td>
              <a href="https://www.jobs.ch/en/vacancies/detail/abc">
                12 hours ago Assistent Generalagent (w/m/d) Generalagentur Dielsdorf
                Place of work : Dielsdorf Workload : 100% Contract type : Permanent position
                die Mobiliar New Is this job relevant to you?
              </a>
            </td></tr></table>
            """,
            subtype="html",
        )

        self.assertEqual(
            main.extract_jobs_ch_alert_links(message),
            [
                (
                    "https://www.jobs.ch/en/vacancies/detail/abc",
                    (
                        "Assistent Generalagent (w/m/d) Generalagentur",
                        "die Mobiliar",
                        "Dielsdorf",
                    ),
                )
            ],
        )

    def test_jobs_ch_parser_extracts_labeled_metadata_without_title_location(self):
        message = EmailMessage()
        message.add_alternative(
            """
            <a href="https://www.jobs.ch/en/vacancies/detail/def">
              Sachbearbeiter:in Administration Place of work: Wädenswil
              Workload: 80% Contract type: Permanent position Brupbacher Gatti AG New
            </a>
            """,
            subtype="html",
        )

        self.assertEqual(
            main.extract_jobs_ch_alert_links(message)[0][1],
            (
                "Sachbearbeiter:in Administration",
                "Brupbacher Gatti AG",
                "Wädenswil",
            ),
        )

    def test_database_backfills_old_jobs_ch_alert_metadata(self):
        with main.sqlite3.connect(main.DATABASE_PATH) as connection:
            connection.execute(
                "INSERT INTO jobs (link, title, source, company, location, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "https://www.jobs.ch/en/vacancies/detail/old",
                    "Sachbearbeiter:in Administration Place of work : Wädenswil "
                    "Workload : 80% Contract type : Permanent position Brupbacher Gatti AG",
                    "jobs.ch",
                    "",
                    "",
                    "ready",
                ),
            )

        main.initialise_database()

        with main.sqlite3.connect(main.DATABASE_PATH) as connection:
            stored = connection.execute(
                "SELECT title, company, location, fallback_notified_at FROM jobs WHERE link = ?",
                ("https://www.jobs.ch/en/vacancies/detail/old",),
            ).fetchone()
        self.assertEqual(
            stored,
            ("Sachbearbeiter:in Administration", "Brupbacher Gatti AG", "Wädenswil", None),
        )

    def test_linkedin_comm_url_is_canonicalized(self):
        self.assertEqual(
            main.canonicalise_link(
                "https://www.linkedin.com/comm/jobs/view/4458626465?trk=test"
            ),
            "https://www.linkedin.com/jobs/view/4458626465",
        )

    def test_linkedin_metadata_prefers_clean_title_and_extracts_company_location(self):
        links = [
            ("https://www.linkedin.com/jobs/view/123", ""),
            (
                "https://www.linkedin.com/jobs/view/123",
                "Sachbearbeiter:in Order Administration Stadler · Wallisellen / Hof, Zurich, Switzerland Actively recruiting",
            ),
            (
                "https://www.linkedin.com/jobs/view/123",
                "Sachbearbeiter:in Order Administration",
            ),
        ]

        self.assertEqual(
            main.linkedin_metadata(links, "https://www.linkedin.com/jobs/view/123"),
            (
                "Sachbearbeiter:in Order Administration",
                "Stadler",
                "Wallisellen / Hof, Zurich, Switzerland",
            ),
        )

    def test_categories_cover_configured_job_families(self):
        self.assertEqual(main.categorise_job("Software Tester"), "QA & Testing")
        self.assertEqual(main.categorise_job("Internal Auditor"), "Audit & Compliance")
        self.assertEqual(
            main.categorise_job("Data Analyst"),
            "Business Support, Sales Ops & Data",
        )
        self.assertEqual(
            main.categorise_job("Sachbearbeiterin Administration"),
            "Sachbearbeitung & Kaufmännisch",
        )

    def test_template_escapes_subject_and_summary(self):
        rendered = main.render_email(
            "Subject <unsafe>", "Summary & details", "<p>Job section</p>"
        )
        self.assertIn("Subject &lt;unsafe&gt;", rendered)
        self.assertIn("Summary &amp; details", rendered)
        self.assertNotIn("{{SUBJECT}}", rendered)

    def test_email_summary_describes_sources_and_total(self):
        rendered = main.render_email(
            "Job list",
            "Found 2 matched listings: 1 high-match role (85%+), 2 strong potential matches (75%+), and 0 additional matches.",
            "<p>Job section</p>",
        )
        self.assertIn(
            "Found 2 matched listings:",
            rendered,
        )
        self.assertIn("1 high-match role", rendered)

    def test_match_card_uses_score_class_and_application_strategy(self):
        evaluation = main.SingleJobEvaluation(
            job_index=1,
            is_relevant=True,
            match_score=92,
            job_title="Senior Office Administrator",
            company="Example AG",
            location="Wetzikon",
            pros=["Advanced Excel is relevant"],
            cons_or_gaps="German requirement should be confirmed",
            summary="Strong administrative fit.",
            application_strategy="Highlight invoice processing and Excel experience.",
        )
        card = main.render_match_card(
            {"link": "https://example.com/job"}, evaluation
        )
        self.assertIn('class="job-card high-match"', card)
        self.assertIn('class="badge badge-high"', card)
        self.assertIn("Highlight invoice processing and Excel experience.", card)

    def test_sort_matches_orders_highest_score_first(self):
        first = main.SingleJobEvaluation(
            job_index=1, is_relevant=True, match_score=75, job_title="Lower",
            company="Company", location="Zurich", pros=[], cons_or_gaps="", summary="",
        )
        second = main.SingleJobEvaluation(
            job_index=2, is_relevant=True, match_score=92, job_title="Higher",
            company="Company", location="Zurich", pros=[], cons_or_gaps="", summary="",
        )
        matches = main.sort_matches([({"link": "lower"}, first), ({"link": "higher"}, second)])
        self.assertEqual([evaluation.match_score for _, evaluation in matches], [92, 75])

    def test_job_text_removes_jobs_ch_boilerplate(self):
        cleaned = main.clean_job_text(
            "Contract type: Permanent position Brupbacher Gatti AG New "
            "Is this job relevant to you? Actual posting text"
        )
        self.assertEqual(cleaned, "Brupbacher Gatti AG Actual posting text")

    def test_jobs_ch_search_title_removes_result_metadata(self):
        title = main.clean_jobs_ch_title(
            "12 hours ago Sachbearbeiter:in Administration Place of work: "
            "Wädenswil Workload: 80% Contract type: Permanent position"
        )
        self.assertEqual(title, "Sachbearbeiter:in Administration")

    def test_fallback_notification_is_recorded_once(self):
        job = {
            "link": "https://www.jobs.ch/en/vacancies/detail/abc",
            "title": "Software Tester",
            "description": "Testing role",
        }
        main.save_alert_jobs([job])
        fallback_jobs = main.get_fallback_jobs()
        self.assertEqual(len(fallback_jobs), 1)

        main.mark_fallback_notified(fallback_jobs)

        self.assertEqual(main.get_fallback_jobs(), [])

    def test_alert_job_updates_empty_existing_title(self):
        job = {
            "link": "https://www.jobs.ch/en/vacancies/detail/abc",
            "title": "Your Job Alert for: Alert 8 is now active",
            "description": "Alert text",
        }
        main.save_alert_jobs([job])
        job["title"] = "QA Specialist"
        main.save_alert_jobs([job])

        stored = main.get_fallback_jobs()[0]
        self.assertEqual(stored["title"], "QA Specialist")


if __name__ == "__main__":
    unittest.main()
