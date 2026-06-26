import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { checkAuthStatus } from './api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [loading, setLoading] = useState(true);
  const [auth, setAuth] = useState({
    authenticated: false,
    xId: null,
    xUsername: null,
    isAdmin: false,
    walletAddress: null,
    stakeVerified: false,
  });

  const refresh = useCallback(() => {
    return checkAuthStatus().then(data => {
      setAuth({
        authenticated: data.authenticated ?? false,
        xId: data.x_id ?? null,
        xUsername: data.x_username ?? null,
        isAdmin: data.is_admin ?? false,
        walletAddress: data.wallet_address ?? null,
        stakeVerified: data.stake_verified ?? false,
      });
    });
  }, []);

  useEffect(() => {
    refresh().finally(() => setLoading(false));
  }, [refresh]);

  return (
    <AuthContext.Provider value={{ loading, ...auth, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
