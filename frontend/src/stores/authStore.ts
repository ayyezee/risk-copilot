import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

interface User {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_verified: boolean;
  is_superuser: boolean;
  totp_enabled: boolean;
  created_at: string;
}

interface AuthState {
  user: User | null;
  accessToken: string | null;
  refreshToken: string | null;
  is2FAVerified: boolean;
  isLoading: boolean;

  // Actions
  setUser: (user: User | null) => void;
  setTokens: (accessToken: string, refreshToken: string) => void;
  set2FAVerified: (verified: boolean) => void;
  setLoading: (loading: boolean) => void;
  logout: () => void;

  // Computed
  isAuthenticated: () => boolean;
  requires2FA: () => boolean;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      accessToken: null,
      refreshToken: null,
      is2FAVerified: false,
      isLoading: false,

      setUser: (user) => set({ user }),

      setTokens: (accessToken, refreshToken) =>
        set({ accessToken, refreshToken }),

      set2FAVerified: (verified) => set({ is2FAVerified: verified }),

      setLoading: (loading) => set({ isLoading: loading }),

      logout: () => set({
        user: null,
        accessToken: null,
        refreshToken: null,
        is2FAVerified: false,
      }),

      isAuthenticated: () => {
        const state = get();
        return !!state.accessToken && !!state.user;
      },

      requires2FA: () => {
        const state = get();
        return !!state.user?.totp_enabled && !state.is2FAVerified;
      },
    }),
    {
      name: 'werdsmith-auth',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        user: state.user,
        is2FAVerified: state.is2FAVerified,
      }),
    }
  )
);
