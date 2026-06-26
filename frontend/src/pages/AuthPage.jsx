/** Same-origin in dev (Vite proxies /oauth → API). Set VITE_BACKEND_URL when the API is on another origin. */
const oauthLoginHref = import.meta.env.VITE_BACKEND_URL
  ? `${import.meta.env.VITE_BACKEND_URL.replace(/\/$/, '')}/oauth/login`
  : '/oauth/login';

export default function AuthPage() {
  return (
    <div className="min-h-screen bg-zinc-950 flex flex-col items-center justify-center p-6">
      <div className="text-center space-y-6">
        <div>
          <h1 className="text-4xl font-bold text-white tracking-tight">ShillJudge</h1>
          <p className="text-zinc-500 mt-2 text-sm">Track and score your X thread performance</p>
        </div>
        <a
          href={oauthLoginHref}
          className="inline-flex items-center gap-2 bg-sky-500 hover:bg-sky-400 active:bg-sky-600 text-white font-semibold px-8 py-3 rounded-full transition-colors text-sm"
        >
          Authenticate with X
        </a>
      </div>
    </div>
  );
}
