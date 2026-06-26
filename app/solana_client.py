"""Solana stake verification via JSON-RPC (Helius or any Solana RPC endpoint).

check_wallet_staked() is a deliberately isolated seam: the current implementation
checks token balance via getTokenAccountsByOwner. If the staking program escrows
tokens in a PDA (so the wallet balance shows 0), replace this function body with
a getProgramAccounts/DAS query once the staking program ID is known.
"""

from __future__ import annotations

from typing import Any

import requests

from config import get_settings

STAKED_TOKEN_MINT = "5kmutBRX7incPuyBGeF21gRE87Rbgvkica6q8zFXjups"


class SolanaCheckError(Exception):
    pass


def _rpc(method: str, params: list[Any]) -> Any:
    url = get_settings().solana_rpc_url
    if not url:
        raise SolanaCheckError("SOLANA_RPC_URL is not configured.")
    try:
        resp = requests.post(
            url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise SolanaCheckError(f"RPC request failed: {e}") from e
    body = resp.json()
    if "error" in body:
        raise SolanaCheckError(f"RPC error: {body['error']}")
    return body.get("result")


def get_token_balance(wallet: str, mint: str = STAKED_TOKEN_MINT) -> float:
    result = _rpc(
        "getTokenAccountsByOwner",
        [
            wallet,
            {"mint": mint},
            {"encoding": "jsonParsed"},
        ],
    )
    total = 0.0
    for acct in (result or {}).get("value", []):
        parsed = acct.get("account", {}).get("data", {}).get("parsed", {})
        amount = parsed.get("info", {}).get("tokenAmount", {}).get("uiAmount") or 0.0
        total += float(amount)
    return total


def check_wallet_staked(wallet: str) -> bool:
    return get_token_balance(wallet) > 0
