import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  // Local dev defaults to the API on this machine; override with VITE_DEV_PROXY_TARGET for Docker.
  const backendTarget = env.VITE_DEV_PROXY_TARGET || 'http://127.0.0.1:8080';

  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port: 5173,
      proxy: {
        '/oauth': backendTarget,
        '/auth': backendTarget,
        '/leaderboard': backendTarget,
        '/manage': backendTarget,
        '/post': backendTarget,
        '/submissions': backendTarget,
        '/submit': backendTarget,
        '/me': backendTarget,
      },
    },
  };
});
