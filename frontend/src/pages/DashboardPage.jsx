import { useState, useEffect, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw, Search, X, ArrowUp, ArrowDown, Users, FileText, Layers, Send, Clock } from 'lucide-react';
import { getLeaderboard, getStatus } from '../api';

const SORT_OPTIONS = {
  users: [
    { key: 'score', label: 'SCORE', defaultDir: 'desc' },
    { key: 'ratio', label: 'RATIO', defaultDir: 'desc' },
    { key: 'post_count', label: 'VOLUME', defaultDir: 'desc' },
    { key: 'interactions', label: 'ENGAGE', defaultDir: 'desc' },
  ],
  posts: [
    { key: 'score', label: 'SCORE', defaultDir: 'desc' },
    { key: 'ratio', label: 'RATIO', defaultDir: 'desc' },
    { key: 'created', label: 'RECENT', defaultDir: 'desc' },
  ],
  threads: [
    { key: 'score', label: 'SCORE', defaultDir: 'desc' },
    { key: 'post_count', label: 'LENGTH', defaultDir: 'desc' },
    { key: 'created', label: 'RECENT', defaultDir: 'desc' },
  ],
};

const FILTER_OPTIONS = {
  users: [
    { id: 'veterans', label: 'Veterans (5+)', pred: (e) => (e.post_count || 0) >= 5 },
    { id: 'efficient', label: 'Efficient 3%+', pred: (e) => (e.ratio || 0) >= 0.03 },
    { id: 'active', label: 'High Activity', pred: (e) => (e.total_interactions || 0) > 180 },
  ],
  posts: [
    { id: 'strong', label: 'Strong Ratio', pred: (e) => (e.ratio || 0) >= 0.04 },
    { id: 'recent', label: 'Last 7 days', pred: (e) => {
      if (!e.created_at) return false;
      const ageDays = (Date.now() - new Date(e.created_at).getTime()) / 86400000;
      return ageDays <= 7;
    }},
  ],
  threads: [
    { id: 'multi', label: 'Multi-post', pred: (e) => (e.post_count || 0) > 1 },
    { id: 'power', label: 'Power Threads', pred: (e) => (e.total_score || 0) > 90 },
  ],
};

function getSortableValue(entry, key) {
  if (!entry) return 0;
  if (key === 'score') return entry.score ?? entry.total_score ?? 0;
  if (key === 'ratio') return entry.ratio ?? 0;
  if (key === 'post_count') return entry.post_count ?? 0;
  if (key === 'interactions') return entry.total_interactions ?? 0;
  if (key === 'created') return entry.created_at ? new Date(entry.created_at).getTime() : 0;
  return entry.score ?? entry.total_score ?? 0;
}

function getScoreForRail(entry) {
  return entry.score ?? entry.total_score ?? 0;
}

function fmtDate(d) {
  if (!d) return '';
  try {
    return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } catch {
    return '';
  }
}

function fmtLastUpdated(iso) {
  if (!iso) return 'Not yet polled';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return 'Not yet polled';
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return 'just now';
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function UsersList({ entries = [], maxScore = 1 }) {
  if (!entries.length) return null;
  return (
    <ol className="space-y-2">
      {entries.map((entry, i) => {
        const username = entry.x_username || entry.x_id;
        const score = entry.score || 0;
        const rel = maxScore > 0 ? Math.min(1, score / maxScore) : 0;
        const isTop = i < 3;
        const rankColor = i === 0 ? 'text-amber-400' : i === 1 ? 'text-zinc-200' : i === 2 ? 'text-amber-600' : 'text-zinc-600';
        return (
          <li key={entry.x_id} className="list-item group relative bg-zinc-950 border border-zinc-800 rounded-2xl px-4 py-3.5 pb-4 flex gap-3.5">
            <div className={`rank-stamp w-7 shrink-0 flex items-center justify-center text-[17px] font-black tabular-nums tracking-[-1.5px] pt-px rounded-xl ring-1 ring-offset-2 ring-offset-zinc-950 transition-colors ${isTop ? (i === 0 ? 'bg-amber-950/60 ring-amber-400/50' : i === 1 ? 'bg-zinc-900 ring-zinc-300/40' : 'bg-amber-950/40 ring-amber-600/30') : 'ring-transparent'} ${rankColor}`}>
              {i + 1}
            </div>
            <div className="flex-1 min-w-0 space-y-1">
              <p className="text-white font-semibold text-[15px] tracking-[-0.2px] truncate">
                @{username}
              </p>
              <div className="metric flex items-center gap-x-2 text-[10px] font-mono text-zinc-500 tracking-[0.2px]">
                <span>{entry.post_count || 0} POSTS</span>
                <span className="text-zinc-700">·</span>
                <span>{(entry.total_interactions || 0).toLocaleString()} INT</span>
                <span className="text-zinc-700">·</span>
                <span>{(entry.total_impressions || 0).toLocaleString()} IMP</span>
              </div>
              <div className="flex items-center gap-1.5 text-[10px]">
                <span className="font-mono text-emerald-400/90 tracking-tight">{((entry.ratio || 0) * 100).toFixed(1)}% RATIO</span>
              </div>
            </div>
            <div className="text-right shrink-0 tabular-nums">
              <div className="score-value text-2xl font-semibold text-sky-400 leading-none tracking-[-1.2px]">{score.toFixed(1)}</div>
              <div className="text-[9px] text-zinc-600 font-medium mt-px">SCORE</div>
            </div>
            <div className="absolute bottom-0 left-4 right-4 h-px bg-zinc-800 rounded">
              <div className={`rail h-px rounded ${isTop ? 'bg-sky-400 shadow-[0_0_6px_rgb(56,189,248,0.6)]' : 'bg-sky-400/90'}`} style={{ width: `${rel * 100}%` }} />
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function PostsList({ entries = [], maxScore = 1 }) {
  if (!entries.length) return null;
  return (
    <ol className="space-y-2">
      {entries.map((entry, i) => {
        const score = entry.score || 0;
        const rel = maxScore > 0 ? Math.min(1, score / maxScore) : 0;
        const isTop = i < 3;
        const rankColor = i === 0 ? 'text-amber-400' : i === 1 ? 'text-zinc-200' : i === 2 ? 'text-amber-600' : 'text-zinc-600';
        return (
          <li key={entry.post_id} className="list-item group relative bg-zinc-950 border border-zinc-800 rounded-2xl px-4 py-3.5 pb-4 flex gap-3.5">
            <div className={`rank-stamp w-7 shrink-0 flex items-center justify-center text-[17px] font-black tabular-nums tracking-[-1.5px] pt-px rounded-xl ring-1 ring-offset-2 ring-offset-zinc-950 transition-colors ${isTop ? (i === 0 ? 'bg-amber-950/60 ring-amber-400/50' : i === 1 ? 'bg-zinc-900 ring-zinc-300/40' : 'bg-amber-950/40 ring-amber-600/30') : 'ring-transparent'} ${rankColor}`}>
              {i + 1}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[10px] text-zinc-400 font-mono tracking-[0.5px] mb-px">
                @{entry.x_username || entry.x_id}
              </p>
              <p className="text-white text-[13.5px] leading-snug line-clamp-3 pr-1">
                {entry.text || '—'}
              </p>
              <div className="mt-1.5 flex items-center gap-2 text-[10px] text-zinc-500 font-mono tracking-tight">
                {fmtDate(entry.created_at) && <span>{fmtDate(entry.created_at)}</span>}
                <span className="text-emerald-400/90">{((entry.ratio || 0) * 100).toFixed(1)}%</span>
              </div>
            </div>
            <div className="text-right shrink-0 tabular-nums">
              <div className="score-value text-2xl font-semibold text-sky-400 leading-none tracking-[-1.2px]">{score.toFixed(1)}</div>
              <div className="text-[9px] text-zinc-600 font-medium mt-px">SCORE</div>
            </div>
            <div className="absolute bottom-0 left-4 right-4 h-px bg-zinc-800 rounded">
              <div className={`rail h-px rounded ${isTop ? 'bg-sky-400 shadow-[0_0_6px_rgb(56,189,248,0.6)]' : 'bg-sky-400/90'}`} style={{ width: `${rel * 100}%` }} />
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function ThreadsList({ entries = [], maxScore = 1 }) {
  if (!entries.length) return null;
  return (
    <ol className="space-y-2">
      {entries.map((entry, i) => {
        const rank = entry.rank ?? i + 1;
        const score = entry.score ?? entry.total_score ?? 0;
        const rel = maxScore > 0 ? Math.min(1, score / maxScore) : 0;
        const isTop = rank <= 3;
        const rankColor = rank === 1 ? 'text-amber-400' : rank === 2 ? 'text-zinc-200' : rank === 3 ? 'text-amber-600' : 'text-zinc-600';
        return (
          <li key={entry.thread_id} className="list-item group relative bg-zinc-950 border border-zinc-800 rounded-2xl px-4 py-3.5 pb-4 flex gap-3.5">
            <div className={`rank-stamp min-w-7 px-1 shrink-0 flex items-center justify-center text-[17px] font-black tabular-nums tracking-[-1.5px] pt-px rounded-xl ring-1 ring-offset-2 ring-offset-zinc-950 transition-colors ${isTop ? (rank === 1 ? 'bg-amber-950/60 ring-amber-400/50' : rank === 2 ? 'bg-zinc-900 ring-zinc-300/40' : 'bg-amber-950/40 ring-amber-600/30') : 'ring-transparent'} ${rankColor}`}>
              {rank}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-[10px] text-zinc-400 font-mono tracking-[0.5px] mb-px">
                @{entry.x_username || entry.x_id}
              </p>
              <p className="text-white text-[13.5px] leading-snug line-clamp-3 pr-1">
                {entry.top_text || '—'}
              </p>
              <div className="mt-1.5 text-[10px] font-mono text-zinc-500 tracking-tight">
                {entry.post_count || 0} POST{(entry.post_count || 0) === 1 ? '' : 'S'}
              </div>
            </div>
            <div className="text-right shrink-0 tabular-nums">
              {entry.is_overridden && (
                <div
                  className="inline-flex items-center gap-1 mb-1 px-1.5 py-0.5 rounded-full bg-amber-950/60 border border-amber-700/50 text-amber-400 text-[8.5px] font-semibold tracking-[0.5px] not-tabular"
                  title="Score manually set by an admin"
                >
                  ✎ ADMIN
                </div>
              )}
              <div className="score-value text-2xl font-semibold text-sky-400 leading-none tracking-[-1.2px]">{score.toFixed(1)}</div>
              <div className="text-[9px] text-zinc-600 font-medium mt-px">SCORE</div>
            </div>
            <div className="absolute bottom-0 left-4 right-4 h-px bg-zinc-800 rounded">
              <div className={`rail h-px rounded ${isTop ? 'bg-sky-400 shadow-[0_0_6px_rgb(56,189,248,0.6)]' : 'bg-sky-400/90'}`} style={{ width: `${rel * 100}%` }} />
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function ListSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="bg-zinc-950 border border-zinc-800 rounded-2xl px-4 py-4">
          <div className="flex gap-3.5">
            <div className="skeleton w-7 h-7 rounded-xl" />
            <div className="flex-1 space-y-2 pt-0.5">
              <div className="skeleton h-3.5 w-2/5 rounded" />
              <div className="skeleton h-2.5 w-4/5 rounded" />
              <div className="skeleton h-2 w-1/3 rounded" />
            </div>
            <div className="skeleton w-11 h-6 rounded self-start mt-0.5" />
          </div>
          <div className="mt-3 h-px bg-zinc-800">
            <div className="skeleton h-px w-[62%] rounded" />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState('users');

  // Filtering + sorting state
  const [search, setSearch] = useState('');
  const [sortBy, setSortBy] = useState('score');
  const [sortDir, setSortDir] = useState('desc');
  const [filterIds, setFilterIds] = useState([]);

  const load = () => {
    setLoading(true);
    setError(null);
    // The threads rail is sorted + paginated server-side; pull the full first page
    // and stamp each thread with its leaderboard rank (offset + index + 1).
    getLeaderboard({ sort: sortBy, dir: sortDir, limit: 100, offset: 0 })
      .then((d) => {
        const off = d.offset || 0;
        const threads = (d.threads || []).map((t, i) => ({ ...t, rank: off + i + 1 }));
        setData({ ...d, threads });
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
    getStatus().then(setStatus).catch(() => setStatus(null));
  };

  // (Re)load whenever the sort changes — threads come back server-ordered.
  useEffect(load, [sortBy, sortDir]);

  // Reset controls to sensible defaults when switching divisions
  useEffect(() => {
    setSearch('');
    setFilterIds([]);
    setSortBy('score');
    setSortDir('desc');
  }, [tab]);

  const currentEntries = data
    ? (tab === 'users' ? data.users : tab === 'posts' ? data.posts : data.threads) ?? []
    : [];

  const processed = useMemo(() => {
    let items = [...currentEntries];

    const q = search.trim().toLowerCase();
    if (q) {
      items = items.filter((entry) => {
        const u = (entry.x_username || entry.x_id || '').toLowerCase();
        if (u.includes(q)) return true;
        if (tab === 'posts' && (entry.text || '').toLowerCase().includes(q)) return true;
        if (tab === 'threads' && (entry.top_text || '').toLowerCase().includes(q)) return true;
        return false;
      });
    }

    const activeFilters = FILTER_OPTIONS[tab] || [];
    const activePreds = filterIds
      .map((id) => activeFilters.find((f) => f.id === id)?.pred)
      .filter(Boolean);

    if (activePreds.length) {
      items = items.filter((entry) => activePreds.every((pred) => pred(entry)));
    }

    // Threads are sorted server-side (override-aware); only client-sort the
    // supplementary users/posts rails. Search + quick filters preserve rank order.
    if (tab !== 'threads') {
      const dirMul = sortDir === 'asc' ? 1 : -1;
      items.sort((a, b) => {
        const va = getSortableValue(a, sortBy);
        const vb = getSortableValue(b, sortBy);
        if (va === vb) return 0;
        return (va > vb ? 1 : -1) * dirMul;
      });
    }

    return items;
  }, [currentEntries, search, filterIds, sortBy, sortDir, tab]);

  const maxScore = processed.length
    ? Math.max(...processed.map(getScoreForRail))
    : 1;

  const originalCount = currentEntries.length;

  const currentSortOptions = SORT_OPTIONS[tab] || [];
  const currentFilterOptions = FILTER_OPTIONS[tab] || [];
  const activeSort = currentSortOptions.find((o) => o.key === sortBy);
  const sortLabel = activeSort ? activeSort.label : 'SCORE';

  const handleTabChange = (t) => setTab(t);

  const handleSortClick = (opt) => {
    if (sortBy === opt.key) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortBy(opt.key);
      setSortDir(opt.defaultDir);
    }
  };

  const toggleFilter = (id) => {
    setFilterIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const clearFilters = () => {
    setSearch('');
    setFilterIds([]);
  };

  return (
    <div className="space-y-5">
      {/* Page header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="font-mono uppercase tracking-[4px] text-[10px] text-zinc-600">PRECISION ARENA</div>
          <h2 className="text-white font-semibold text-[22px] tracking-[-0.4px] leading-none mt-px">Leaderboard</h2>
          <div className="flex items-center gap-1.5 mt-2 text-[10px] font-mono text-zinc-600 tracking-[0.5px]">
            <Clock size={11} className="text-zinc-700" />
            <span>UPDATED <span className="text-zinc-400">{fmtLastUpdated(status?.last_poll_at)}</span></span>
            {status?.status === 'rate_limited' && (
              <span className="text-amber-500/80">· X RATE-LIMITED</span>
            )}
          </div>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="mt-0.5 text-zinc-400 hover:text-zinc-200 disabled:opacity-40 transition-colors p-2 -mr-2 rounded-full hover:bg-zinc-900 active:bg-zinc-950"
          aria-label="Refresh leaderboard"
        >
          <RefreshCw size={17} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Public CTA — anyone can view the board; submitting prompts login on /add */}
      <Link
        to="/add"
        className="flex items-center justify-center gap-2 w-full py-3 rounded-2xl bg-sky-500 hover:bg-sky-400 active:bg-sky-600 text-zinc-950 font-semibold text-sm tracking-[-0.1px] transition-colors active:scale-[0.99]"
      >
        <Send size={15} />
        Submit your thread
      </Link>

      {/* Contest header strip */}
      {!loading && !error && data?.contest && (
        <div className="bg-zinc-950 border border-zinc-800 rounded-2xl px-4 py-3 flex items-center gap-3">
          <div className="flex-1 min-w-0">
            <p className="text-sky-400 font-semibold text-[15px] tracking-[-0.1px] truncate">{data.contest.title}</p>
            <p className="text-zinc-500 text-xs mt-px font-mono tracking-[0.5px] tabular-nums">
              {data.contest.start_date} — {data.contest.end_date}
            </p>
          </div>
          <div
            className={`shrink-0 text-[10px] font-semibold px-3 py-1 rounded-full border tracking-widest ${data.contest.status === 'active'
              ? 'text-emerald-400 border-emerald-900 bg-emerald-950/60'
              : 'text-zinc-400 border-zinc-700 bg-zinc-900'
              }`}
          >
            {data.contest.status === 'active' ? 'LIVE' : 'ENDED'}
          </div>
        </div>
      )}

      {/* Division tabs */}
      <div className="flex gap-1 bg-zinc-900/70 p-1 rounded-2xl border border-zinc-800">
        {['users', 'posts', 'threads'].map((t) => {
          const active = tab === t;
          const count = data ? (t === 'users' ? data.users?.length : t === 'posts' ? data.posts?.length : data.threads?.length) || 0 : 0;
          const Icon = t === 'users' ? Users : t === 'posts' ? FileText : Layers;
          return (
            <button
              key={t}
              onClick={() => handleTabChange(t)}
              className={`flex-1 flex items-center justify-center gap-2 py-[9px] text-sm font-semibold rounded-[14px] transition-all active:scale-[0.985] ${active
                ? 'bg-zinc-800 text-white shadow-sm'
                : 'text-zinc-400 hover:text-zinc-200 hover:bg-zinc-900/60'
                }`}
            >
              <Icon size={15} />
              <span className="tracking-[-0.1px]">{t.toUpperCase()}</span>
              <span className="text-[10px] font-mono text-zinc-500 tabular-nums">({count})</span>
            </button>
          );
        })}
      </div>

      {error && (
        <div className="text-red-400 text-sm bg-red-950/30 border border-red-900 rounded-2xl p-3.5">{error}</div>
      )}

      {/* Controls cockpit — the heart of intuitive filtering + sorting */}
      {!loading && !error && data && (
        <div className="border border-zinc-800 bg-zinc-950/50 rounded-2xl p-4 space-y-4">
          {/* Search */}
          <div>
            <div className="font-mono uppercase text-[9px] tracking-[2.5px] text-zinc-600 mb-1.5">HUNT</div>
            <div className="relative">
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search @handles or keywords…"
                className="w-full bg-zinc-950 border border-zinc-700 focus:border-cyan-400/70 text-sm placeholder:text-zinc-600 text-white rounded-2xl pl-9 pr-8 py-2.5 outline-none transition-colors"
              />
              <Search size={15} className="absolute left-3.5 top-3 text-zinc-600 pointer-events-none" />
              {search && (
                <button
                  onClick={() => setSearch('')}
                  className="absolute right-2.5 top-2.5 p-1 text-zinc-500 hover:text-zinc-300 transition-colors"
                  aria-label="Clear search"
                >
                  <X size={15} />
                </button>
              )}
            </div>
          </div>

          {/* Sort */}
          <div>
            <div className="flex items-baseline justify-between mb-1.5">
              <div className="font-mono uppercase text-[9px] tracking-[2.5px] text-zinc-600">SORT</div>
              <div className="text-[9px] text-zinc-700 font-mono tracking-widest">TAP TO REVERSE</div>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {currentSortOptions.map((opt) => {
                const isActive = sortBy === opt.key;
                return (
                  <button
                    key={opt.key}
                    onClick={() => handleSortClick(opt)}
                    className={`control-btn px-3.5 py-1.5 rounded-2xl text-xs font-semibold border flex items-center gap-1.5 active:scale-[0.975] ${isActive
                      ? 'control-btn-active border-cyan-400/60 text-cyan-400'
                      : 'border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500'
                      }`}
                  >
                    {opt.label}
                    {isActive && (
                      sortDir === 'desc' ? <ArrowDown size={13} /> : <ArrowUp size={13} />
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Quick Filters */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <div className="font-mono uppercase text-[9px] tracking-[2.5px] text-zinc-600">QUICK FILTERS</div>
              {filterIds.length > 0 && (
                <button
                  onClick={() => setFilterIds([])}
                  className="text-[10px] text-cyan-400 hover:text-cyan-300 font-medium tracking-normal"
                >
                  CLEAR
                </button>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {currentFilterOptions.map((f) => {
                const on = filterIds.includes(f.id);
                return (
                  <button
                    key={f.id}
                    onClick={() => toggleFilter(f.id)}
                    className={`filter-chip px-3 py-[5px] text-[10px] font-medium rounded-full border ${on
                      ? 'filter-chip-active'
                      : 'border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-500'
                      }`}
                  >
                    {f.label}
                  </button>
                );
              })}
              {currentFilterOptions.length === 0 && (
                <span className="text-xs text-zinc-700 px-1">No quick filters for this view</span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Results meta */}
      {!loading && !error && data && originalCount > 0 && (
        <div className="px-1 flex items-center justify-between text-[10px] font-mono tracking-[0.8px] text-zinc-600 tabular-nums">
          <div>
            SHOWING <span className="text-zinc-400 font-semibold">{processed.length}</span> OF {originalCount}
          </div>
          <div className="text-right">
            {sortLabel} · {sortDir.toUpperCase()}
            {filterIds.length > 0 && ` · ${filterIds.length} FILTER${filterIds.length > 1 ? 'S' : ''}`}
          </div>
        </div>
      )}

      {/* Main content area */}
      {loading && <ListSkeleton />}

      {!loading && !error && data && originalCount === 0 && (
        <div className="text-center text-sm text-zinc-500 border border-zinc-800 bg-zinc-950 rounded-2xl py-9">
          No data yet for this contest.<br />Submit threads to populate the arena.
        </div>
      )}

      {!loading && !error && data && originalCount > 0 && processed.length === 0 && (
        <div className="text-center text-sm text-zinc-500 border border-zinc-800 bg-zinc-950 rounded-2xl py-8 space-y-3">
          <p>No entries match the current search &amp; filters.</p>
          <button
            onClick={clearFilters}
            className="inline-flex items-center gap-1 text-xs px-4 py-1.5 rounded-full border border-cyan-400/40 text-cyan-400 hover:bg-cyan-950/30 active:bg-cyan-950/50 transition-colors"
          >
            <X size={13} /> CLEAR SEARCH + FILTERS
          </button>
        </div>
      )}

      {!loading && !error && data && processed.length > 0 && (
        tab === 'users' ? (
          <UsersList entries={processed} maxScore={maxScore} />
        ) : tab === 'posts' ? (
          <PostsList entries={processed} maxScore={maxScore} />
        ) : (
          <ThreadsList entries={processed} maxScore={maxScore} />
        )
      )}

      {/* Tiny footer hint */}
      {!loading && !error && data && processed.length > 0 && (
        <p className="text-center text-[9px] text-zinc-700 font-mono tracking-widest pt-1">SCORES = INTERACTIONS + 300 × RATIO</p>
      )}
    </div>
  );
}
