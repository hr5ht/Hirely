import io
import json
import os
from unittest.mock import patch

import PyPDF2
from django.contrib.auth.models import User
from django.test import TestCase

from ai_engine import rag
from ai_engine.brain import InterviewBrain
from ai_engine.models import Company, Job, Application, InterviewSession, UserProfile

# Tests never call Gemini: retrieval uses the keyword fallback unless a test opts in with a fake embedding
_no_embeddings = patch.dict(os.environ, {"GOOGLE_API_KEY": ""})
setUpModule, tearDownModule = _no_embeddings.start, _no_embeddings.stop


class FakeEmbeddings:
    """Maps synonyms onto the same axis, which keyword matching can't do."""
    AXES = [("kafka",), ("redis",), ("kubernetes", "k8s")]

    def _vec(self, text):
        text = text.lower()
        return [float(sum(text.count(w) for w in words)) + 0.01 for words in self.AXES]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


def make_app(username="cand"):
    user = User.objects.create_user(username, f"{username}@x.com", "pw")
    UserProfile.objects.create(user=user)
    job = Job.objects.create(company=Company.objects.create(name="Acme", domain=f"{username}.com"), title="Dev",
                             description="We need Kafka streaming and Postgres tuning. " + "filler words here " * 60)
    resume = "Built Redis caches for checkout. " + "unrelated hobby text " * 60 + " Ran Kafka consumers at scale."
    return user, Application.objects.create(job=job, candidate=user, resume_text=resume)


class RagTest(TestCase):
    def test_retrieves_relevant_chunks_from_both_docs(self):
        _, app = make_app()
        resume_ctx, jd_ctx = rag.retrieve("Kafka", app.resume_text, app.job.description, top_k=1)
        self.assertIn("Kafka consumers", resume_ctx)
        self.assertNotIn("Redis", resume_ctx)  # the Redis chunk is a different, irrelevant chunk
        self.assertIn("Kafka streaming", jd_ctx)
        self.assertEqual(rag.retrieve("anything", "", ""), ("", ""))

    def test_semantic_retrieval_matches_synonyms(self):
        resume = "Ran Kafka consumers. " + "unrelated hobby text " * 60 + " Operated Kubernetes clusters."
        jd = "Must know k8s deeply. " + "filler words here " * 60 + " Kafka is a plus."
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test"}), patch.object(rag, "GoogleGenerativeAIEmbeddings", return_value=FakeEmbeddings()):
            resume_ctx, jd_ctx = rag.retrieve("k8s experience", resume, jd, top_k=1)
        self.assertIn("Kubernetes clusters", resume_ctx)  # "k8s" query, "Kubernetes" text
        self.assertIn("k8s deeply", jd_ctx)
        self.assertEqual(rag._top_chunks({"k8s"}, resume, 1), resume[:len(rag.chunk_text(resume)[0])])  # keyword path can't: falls back to the opening chunk

    def test_falls_back_to_keywords_when_embeddings_fail(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test"}), patch.object(rag, "GoogleGenerativeAIEmbeddings", side_effect=RuntimeError("429")):
            resume_ctx, _ = rag.retrieve("Kafka", "Ran Kafka consumers.", "jd", top_k=1)
        self.assertIn("Kafka", resume_ctx)


class AtsTest(TestCase):
    def test_groq_score_is_normalised(self):
        raw = json.dumps({"score": "120", "semantic_score": 55, "skill_score": None,
                          "matching_keywords": ["python"], "improvement_suggestions": ["a", "b", "c", "d"]})
        with patch.object(InterviewBrain, "_chat", return_value=raw):
            result = InterviewBrain().get_resume_score("resume", "jd")
        self.assertEqual((result["score"], result["semantic_score"], result["skill_score"]), (100, 55, 0))
        self.assertEqual(result["feedback"], "a b c")
        self.assertEqual(result["missing_keywords"], [])


class PagesTest(TestCase):
    def test_pages_render(self):
        user, app = make_app()
        InterviewSession.objects.create(application=app, avg_confidence=80, avg_clarity=60)
        self.client.force_login(user)
        for url in ["/", "/dashboard/", "/scores/", "/profile/", "/resume-scanner/", f"/session/?app_id={app.id}"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertContains(self.client.get("/scores/"), "80")
        self.assertRedirects(self.client.get("/session/"), "/dashboard/")


class TenantTest(TestCase):
    def register(self, username, company):
        self.client.post("/register/", {"username": username, "email": f"{username}@gmail.com", "password": "pw",
                                        "role": "recruiter", "company_name": company})
        return User.objects.get(username=username)

    def test_recruiters_on_the_same_email_provider_are_isolated(self):
        a, b = self.register("ra", "Acme"), self.register("rb", "Acme")
        self.assertNotEqual(a.profile.company, b.profile.company)
        _, app = make_app("zed_applicant")
        app.job.company = a.profile.company
        app.job.save()
        self.client.force_login(b)
        self.assertNotContains(self.client.get("/dashboard/"), app.candidate.username)
        self.assertRedirects(self.client.get(f"/ai/candidate-detail/{app.id}/"), "/dashboard/")


def make_pdf(text="Python developer with Kafka experience"):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf)
    pdf.drawString(72, 720, text)
    pdf.save()
    return SimpleUploadedFile("resume.pdf", buf.getvalue(), content_type="application/pdf")


@patch.object(InterviewBrain, "get_resume_score", return_value={"score": 72})
class ApplyTest(TestCase):
    def setUp(self):
        self.user, app = make_app()
        self.job = app.job
        app.delete()

    def apply(self, **extra):
        return self.client.post("/ai/apply-to-job/", {"job_id": self.job.id, "resume": make_pdf(), **extra})

    def test_requires_login(self, _):
        self.assertEqual(self.apply().status_code, 401)

    def test_closed_job_rejects_applications(self, _):
        self.client.force_login(self.user)
        self.job.is_active = False
        self.job.save()
        res = self.apply()
        self.assertEqual(res.status_code, 400)
        self.assertIn("no longer accepting", res.json()["error"])
        self.assertEqual(self.apply(job_id="abc").status_code, 400)
        self.assertFalse(Application.objects.exists())

    def test_open_job_accepts_application(self, _):
        self.client.force_login(self.user)
        res = self.apply()
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["ats_score"], 72)
        self.assertIn("Kafka", Application.objects.get().resume_text)


class StateChangeTest(TestCase):
    def test_get_on_state_changing_urls_returns_405(self):
        user, app = make_app()
        session = InterviewSession.objects.create(application=app)
        self.client.force_login(user)
        for url in [f"/ai/update-status/{app.id}/accepted/", f"/delete-session/{session.id}/",
                    "/ai/score-resume/", f"/ai/interview/{session.id}/start/"]:
            self.assertEqual(self.client.get(url).status_code, 405, url)
        self.assertTrue(InterviewSession.objects.filter(id=session.id).exists())

    def test_posts_without_csrf_token_are_rejected(self):
        user, app = make_app()
        csrf_client = self.client_class(enforce_csrf_checks=True)
        csrf_client.force_login(user)
        self.assertEqual(csrf_client.post("/ai/score-resume/", {"jd": "x"}).status_code, 403)


@patch("ai_engine.audio_service.AudioService.text_to_speech", return_value=None)
@patch("ai_engine.brain.InterviewBrain.get_session_skills", return_value='{"tech_knowledge": 70, "gap_analysis": "Needs deeper Kafka partitioning."}')
class InterviewFlowTest(TestCase):
    def post(self, action, data=None):
        return self.client.post(f"/ai/interview/{self.session.id}/{action}/", json.dumps(data or {}), content_type="application/json")

    def setUp(self):
        user, self.app = make_app()
        self.session = InterviewSession.objects.create(application=self.app, session_status="active")
        self.client.force_login(user)

    def test_full_interview_with_proctoring(self, *_):
        feedback = json.dumps({"feedback": "Weak.", "confidence": 40, "clarity": 60, "tone": "Hesitant"})
        with patch.object(InterviewBrain, "generate_initial_question", return_value="Q1?") as first_q, \
             patch.object(InterviewBrain, "get_feedback", return_value=feedback), \
             patch.object(InterviewBrain, "get_next_question", return_value="Q2?") as next_q:
            self.assertEqual(self.post("start").json()["messages"][0]["text"], "Q1?")
            self.assertEqual(self.post("start").json()["messages"][0]["text"], "Q1?")  # reload resumes the same question
            self.assertEqual(first_q.call_count, 1)
            self.assertIn("Kafka", first_q.call_args.args[1] + first_q.call_args.args[2])  # RAG context passed

            types = [m.get("message_type", m["type"]) for m in self.post("answer", {"answer": "I used Kafka when a<b and b>c"}).json()["messages"]]
            self.assertEqual(types, ["insights_update", "silent_feedback", "question"])
            self.assertIn("Kafka consumers", next_q.call_args.args[2])  # resume chunk matching the answer

        self.post("proctor", {"type": "Face Not Detected Anomalous Event", "timestamp": "2026-10-15T12:00:00Z"})
        self.assertEqual(self.post("end").json()["messages"][0]["type"], "session_completed")

        self.session.refresh_from_db()
        self.app.refresh_from_db()
        self.assertEqual(self.session.session_status, "completed")
        self.assertEqual(len(self.session.transcript), 1)  # pending Q2 dropped
        self.assertEqual((self.session.avg_confidence, self.session.avg_clarity), (40, 60))
        self.assertEqual((self.app.proctoring_score, self.app.status), (80, "evaluated"))  # -5 reload, -15 face
        pdf_text = "".join(p.extract_text() for p in PyPDF2.PdfReader(io.BytesIO(bytes(self.session.pdf_report))).pages)
        self.assertIn("Face Not Detected", pdf_text)
        self.assertIn("Interview page reloaded", pdf_text)
        self.assertIn("Needs deeper Kafka partitioning.", pdf_text)  # gap analysis is in the report
        self.assertIn("a<b and b>c", pdf_text)  # markup-like answers no longer abort the report

    def test_ai_failure_returns_error_and_session_can_still_end(self, *_):
        with patch.object(InterviewBrain, "generate_initial_question", side_effect=RuntimeError("401")):
            res = self.post("start")
        self.assertEqual(res.status_code, 502)
        self.assertIn("AI service error", res.json()["error"])
        self.assertEqual(self.post("end").status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.session_status, "completed")
        self.assertTrue(bytes(self.session.pdf_report).startswith(b"%PDF"))

    def test_other_users_session_is_404(self, *_):
        other, _ = make_app("other")
        self.client.force_login(other)
        self.assertEqual(self.post("start").status_code, 404)
