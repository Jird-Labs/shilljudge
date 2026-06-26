import { useState, useEffect } from 'react';
import {
  Trash2, ChevronDown, ChevronUp, Edit2, Check, X,
  Search, ShieldCheck, ShieldOff, Ban, CircleCheck,
} from 'lucide-react';
import {
  getManageUsers, patchUser, deleteUser, getUserThreads, deletePost,
  getManageContests, createContest, updateContest, deleteContest,
} from '../api';
import { useAuth } from '../AuthContext';

const WEIGHT_FIELDS = [
  ['weight_likes', 'Likes'],
  ['weight_retweets', 'Retweets'],
  ['weight_replies', 'Replies'],
  ['weight_quotes', 'Quotes'],
  ['weight_bookmarks', 'Bookmarks'],
  ['weight_impressions', 'Impressions'],
];
const DEFAULT_WEIGHTS = Object.fromEntries(WEIGHT_FIELDS.map(([key]) => [key, 1]));

const EMPTY_FORM = {
  title: '', description: '', start_date: '', end_date: '', must_stake_token: false,
  prize: '', thread_length: 1, ...DEFAULT_WEIGHTS,
};

/** Coerce the 6 weight inputs (which arrive as strings) to numbers for the API. */
function weightsToNumbers(form) {
  return Object.fromEntries(WEIGHT_FIELDS.map(([key]) => [key, Number(form[key])]));
}

/** Six non-negative metric-weight inputs (default 1.0). Mutates form via setForm. */
function WeightInputs({ form, setForm }) {
  return (
    <div>
      <p className="text-zinc-500 text-xs mb-1.5">Metric weights</p>
      <div className="grid grid-cols-3 gap-2">
        {WEIGHT_FIELDS.map(([key, label]) => (
          <label key={key} className="flex flex-col gap-1">
            <span className="text-zinc-500 text-[11px]">{label}</span>
            <input
              type="number"
              min="0"
              max="5"
              step="0.1"
              value={form[key]}
              onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))}
              className="w-full bg-zinc-800 border border-zinc-700 text-white text-xs rounded-lg px-2 py-1.5 focus:outline-none focus:border-sky-500"
            />
          </label>
        ))}
      </div>
    </div>
  );
}

/** Compact summary of weights that differ from the 1.0 default. */
function WeightSummary({ contest }) {
  const tweaked = WEIGHT_FIELDS
    .filter(([key]) => contest[key] != null && Number(contest[key]) !== 1)
    .map(([key, label]) => `${label} ×${Number(contest[key])}`);
  if (!tweaked.length) return null;
  return <p className="text-zinc-500 text-xs mt-0.5">Weights: {tweaked.join(', ')}</p>;
}

const STATUS_STYLES = {
  active: 'bg-green-900/40 text-green-400 border border-green-800',
  upcoming: 'bg-sky-900/40 text-sky-400 border border-sky-800',
  ended: 'bg-zinc-800 text-zinc-400',
  archived: 'bg-zinc-800/60 text-zinc-600 border border-zinc-700',
};

function StakeCheckbox({ checked, onChange, disabled }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer select-none">
      <input
        type="checkbox"
        checked={checked}
        onChange={e => onChange(e.target.checked)}
        disabled={disabled}
        className="w-4 h-4 rounded accent-sky-500"
      />
      <span className="text-zinc-300 text-sm">Must stake token</span>
    </label>
  );
}

function ContestEditForm({ contest, onSave, onCancel }) {
  const [form, setForm] = useState({
    title: contest.title,
    description: contest.description ?? '',
    start_date: contest.start_date,
    end_date: contest.end_date,
    must_stake_token: !!contest.must_stake_token,
    prize: contest.prize ?? '',
    thread_length: contest.thread_length ?? 1,
    ...Object.fromEntries(WEIGHT_FIELDS.map(([key]) => [key, contest[key] ?? 1])),
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState(null);

  const handleSave = async e => {
    e.preventDefault();
    setSaving(true);
    setErr(null);
    try {
      const updated = await updateContest(contest.contest_id, {
        ...form,
        thread_length: Number(form.thread_length),
        prize: form.prize || null,
        ...weightsToNumbers(form),
      });
      onSave(updated);
    } catch (error) {
      setErr(error.message);
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSave} className="mt-3 space-y-2 border-t border-zinc-800 pt-3">
      {err && <p className="text-red-400 text-xs">{err}</p>}
      <input
        type="text"
        required
        value={form.title}
        onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
        className="w-full bg-zinc-800 border border-zinc-700 text-white text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:border-sky-500"
      />
      <div className="flex gap-2">
        <input type="date" required value={form.start_date}
          onChange={e => setForm(f => ({ ...f, start_date: e.target.value }))}
          className="flex-1 bg-zinc-800 border border-zinc-700 text-white text-xs rounded-lg px-2 py-1.5 focus:outline-none focus:border-sky-500" />
        <input type="date" required value={form.end_date}
          onChange={e => setForm(f => ({ ...f, end_date: e.target.value }))}
          className="flex-1 bg-zinc-800 border border-zinc-700 text-white text-xs rounded-lg px-2 py-1.5 focus:outline-none focus:border-sky-500" />
      </div>
      <input
        type="text"
        placeholder="Prize (optional)"
        value={form.prize}
        onChange={e => setForm(f => ({ ...f, prize: e.target.value }))}
        className="w-full bg-zinc-800 border border-zinc-700 text-white text-sm rounded-lg px-3 py-1.5 placeholder-zinc-500 focus:outline-none focus:border-sky-500"
      />
      <div className="flex items-center gap-2">
        <label className="text-zinc-500 text-xs shrink-0">Thread length</label>
        <select
          value={form.thread_length}
          onChange={e => setForm(f => ({ ...f, thread_length: Number(e.target.value) }))}
          className="bg-zinc-800 border border-zinc-700 text-white text-xs rounded-lg px-2 py-1.5 focus:outline-none focus:border-sky-500"
        >
          {[1, 3, 5, 7].map(n => <option key={n} value={n}>{n}</option>)}
        </select>
      </div>
      <WeightInputs form={form} setForm={setForm} />
      <StakeCheckbox checked={form.must_stake_token} onChange={v => setForm(f => ({ ...f, must_stake_token: v }))} />
      <div className="flex gap-2 pt-1">
        <button type="submit" disabled={saving}
          className="flex items-center gap-1 text-xs bg-sky-500 hover:bg-sky-400 disabled:opacity-50 text-white px-3 py-1.5 rounded-lg font-medium transition-colors">
          <Check size={12} />{saving ? 'Saving…' : 'Save'}
        </button>
        <button type="button" onClick={onCancel}
          className="flex items-center gap-1 text-xs bg-zinc-700 hover:bg-zinc-600 text-white px-3 py-1.5 rounded-lg font-medium transition-colors">
          <X size={12} />Cancel
        </button>
      </div>
    </form>
  );
}

function ContestsTab() {
  const [contests, setContests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const load = () => {
    setLoading(true);
    setError(null);
    getManageContests().then(setContests).catch(e => setError(e.message)).finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleCreate = async e => {
    e.preventDefault();
    setSubmitting(true);
    setFormError(null);
    try {
      await createContest({
        ...form,
        thread_length: Number(form.thread_length),
        prize: form.prize || null,
        ...weightsToNumbers(form),
      });
      setForm(EMPTY_FORM);
      load();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleArchive = async id => {
    setDeleting(true);
    try {
      await deleteContest(id);
      setConfirmDeleteId(null);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setDeleting(false);
    }
  };

  const handleEditSaved = updated => {
    setContests(cs => cs.map(c => c.contest_id === updated.contest_id ? updated : c));
    setEditingId(null);
  };

  return (
    <div className="space-y-4">
      <form onSubmit={handleCreate} className="bg-zinc-900 border border-zinc-800 rounded-xl p-4 space-y-3">
        <p className="text-white font-medium text-sm">New Contest</p>
        {formError && (
          <div className="text-red-400 text-xs bg-red-950/40 border border-red-800 rounded-lg p-2">{formError}</div>
        )}
        <input type="text" placeholder="Title" required value={form.title}
          onChange={e => setForm(f => ({ ...f, title: e.target.value }))}
          className="w-full bg-zinc-800 border border-zinc-700 text-white text-sm rounded-lg px-3 py-2 placeholder-zinc-500 focus:outline-none focus:border-sky-500" />
        <textarea placeholder="Description (optional)" rows={2} value={form.description}
          onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
          className="w-full bg-zinc-800 border border-zinc-700 text-white text-sm rounded-lg px-3 py-2 placeholder-zinc-500 focus:outline-none focus:border-sky-500 resize-none" />
        <div className="flex gap-2">
          <div className="flex-1">
            <label className="text-zinc-500 text-xs block mb-1">Start date</label>
            <input type="date" required value={form.start_date}
              onChange={e => setForm(f => ({ ...f, start_date: e.target.value }))}
              className="w-full bg-zinc-800 border border-zinc-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-sky-500" />
          </div>
          <div className="flex-1">
            <label className="text-zinc-500 text-xs block mb-1">End date</label>
            <input type="date" required value={form.end_date}
              onChange={e => setForm(f => ({ ...f, end_date: e.target.value }))}
              className="w-full bg-zinc-800 border border-zinc-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-sky-500" />
          </div>
        </div>
        <input type="text" placeholder="Prize (optional)" value={form.prize}
          onChange={e => setForm(f => ({ ...f, prize: e.target.value }))}
          className="w-full bg-zinc-800 border border-zinc-700 text-white text-sm rounded-lg px-3 py-2 placeholder-zinc-500 focus:outline-none focus:border-sky-500" />
        <div className="flex items-center gap-2">
          <label className="text-zinc-500 text-xs shrink-0">Thread length</label>
          <select value={form.thread_length}
            onChange={e => setForm(f => ({ ...f, thread_length: Number(e.target.value) }))}
            className="bg-zinc-800 border border-zinc-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:border-sky-500">
            {[1, 3, 5, 7].map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
        <WeightInputs form={form} setForm={setForm} />
        <StakeCheckbox checked={form.must_stake_token} onChange={v => setForm(f => ({ ...f, must_stake_token: v }))} />
        <button type="submit" disabled={submitting}
          className="w-full bg-sky-500 hover:bg-sky-400 disabled:opacity-50 text-white text-sm font-medium rounded-lg py-2 transition-colors">
          {submitting ? 'Creating…' : 'Create Contest'}
        </button>
      </form>

      {error && <div className="text-red-400 text-sm bg-red-950/40 border border-red-800 rounded-xl p-3">{error}</div>}
      {loading && <p className="text-zinc-500 text-sm text-center py-6">Loading…</p>}
      {!loading && !error && contests.length === 0 && <p className="text-zinc-500 text-sm text-center py-6">No contests yet.</p>}

      <ul className="space-y-2">
        {contests.map(c => {
          const isArchived = c.status === 'archived';
          return (
            <li key={c.contest_id} className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3">
              <div className="flex items-start gap-3">
                <div className="flex-1 min-w-0">
                  <p className={`font-medium text-sm ${isArchived ? 'text-zinc-500' : 'text-white'}`}>{c.title}</p>
                  {c.description && <p className="text-zinc-400 text-xs mt-0.5 line-clamp-2">{c.description}</p>}
                  <p className="text-zinc-600 text-xs mt-1">{c.start_date} – {c.end_date}</p>
                  {c.prize && <p className="text-zinc-400 text-xs mt-0.5">Prize: {c.prize}</p>}
                  {c.thread_length > 1 && <p className="text-zinc-500 text-xs mt-0.5">{c.thread_length}-post threads</p>}
                  <WeightSummary contest={c} />
                  {c.must_stake_token ? (
                    <p className="text-yellow-500 text-xs mt-0.5">Stake required</p>
                  ) : null}
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <span className={`text-xs px-2 py-0.5 rounded-full capitalize ${STATUS_STYLES[c.status] ?? STATUS_STYLES.ended}`}>
                    {c.status}
                  </span>
                  {!isArchived && (
                    <button onClick={() => setEditingId(editingId === c.contest_id ? null : c.contest_id)}
                      className="p-1.5 text-zinc-500 hover:text-sky-400 transition-colors rounded-lg hover:bg-sky-950/40">
                      <Edit2 size={14} />
                    </button>
                  )}
                  {!isArchived && (
                    confirmDeleteId === c.contest_id ? (
                      <div className="flex gap-1">
                        <button onClick={() => handleArchive(c.contest_id)} disabled={deleting}
                          className="text-xs bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white px-2 py-1 rounded-lg font-medium">
                          {deleting ? '…' : 'Archive'}
                        </button>
                        <button onClick={() => setConfirmDeleteId(null)}
                          className="text-xs bg-zinc-700 hover:bg-zinc-600 text-white px-2 py-1 rounded-lg font-medium">
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button onClick={() => setConfirmDeleteId(c.contest_id)}
                        className="p-1.5 text-zinc-600 hover:text-red-400 transition-colors rounded-lg hover:bg-red-950/40">
                        <Trash2 size={14} />
                      </button>
                    )
                  )}
                </div>
              </div>
              {!isArchived && editingId === c.contest_id && (
                <ContestEditForm contest={c} onSave={handleEditSaved} onCancel={() => setEditingId(null)} />
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function UserThreads({ xId }) {
  const [threads, setThreads] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [confirmPostId, setConfirmPostId] = useState(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    getUserThreads(xId)
      .then(setThreads)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [xId]);

  const handleDeletePost = async postId => {
    setDeleting(true);
    try {
      await deletePost(postId);
      setConfirmPostId(null);
      setThreads(ts => ts.map(t => ({
        ...t,
        posts: t.posts.filter(p => p.post_id !== postId),
      })).filter(t => t.posts.length > 0));
    } catch (err) {
      setError(err.message);
    } finally {
      setDeleting(false);
    }
  };

  if (loading) return <p className="text-zinc-500 text-xs py-3 pl-2">Loading threads…</p>;
  if (error) return <p className="text-red-400 text-xs py-3 pl-2">{error}</p>;
  if (!threads?.length) return <p className="text-zinc-500 text-xs py-3 pl-2">No threads.</p>;

  return (
    <div className="mt-3 space-y-3 border-t border-zinc-800 pt-3">
      {threads.map(t => (
        <div key={t.thread_id} className="space-y-1.5">
          <p className="text-zinc-500 text-xs">Thread · {t.post_count} post{t.post_count !== 1 ? 's' : ''} · Score {t.total_score?.toFixed(1)}</p>
          {t.posts.map(p => (
            <div key={p.post_id} className="flex items-start gap-2 bg-zinc-800 rounded-lg px-3 py-2">
              <p className="text-zinc-300 text-xs flex-1 line-clamp-2 leading-snug">{p.text || p.post_id}</p>
              {confirmPostId === p.post_id ? (
                <div className="flex gap-1 shrink-0">
                  <button onClick={() => handleDeletePost(p.post_id)} disabled={deleting}
                    className="text-xs bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white px-2 py-0.5 rounded font-medium">
                    {deleting ? '…' : 'Del'}
                  </button>
                  <button onClick={() => setConfirmPostId(null)}
                    className="text-xs bg-zinc-600 hover:bg-zinc-500 text-white px-2 py-0.5 rounded font-medium">
                    No
                  </button>
                </div>
              ) : (
                <button onClick={() => setConfirmPostId(p.post_id)}
                  className="shrink-0 p-1 text-zinc-600 hover:text-red-400 transition-colors rounded">
                  <Trash2 size={12} />
                </button>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function Avatar({ user }) {
  if (user.profile_image_url) {
    return <img src={user.profile_image_url} alt="" className="w-8 h-8 rounded-full shrink-0 object-cover" />;
  }
  const initial = (user.x_username || user.x_id || '?').charAt(0).toUpperCase();
  return (
    <div className="w-8 h-8 rounded-full shrink-0 bg-zinc-700 flex items-center justify-center text-zinc-300 text-xs font-medium">
      {initial}
    </div>
  );
}

function formatDate(value) {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString();
}

function UsersTab() {
  const { xId: currentXId } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [confirmId, setConfirmId] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [expandedId, setExpandedId] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [query, setQuery] = useState('');

  useEffect(() => {
    setLoading(true);
    setError(null);
    const handle = setTimeout(() => {
      getManageUsers(query.trim())
        .then(setUsers)
        .catch(e => setError(e.message))
        .finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(handle);
  }, [query]);

  const handlePatch = async (xId, patch) => {
    setBusyId(xId);
    setError(null);
    try {
      const updated = await patchUser(xId, patch);
      setUsers(us => us.map(u => u.x_id === xId
        ? { ...u, is_admin: updated.is_admin, participation_status: updated.participation_status }
        : u));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async xId => {
    setDeleting(true);
    try {
      await deleteUser(xId);
      setConfirmId(null);
      setUsers(us => us.filter(u => u.x_id !== xId));
    } catch (err) {
      setError(err.message);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="relative">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
        <input
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search by username…"
          className="w-full bg-zinc-900 border border-zinc-800 text-white text-sm rounded-xl pl-9 pr-3 py-2 placeholder-zinc-500 focus:outline-none focus:border-sky-500"
        />
      </div>

      {error && <div className="text-red-400 text-sm bg-red-950/40 border border-red-800 rounded-xl p-3">{error}</div>}
      {loading && <p className="text-zinc-500 text-sm text-center py-10">Loading…</p>}
      {!loading && !error && users.length === 0 && <p className="text-zinc-500 text-sm text-center py-10">No users found.</p>}

      <ul className="space-y-2">
        {users.map(user => {
          const isSelf = user.x_id === currentXId;
          const isAdmin = !!user.is_admin;
          const isSuspended = user.participation_status === 'suspended';
          const busy = busyId === user.x_id;
          const joined = formatDate(user.created_at);
          return (
            <li key={user.x_id} className="bg-zinc-900 border border-zinc-800 rounded-xl px-4 py-3">
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setExpandedId(expandedId === user.x_id ? null : user.x_id)}
                  className="flex-1 flex items-center gap-2.5 min-w-0 text-left"
                >
                  <Avatar user={user} />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <p className="text-white font-medium text-sm truncate">
                        {user.x_username ? `@${user.x_username}` : user.x_id}
                      </p>
                      {isAdmin && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-sky-900/40 text-sky-400 border border-sky-800">
                          Admin
                        </span>
                      )}
                      {isSuspended && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-red-900/40 text-red-400 border border-red-800">
                          Suspended
                        </span>
                      )}
                    </div>
                    <p className="text-zinc-500 text-xs mt-0.5">
                      {user.post_count} post{user.post_count !== 1 ? 's' : ''}
                      {user.stake_verified ? ' · staked' : ''}
                      {joined ? ` · joined ${joined}` : ''}
                    </p>
                  </div>
                  {expandedId === user.x_id ? <ChevronUp size={14} className="text-zinc-500 shrink-0" /> : <ChevronDown size={14} className="text-zinc-500 shrink-0" />}
                </button>

                <div className="flex items-center gap-1 shrink-0">
                  {!isSelf && (
                    <button
                      onClick={() => handlePatch(user.x_id, { is_admin: !isAdmin })}
                      disabled={busy}
                      className="p-2 text-zinc-600 hover:text-sky-400 disabled:opacity-50 transition-colors rounded-lg hover:bg-sky-950/40"
                      title={isAdmin ? 'Revoke admin' : 'Grant admin'}
                      aria-label={isAdmin ? `Revoke admin from ${user.x_username || user.x_id}` : `Grant admin to ${user.x_username || user.x_id}`}>
                      {isAdmin ? <ShieldOff size={16} /> : <ShieldCheck size={16} />}
                    </button>
                  )}
                  <button
                    onClick={() => handlePatch(user.x_id, { participation_status: isSuspended ? 'active' : 'suspended' })}
                    disabled={busy}
                    className={`p-2 disabled:opacity-50 transition-colors rounded-lg ${
                      isSuspended
                        ? 'text-green-500 hover:text-green-400 hover:bg-green-950/40'
                        : 'text-zinc-600 hover:text-amber-400 hover:bg-amber-950/40'
                    }`}
                    title={isSuspended ? 'Unsuspend' : 'Suspend'}
                    aria-label={isSuspended ? `Unsuspend ${user.x_username || user.x_id}` : `Suspend ${user.x_username || user.x_id}`}>
                    {isSuspended ? <CircleCheck size={16} /> : <Ban size={16} />}
                  </button>

                  {confirmId === user.x_id ? (
                    <div className="flex gap-2">
                      <button onClick={() => handleDelete(user.x_id)} disabled={deleting}
                        className="text-xs bg-red-600 hover:bg-red-500 disabled:opacity-50 text-white px-3 py-1.5 rounded-lg font-medium transition-colors">
                        {deleting ? '…' : 'Confirm'}
                      </button>
                      <button onClick={() => setConfirmId(null)}
                        className="text-xs bg-zinc-700 hover:bg-zinc-600 text-white px-3 py-1.5 rounded-lg font-medium transition-colors">
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <button onClick={() => setConfirmId(user.x_id)}
                      className="p-2 text-zinc-600 hover:text-red-400 transition-colors rounded-lg hover:bg-red-950/40"
                      aria-label={`Remove ${user.x_username || user.x_id}`}>
                      <Trash2 size={16} />
                    </button>
                  )}
                </div>
              </div>

              {expandedId === user.x_id && <UserThreads xId={user.x_id} />}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default function ManagePage() {
  const [tab, setTab] = useState('contests');

  return (
    <div className="space-y-4">
      <h2 className="text-white font-semibold text-lg">Manage</h2>

      <div className="flex gap-1 bg-zinc-900 p-1 rounded-xl">
        {['contests', 'users'].map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`flex-1 py-2 text-sm font-medium rounded-lg capitalize transition-colors ${
              tab === t ? 'bg-sky-500 text-white' : 'text-zinc-400 hover:text-zinc-200'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === 'contests' ? <ContestsTab /> : <UsersTab />}
    </div>
  );
}
