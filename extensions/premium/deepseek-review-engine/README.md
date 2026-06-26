# deepseek-review-engine

**Available exclusively on the ShillJudge hosted platform.**

Runs a DeepSeek LLM review pass after the base engagement score is computed. Adds content-quality signals (originality, factual accuracy, shill authenticity) as a weighted modifier on top of the open-core scoring formula.

Corresponds to `CORE_ENABLE_AI_SCORING=1`. The manifest here declares the hook interface; the real implementation lives in `shilljudge-premium`.

To use this feature, see [shilljudge.com](https://shilljudge.com) or contact Jird Labs for enterprise licensing.
