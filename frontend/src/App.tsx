import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Layout } from './components/Layout';
import { ProtectedRoute } from './components/ProtectedRoute';
import { Login } from './pages/Login';
import { Register } from './pages/Register';
import { Setup2FA } from './pages/Setup2FA';
import { Verify2FA } from './pages/Verify2FA';
import { Documents } from './pages/Documents';
import { Batch } from './pages/Batch';
import { ReferenceLibraryPage } from './pages/ReferenceLibrary';
import { Analytics } from './pages/Analytics';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30 * 1000, // 30 seconds
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          {/* Public routes */}
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/setup-2fa" element={<Setup2FA />} />
          <Route path="/verify-2fa" element={<Verify2FA />} />

          {/* Protected routes */}
          <Route
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route path="/documents" element={<Documents />} />
            <Route path="/batch" element={<Batch />} />
            <Route path="/reference-library" element={<ReferenceLibraryPage />} />
            <Route path="/analytics" element={<Analytics />} />
          </Route>

          {/* Default redirect */}
          <Route path="/" element={<Navigate to="/documents" replace />} />
          <Route path="*" element={<Navigate to="/documents" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
