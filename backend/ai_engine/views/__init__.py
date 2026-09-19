"""Views, split by who uses them. URLconfs import everything from here."""
from ai_engine.views.auth import healthz, home, login_view, logout_view, profile_view, register_view  # noqa: F401
from ai_engine.views.candidate import (  # noqa: F401
    apply_to_job,
    dashboard_view,
    delete_session,
    resume_scanner_view,
    review_session,
    score_resume_api,
    scores_view,
    upload_profile_resume,
)
from ai_engine.views.common import MAX_RESUME_BYTES  # noqa: F401
from ai_engine.views.interview import download_session_pdf, interview_action, session_view  # noqa: F401
from ai_engine.views.recruiter import (  # noqa: F401
    allow_retake,
    candidate_detail,
    compare_candidates,
    create_invite,
    download_candidate_resume,
    edit_job,
    export_applicants,
    post_job,
    rescore_job,
    revoke_invite,
    save_notes,
    toggle_job,
    update_application_status,
)
