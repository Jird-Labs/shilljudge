"""shilljudge-core: open-core foundation (auth primitives, contests, public scoring, leaderboard)."""

from .auth import get_current_user_from_session, require_admin
from .hooks import (
    CALCULATE_SCORE,
    ENRICH_LEADERBOARD,
    ENRICH_THREAD,
    EVENT_BUS,
    FORMAT_EXPORT,
    ON_SUBMISSION,
    UI_SLOT,
    WEBHOOK_SLOT,
    registry,
)
from .database import (
    create_contest,
    create_thread,
    delete_contest,
    delete_post,
    delete_thread,
    delete_user_data,
    get_active_contest,
    get_all_contests,
    get_all_users,
    get_contest,
    get_leaderboard,
    get_unenriched_user_ids,
    get_user,
    get_user_threads,
    init_db,
    set_wallet,
    update_contest,
    upsert_post_data,
    upsert_user_data,
    upsert_user_profile,
)
from .feature_flags import get_feature_flags
from .models import (
    ConfirmSubmissionRequest,
    CreateContestRequest,
    PreviewSubmissionRequest,
    UpdateContestRequest,
    WalletRequest,
)
from .token_storage import delete_user_token, load_user_token, save_user_token
from .utils import parse_post_id

__all__ = [
    # hooks
    "registry",
    "ON_SUBMISSION",
    "ENRICH_THREAD",
    "CALCULATE_SCORE",
    "ENRICH_LEADERBOARD",
    "FORMAT_EXPORT",
    "UI_SLOT",
    "WEBHOOK_SLOT",
    "EVENT_BUS",
    # core
    "get_feature_flags",
    "get_current_user_from_session",
    "require_admin",
    "init_db",
    "get_leaderboard",
    "create_contest",
    "get_active_contest",
    "upsert_post_data",
    "parse_post_id",
    # ... (others available for consumers)
]
