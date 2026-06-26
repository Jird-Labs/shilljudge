# wallet-verifier

**Available exclusively on the ShillJudge hosted platform.**

Augments the open-core token-gating check with enhanced on-chain Solana balance verification and $NRSE stake tracking. Hooks into `on_stake_check` to provide richer wallet eligibility signals.

Corresponds to `CORE_ENABLE_TOKEN_GATING=1` with premium stake logic. The manifest here declares the hook interface; the real implementation lives in `shilljudge-premium`.

To use this feature, see [shilljudge.com](https://shilljudge.com) or contact Jird Labs for enterprise licensing.
