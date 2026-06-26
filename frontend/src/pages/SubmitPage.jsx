import { useState } from 'react';
import { Link } from 'react-router-dom';
import { submitPreview, submitThread } from '../api';
import Spinner from '../components/Spinner';
import TweetPreviewCard from '../components/TweetPreviewCard';

// state: idle | previewing | preview | submitting | done
export default function SubmitPage() {
  const [url, setUrl] = useState('');
  const [phase, setPhase] = useState('idle');
  const [preview, setPreview] = useState(null);      // {post, estimated_score}
  const [duplicate, setDuplicate] = useState(null);  // existing_thread_id
  const [result, setResult] = useState(null);        // {thread_id, score}
  const [error, setError] = useState(null);

  const handlePreview = async e => {
    e.preventDefault();
    if (!url.trim()) return;
    setPhase('previewing');
    setError(null);
    setDuplicate(null);
    try {
      const data = await submitPreview(url.trim());
      if (data.status === 'duplicate') {
        setDuplicate(data.existing_thread_id);
        setPhase('idle');
        return;
      }
      setPreview(data);
      setPhase('preview');
    } catch (err) {
      setError(err.message);
      setPhase('idle');
    }
  };

  const handleSubmit = async () => {
    setPhase('submitting');
    setError(null);
    try {
      const data = await submitThread(url.trim());
      if (data.status === 'duplicate') {
        setDuplicate(data.existing_thread_id);
        setPreview(null);
        setPhase('idle');
        return;
      }
      setResult(data);
      setUrl('');
      setPreview(null);
      setPhase('done');
    } catch (err) {
      setError(err.message);
      setPhase('preview');
    }
  };

  const handleReset = () => {
    setPhase('idle');
    setPreview(null);
    setResult(null);
    setDuplicate(null);
    setError(null);
  };

  const spinning = phase === 'previewing' || phase === 'submitting';

  return (
    <div className="space-y-4">
      <h2 className="text-white font-semibold text-lg">Submit a Thread</h2>
      <p className="text-zinc-500 text-sm">Paste an X post URL — no login required.</p>

      {(phase === 'idle' || phase === 'previewing') && (
        <form onSubmit={handlePreview} className="space-y-3">
          <input
            type="text"
            value={url}
            onChange={e => setUrl(e.target.value)}
            placeholder="https://x.com/user/status/123..."
            disabled={spinning}
            className="w-full bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-white text-sm rounded-xl px-4 py-3 placeholder-zinc-600 focus:outline-none transition-colors disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={spinning || !url.trim()}
            className="w-full bg-sky-500 hover:bg-sky-400 active:bg-sky-600 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-3 rounded-xl transition-colors text-sm flex items-center justify-center gap-2"
          >
            {spinning ? <><Spinner size={16} /> Fetching preview…</> : 'Preview'}
          </button>
        </form>
      )}

      {duplicate != null && (
        <div className="text-yellow-300 text-sm bg-yellow-950/30 border border-yellow-800 rounded-xl p-3">
          This post was already submitted.{' '}
          <Link to={`/?thread=${duplicate}`} className="underline text-sky-400">View the existing thread</Link>.
        </div>
      )}

      {phase === 'preview' && preview && (
        <div className="space-y-3">
          <TweetPreviewCard
            post={preview.post}
            author={{ name: null, x_username: null, profile_image_url: null }}
          />
          <p className="text-zinc-400 text-sm">
            Estimated score:{' '}
            <span className="text-white font-semibold">{preview.estimated_score?.toFixed(1)}</span>
          </p>
          <div className="flex gap-3 pt-1">
            <button
              onClick={handleSubmit}
              className="flex-1 bg-sky-500 hover:bg-sky-400 text-white font-semibold py-3 rounded-xl text-sm transition-colors"
            >
              Confirm & Submit
            </button>
            <button
              onClick={handleReset}
              className="flex-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-semibold py-3 rounded-xl text-sm transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {phase === 'submitting' && (
        <div className="flex flex-col items-center gap-3 py-10">
          <Spinner size={32} />
          <p className="text-zinc-400 text-sm">Submitting…</p>
        </div>
      )}

      {phase === 'done' && result && (
        <div className="space-y-3">
          <div className="text-green-400 text-sm bg-green-950/40 border border-green-800 rounded-xl p-4">
            <p className="font-medium">Thread submitted!</p>
            <p className="text-green-300 text-xs mt-1">Score {result.score?.toFixed(1)}</p>
            <Link to={`/?thread=${result.thread_id}`} className="underline text-sky-400 text-xs">
              View on leaderboard
            </Link>
          </div>
          <button
            onClick={handleReset}
            className="w-full bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-medium py-2.5 rounded-xl text-sm transition-colors"
          >
            Submit another
          </button>
        </div>
      )}

      {error && (
        <div className="text-red-400 text-sm bg-red-950/40 border border-red-800 rounded-xl p-3">{error}</div>
      )}
    </div>
  );
}
