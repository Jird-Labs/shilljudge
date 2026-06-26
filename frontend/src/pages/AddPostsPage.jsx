import { useState } from 'react';
import { Link } from 'react-router-dom';
import { previewSubmission, confirmSubmission, ApiError } from '../api';
import Spinner from '../components/Spinner';
import TweetPreviewCard from '../components/TweetPreviewCard';

// state: idle | previewing | preview | confirming | done
export default function AddPostsPage() {
  const [input, setInput] = useState('');
  const [phase, setPhase] = useState('idle');
  const [previews, setPreviews] = useState([]);  // [{post, author}]
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [errorCode, setErrorCode] = useState(null);

  const urls = input.split(/[\n,]+/).map(s => s.trim()).filter(Boolean);

  const handlePreview = async e => {
    e.preventDefault();
    if (!urls.length) return;
    setPhase('previewing');
    setError(null);
    setErrorCode(null);
    setPreviews([]);

    const results = [];
    for (const url of urls) {
      try {
        const data = await previewSubmission(url);
        results.push(data);
      } catch (err) {
        setError(err.message);
        setErrorCode(err instanceof ApiError ? err.code : null);
        setPhase('idle');
        return;
      }
    }
    setPreviews(results);
    setPhase('preview');
  };

  const handleConfirm = async () => {
    setPhase('confirming');
    setError(null);
    setErrorCode(null);
    const postIds = previews.map(p => p.post.id);
    try {
      const data = await confirmSubmission(postIds);
      setResult(data);
      setInput('');
      setPreviews([]);
      setPhase('done');
    } catch (err) {
      setError(err.message);
      setErrorCode(err instanceof ApiError ? err.code : null);
      setPhase('preview');
    }
  };

  const handleDeny = () => {
    setPreviews([]);
    setPhase('idle');
    setError(null);
    setErrorCode(null);
  };

  const handleAddMore = () => {
    setResult(null);
    setPhase('idle');
    setError(null);
  };

  const spinning = phase === 'previewing' || phase === 'confirming';

  return (
    <div className="space-y-4">
      <h2 className="text-white font-semibold text-lg">Add Thread</h2>

      {phase === 'idle' || phase === 'previewing' ? (
        <form onSubmit={handlePreview} className="space-y-3">
          <div>
            <label className="block text-zinc-400 text-xs mb-1.5 font-medium uppercase tracking-wide">
              Post URLs
            </label>
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder={"Paste one URL per line:\nhttps://x.com/user/status/123...\nhttps://x.com/user/status/456..."}
              rows={7}
              disabled={spinning}
              className="w-full bg-zinc-900 border border-zinc-700 focus:border-sky-500 text-white text-sm rounded-xl px-4 py-3 placeholder-zinc-600 focus:outline-none resize-none transition-colors disabled:opacity-50"
            />
          </div>
          <button
            type="submit"
            disabled={spinning || !input.trim()}
            className="w-full bg-sky-500 hover:bg-sky-400 active:bg-sky-600 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-3 rounded-xl transition-colors text-sm flex items-center justify-center gap-2"
          >
            {spinning ? <><Spinner size={16} /> Fetching preview…</> : 'Preview Posts'}
          </button>
        </form>
      ) : null}

      {phase === 'preview' && previews.length > 0 && (
        <div className="space-y-3">
          <p className="text-zinc-400 text-sm">
            {previews.length === 1 ? 'Confirm this post?' : `Confirm these ${previews.length} posts?`}
          </p>
          {previews.map(({ post, author }) => (
            <TweetPreviewCard key={post.id} post={post} author={author} />
          ))}
          <div className="flex gap-3 pt-1">
            <button
              onClick={handleConfirm}
              className="flex-1 bg-sky-500 hover:bg-sky-400 text-white font-semibold py-3 rounded-xl text-sm transition-colors"
            >
              Confirm & Submit
            </button>
            <button
              onClick={handleDeny}
              className="flex-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-semibold py-3 rounded-xl text-sm transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {phase === 'confirming' && (
        <div className="flex flex-col items-center gap-3 py-10">
          <Spinner size={32} />
          <p className="text-zinc-400 text-sm">Submitting…</p>
        </div>
      )}

      {phase === 'done' && result && (
        <div className="space-y-3">
          <div className="text-green-400 text-sm bg-green-950/40 border border-green-800 rounded-xl p-4">
            <p className="font-medium">Thread submitted!</p>
            <p className="text-green-300 text-xs mt-1">
              {result.post_count} post{result.post_count !== 1 ? 's' : ''} · Score {result.total_score?.toFixed(1)}
              {result.unanalyzed?.length > 0 && (
                <span className="text-yellow-400"> · {result.unanalyzed.length} post{result.unanalyzed.length !== 1 ? 's' : ''} pending engagement analysis</span>
              )}
            </p>
          </div>
          <button
            onClick={handleAddMore}
            className="w-full bg-zinc-800 hover:bg-zinc-700 text-zinc-300 font-medium py-2.5 rounded-xl text-sm transition-colors"
          >
            Add another thread
          </button>
        </div>
      )}

      {error && (
        <div className="text-red-400 text-sm bg-red-950/40 border border-red-800 rounded-xl p-3">
          {error}
          {errorCode === 'wallet_required' && (
            <span> <Link to="/profile" className="underline text-sky-400">Set your wallet</Link> in your profile.</span>
          )}
        </div>
      )}
    </div>
  );
}
