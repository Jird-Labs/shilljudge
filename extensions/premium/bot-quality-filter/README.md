# bot-quality-filter

**Available exclusively on the ShillJudge hosted platform.**

Applies ML-based bot detection and low-quality engagement filtering on each ingested post, going beyond the open-core low-follower heuristic. Hooks into `on_post_ingested` to adjust `low_follower_engagements` before the scoring formula runs.

Corresponds to `CORE_ENABLE_ADVANCED_BOT_FILTER=1`. The manifest here declares the hook interface; the real implementation lives in `shilljudge-premium`.

To use this feature, see [shilljudge.com](https://shilljudge.com) or contact Jird Labs for enterprise licensing.
