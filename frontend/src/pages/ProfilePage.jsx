import { useState } from 'react';
import { CheckCircle, XCircle, RefreshCw } from 'lucide-react';
import { useAuth } from '../AuthContext';
import { updateWallet, recheckWallet } from '../api';

export default function ProfilePage() {
  const { xUsername, walletAddress: initialWallet, stakeVerified: initialStaked, refresh } = useAuth();
  const [wallet, setWallet] = useState(initialWallet ?? '');
  const [stakeVerified, setStakeVerified] = useState(initialStaked);
  const [saving, setSaving] = useState(false);
  const [rechecking, setRechecking] = useState(false);
  const [saveResult, setSaveResult] = useState(null);
  const [error, setError] = useState(null);

  const handleSave = async e => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSaveResult(null);
    try {
      const data = await updateWallet(wallet.trim());
      setStakeVerified(data.stake_verified);
      setSaveResult(data);
      refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleRecheck = async () => {
    setRechecking(true);
    setError(null);
    setSaveResult(null);
    try {
      const data = await recheckWallet();
      setStakeVerified(data.stake_verified);
      setSaveResult(data);
      refresh();
    } catch (err) {
      setError(err.message);
    } finally {
      setRechecking(false);
    }
  };

  return (
    <div className="space-y-6">
      <h2 className="text-white font-semibold text-lg">Profile</h2>

      <div className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-4">
        <p className="text-zinc-400 text-xs uppercase tracking-wide mb-1">X account</p>
        <p className="text-white font-medium">@{xUsername}</p>
      </div>

      <div className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-4 space-y-4">
        <div>
          <p className="text-zinc-400 text-xs uppercase tracking-wide mb-1">Stake status</p>
          {stakeVerified ? (
            <span className="inline-flex items-center gap-1.5 text-green-400 text-sm font-medium">
              <CheckCircle size={14} /> Staked
            </span>
          ) : (
            <span className="inline-flex items-center gap-1.5 text-zinc-500 text-sm">
              <XCircle size={14} /> Not staked
            </span>
          )}
        </div>

        <form onSubmit={handleSave} className="space-y-2">
          <label className="block text-zinc-400 text-xs uppercase tracking-wide">
            Solana wallet address
          </label>
          <input
            type="text"
            value={wallet}
            onChange={e => setWallet(e.target.value)}
            placeholder="Base58 public key…"
            className="w-full bg-zinc-800 border border-zinc-700 focus:border-sky-500 text-white text-sm rounded-lg px-3 py-2 placeholder-zinc-500 focus:outline-none transition-colors font-mono text-xs"
          />
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={saving || !wallet.trim()}
              className="flex-1 bg-sky-500 hover:bg-sky-400 disabled:opacity-40 text-white text-sm font-medium rounded-lg py-2 transition-colors"
            >
              {saving ? 'Saving…' : 'Save & verify'}
            </button>
            {initialWallet && (
              <button
                type="button"
                onClick={handleRecheck}
                disabled={rechecking}
                className="px-3 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40 text-zinc-300 text-sm rounded-lg py-2 transition-colors flex items-center gap-1.5"
              >
                <RefreshCw size={14} className={rechecking ? 'animate-spin' : ''} />
                Recheck
              </button>
            )}
          </div>
        </form>

        {saveResult?.check_error && (
          <p className="text-yellow-400 text-xs">
            Wallet saved, but stake check failed: {saveResult.check_error}
          </p>
        )}
      </div>

      {error && (
        <div className="text-red-400 text-sm bg-red-950/40 border border-red-800 rounded-xl p-3">
          {error}
        </div>
      )}
    </div>
  );
}
