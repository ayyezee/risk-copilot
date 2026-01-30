import { useCallback } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { authApi } from '../services/api';
import { useAuthStore } from '../stores/authStore';

export function useAuth() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const {
    user,
    accessToken,
    is2FAVerified,
    isLoading,
    setUser,
    setTokens,
    set2FAVerified,
    setLoading,
    logout: storeLogout,
    isAuthenticated,
    requires2FA,
  } = useAuthStore();

  // Fetch current user
  const { refetch: refetchUser } = useQuery({
    queryKey: ['currentUser'],
    queryFn: async () => {
      const response = await authApi.getMe();
      setUser(response.data);
      return response.data;
    },
    enabled: !!accessToken,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  // Login mutation
  const loginMutation = useMutation({
    mutationFn: async ({ email, password }: { email: string; password: string }) => {
      const response = await authApi.login(email, password);
      return response.data;
    },
    onSuccess: (data) => {
      setTokens(data.access_token, data.refresh_token);
      setUser(data.user);

      // Check if 2FA is required
      if (data.user.totp_enabled) {
        set2FAVerified(false);
        navigate('/verify-2fa');
      } else {
        navigate('/documents');
      }
    },
  });

  // Register mutation
  const registerMutation = useMutation({
    mutationFn: async ({
      email,
      password,
      fullName,
    }: {
      email: string;
      password: string;
      fullName: string;
    }) => {
      const response = await authApi.register(email, password, fullName);
      return response.data;
    },
    onSuccess: (data) => {
      setTokens(data.access_token, data.refresh_token);
      setUser(data.user);
      navigate('/documents');
    },
  });

  // Logout mutation
  const logoutMutation = useMutation({
    mutationFn: async () => {
      await authApi.logout();
    },
    onSettled: () => {
      storeLogout();
      queryClient.clear();
      navigate('/login');
    },
  });

  // 2FA setup mutation
  const setup2FAMutation = useMutation({
    mutationFn: async () => {
      const response = await authApi.setup2FA();
      return response.data;
    },
  });

  // 2FA verify mutation
  const verify2FAMutation = useMutation({
    mutationFn: async (code: string) => {
      const response = await authApi.verify2FA(code);
      return response.data;
    },
    onSuccess: () => {
      set2FAVerified(true);
      navigate('/documents');
    },
  });

  // 2FA enable mutation
  const enable2FAMutation = useMutation({
    mutationFn: async (code: string) => {
      const response = await authApi.enable2FA(code);
      return response.data;
    },
    onSuccess: () => {
      refetchUser();
    },
  });

  // 2FA disable mutation
  const disable2FAMutation = useMutation({
    mutationFn: async (code: string) => {
      const response = await authApi.disable2FA(code);
      return response.data;
    },
    onSuccess: () => {
      set2FAVerified(false);
      refetchUser();
    },
  });

  const login = useCallback(
    (email: string, password: string) => {
      loginMutation.mutate({ email, password });
    },
    [loginMutation]
  );

  const register = useCallback(
    (email: string, password: string, fullName: string) => {
      registerMutation.mutate({ email, password, fullName });
    },
    [registerMutation]
  );

  const logout = useCallback(() => {
    logoutMutation.mutate();
  }, [logoutMutation]);

  const setup2FA = useCallback(() => {
    return setup2FAMutation.mutateAsync();
  }, [setup2FAMutation]);

  const verify2FA = useCallback(
    (code: string) => {
      verify2FAMutation.mutate(code);
    },
    [verify2FAMutation]
  );

  const enable2FA = useCallback(
    (code: string) => {
      return enable2FAMutation.mutateAsync(code);
    },
    [enable2FAMutation]
  );

  const disable2FA = useCallback(
    (code: string) => {
      return disable2FAMutation.mutateAsync(code);
    },
    [disable2FAMutation]
  );

  return {
    user,
    accessToken,
    is2FAVerified,
    isLoading,
    isAuthenticated: isAuthenticated(),
    requires2FA: requires2FA(),

    // Mutations
    login,
    register,
    logout,
    setup2FA,
    verify2FA,
    enable2FA,
    disable2FA,

    // Mutation states
    isLoggingIn: loginMutation.isPending,
    isRegistering: registerMutation.isPending,
    isLoggingOut: logoutMutation.isPending,
    isSettingUp2FA: setup2FAMutation.isPending,
    isVerifying2FA: verify2FAMutation.isPending,

    // Errors
    loginError: loginMutation.error,
    registerError: registerMutation.error,
    setup2FAError: setup2FAMutation.error,
    verify2FAError: verify2FAMutation.error,

    // 2FA data
    setup2FAData: setup2FAMutation.data,
  };
}
