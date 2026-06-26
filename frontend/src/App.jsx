import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './AuthContext';
import AuthPage from './pages/AuthPage';
import DashboardPage from './pages/DashboardPage';
import AddPostsPage from './pages/AddPostsPage';
import ManagePage from './pages/ManagePage';
import ProfilePage from './pages/ProfilePage';
import SubmitPage from './pages/SubmitPage';
import Layout from './components/Layout';

function AppRoutes() {
  const { loading, authenticated, isAdmin } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-zinc-950 flex items-center justify-center">
        <div className="text-zinc-500 text-sm">Loading…</div>
      </div>
    );
  }

  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/submit" element={<SubmitPage />} />
          <Route path="/add" element={authenticated ? <AddPostsPage /> : <AuthPage />} />
          <Route path="/profile" element={authenticated ? <ProfilePage /> : <AuthPage />} />
          <Route path="/manage" element={isAdmin ? <ManagePage /> : <Navigate to="/" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  );
}
