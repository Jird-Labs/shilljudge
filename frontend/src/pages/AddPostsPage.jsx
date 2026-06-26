import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Trash2 } from 'lucide-react';
import { previewSubmission, confirmSubmission, ApiError } from '../api';
import Spinner from '../components/Spinner';
import TweetPreviewCard from '../components/TweetPreviewCard';

/**
 * Order previews so that each self-reply sits directly under its parent, indented.
 * A post B is a reply within the batch when it is the author's own reply
 * (in_reply_to_user_id === author_id) to a post A that was also pasted
 * (in_reply_to_post_id is present in the set). Returns [{ post, author, depth, isReply }].
 */
function orderChains(previews) {
  const byId = new Map(previews.map(p => [p.post.id, p]));
  const parentInBatch = p => {
    const post = p.post;
    return (
      post.in_reply_to_user_id &&
      post.in_reply_to_user_id === post.author_id &&
      post.in_reply_to_post_id &&
      byId.has(post.in_reply_to_post_id)
    );
  };

  const children = new Map(); // parentId -> [preview]
  const roots = [];
  for (const p of previews) {
    if (parentInBatch(p)) {
      const pid = p.post.in_reply_to_post_id;
      if (!children.has(pid)) children.set(pid, []);
      children.get(pid).push(p);
    } else {
      roots.push(p);
    }
  }

  const ordered = [];
  const visited = new Set();
  const walk = (p, depth) => {
    if (visited.has(p.post.id)) return; // guard against reply cycles
    visited.add(p.post.id);
    ordered.push({ ...p, depth, isReply: depth > 0 });
    for (const c of children.get(p.post.id) ?? []) walk(c, depth + 1);
  };
  for (const r of roots) walk(r, 0);
  for (const p of previews) if (!visited.has(p.post.id)) walk(p, 0); // orphans
  return ordered;
}

// state: idle | previewing | preview | confirming | done
export default function AddPostsPage() {
  const [input, setInput] = useState('');
  const [phase, setPhase] = useState('idle');
  const [previews, setPreviews] = useState([]);  // raw results: {status, post, author} | {status:'deleted', post_id}
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [errorCode, setErrorCode] = useState(null);

  const urls = input.split(/[\n,]+/).map(s => s.trim()).filter(Boolean);

  const okPreviews = previews.filter(p => p.status !== 'deleted' && p.post);
  const deletedPreviews = previews.filter(p => p.status === 'deleted');
  const orderedOk = orderChains(okPreviews);

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
    const postIds = orderedOk.map(p => p.post.id);  // parent-first; deleted posts excluded
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
            {okPreviews.length === 0
              ? 'No live posts to submit.'
              : okPreviews.length === 1 ? 'Confirm this post?' : `Confirm these ${okPreviews.length} posts?`}
          </p>

          {orderedOk.map(({ post, author, isReply, depth }) => (
            <div key={post.id} style={depth ? { marginLeft: `${Math.min(depth, 4) * 16}px` } : undefined}>
              <TweetPreviewCard post={post} author={author} isReply={isReply} />
            </div>
          ))}

          {deletedPreviews.map(({ post_id }) => (
            <div key={post_id} className="flex items-center gap-2 bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3 text-zinc-500 text-sm">
              <Trash2 size={14} className="shrink-0" />
              <span>Post <span className="text-zinc-400">{post_id}</span> was deleted or is unavailable — it will be skipped.</span>
            </div>
          ))}

          <div className="flex gap-3 pt-1">
            <button
              onClick={handleConfirm}
              disabled={okPreviews.length === 0}
              className="flex-1 bg-sky-500 hover:bg-sky-400 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-3 rounded-xl text-sm transition-colors"
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
