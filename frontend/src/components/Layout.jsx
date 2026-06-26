import { Link, useLocation } from 'react-router-dom';
import { Trophy, PlusCircle, Settings, User, Send } from 'lucide-react';
import { useAuth } from '../AuthContext';
import { logout } from '../api';

const oauthLoginHref = import.meta.env.VITE_BACKEND_URL
  ? `${import.meta.env.VITE_BACKEND_URL.replace(/\/$/, '')}/oauth/login`
  : '/oauth/login';

export default function Layout({ children }) {
  const { pathname } = useLocation();
  const { authenticated, xUsername, isAdmin, refresh } = useAuth();

  const handleLogout = async () => {
    await logout().catch(() => {});
    await refresh();
    window.location.href = '/';
  };

  const nav = [
    { to: '/', label: 'Leaderboard', Icon: Trophy, always: true },
    { to: '/submit', label: 'Submit', Icon: Send, always: true },
    { to: '/add', label: 'Add Posts', Icon: PlusCircle, always: false },
    { to: '/profile', label: 'Profile', Icon: User, always: false },
    { to: '/manage', label: 'Manage', Icon: Settings, adminOnly: true },
  ].filter(item => item.always || (item.adminOnly ? isAdmin : authenticated));

  return (
    <div className="min-h-screen bg-zinc-950 flex flex-col">
      <header className="sticky top-0 z-10 bg-zinc-950/90 backdrop-blur-sm border-b border-zinc-800 px-4 py-3 flex items-center justify-between">
        <span className="text-white font-bold text-lg tracking-tight">ShillJudge</span>
        <div className="text-xs">
          {authenticated ? (
            <div className="flex items-center gap-3">
              <span className="text-zinc-400">@{xUsername}</span>
              <button
                onClick={handleLogout}
                className="text-zinc-500 hover:text-zinc-300 transition-colors"
              >
                Sign out
              </button>
            </div>
          ) : (
            <a
              href={oauthLoginHref}
              className="text-sky-400 hover:text-sky-300 transition-colors font-medium"
            >
              Sign in with X
            </a>
          )}
        </div>
      </header>

      <main className="flex-1 w-full max-w-lg mx-auto px-4 py-5 pb-28">
        {children}
      </main>

      <nav className="fixed bottom-0 left-0 right-0 z-10 bg-zinc-900 border-t border-zinc-800 flex safe-bottom">
        {nav.map(({ to, label, Icon }) => {
          const active = pathname === to;
          return (
            <Link
              key={to}
              to={to}
              className={`flex-1 flex flex-col items-center gap-1 py-3 text-xs font-medium transition-colors ${
                active ? 'text-sky-400' : 'text-zinc-500 hover:text-zinc-300 active:text-zinc-200'
              }`}
            >
              <Icon size={20} strokeWidth={active ? 2.5 : 1.75} />
              <span>{label}</span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
