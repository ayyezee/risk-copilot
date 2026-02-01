import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { useAuthStore } from '../stores/authStore';

const API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1';

export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor to add auth token
api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = useAuthStore.getState().accessToken;
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }

    // Add 2FA verification header if verified
    const is2FAVerified = useAuthStore.getState().is2FAVerified;
    if (is2FAVerified) {
      config.headers['X-2FA-Verified'] = 'true';
    }

    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor for token refresh
api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    // Handle 401 Unauthorized
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      const refreshToken = useAuthStore.getState().refreshToken;
      if (refreshToken) {
        try {
          const response = await axios.post(`${API_BASE_URL}/auth/refresh`, {
            refresh_token: refreshToken,
          });

          const { access_token, refresh_token: newRefreshToken } = response.data;
          useAuthStore.getState().setTokens(access_token, newRefreshToken);

          originalRequest.headers.Authorization = `Bearer ${access_token}`;
          return api(originalRequest);
        } catch (refreshError) {
          // Refresh failed, logout user
          useAuthStore.getState().logout();
          window.location.href = '/login';
          return Promise.reject(refreshError);
        }
      } else {
        // No refresh token, logout
        useAuthStore.getState().logout();
        window.location.href = '/login';
      }
    }

    // Handle 403 with 2FA required
    if (error.response?.status === 403 && error.response.headers['x-2fa-required'] === 'true') {
      window.location.href = '/setup-2fa';
    }

    return Promise.reject(error);
  }
);

// Auth API
export const authApi = {
  login: (email: string, password: string) =>
    api.post('/auth/login', { email, password }),

  register: (email: string, password: string, full_name: string) =>
    api.post('/auth/register', { email, password, full_name }),

  logout: () => {
    const refreshToken = useAuthStore.getState().refreshToken;
    return api.post('/auth/logout', { refresh_token: refreshToken });
  },

  refreshToken: (refreshToken: string) =>
    api.post('/auth/refresh', { refresh_token: refreshToken }),

  getMe: () => api.get('/auth/me'),

  setup2FA: () => api.post('/auth/2fa/setup'),

  verify2FA: (code: string) => api.post('/auth/2fa/verify', { code }),

  enable2FA: (code: string) => api.post('/auth/2fa/enable', { code }),

  disable2FA: (code: string) => api.post('/auth/2fa/disable', { code }),
};

// Documents API
export const documentsApi = {
  list: (params?: { page?: number; page_size?: number; file_type?: string }) =>
    api.get('/documents', { params }),

  get: (id: string) => api.get(`/documents/${id}`),

  upload: (file: File, onProgress?: (progress: number) => void) => {
    const formData = new FormData();
    formData.append('file', file);

    return api.post('/documents/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(progress);
        }
      },
    });
  },

  delete: (id: string) => api.delete(`/documents/${id}`),

  // Basic processing (extract text, summary, index)
  processBasic: (documentId: string, options?: {
    generate_summary?: boolean;
    extract_metadata?: boolean;
    index_for_search?: boolean;
  }) => api.post(`/documents/${documentId}/process`, options || {}),

  // Full AI processing pipeline (term replacement)
  process: (documentId: string, options?: {
    reference_example_ids?: string[];
    top_k_examples?: number;
    protected_terms?: string[];
    min_confidence?: number;
    highlight_changes?: boolean;
    generate_changes_report?: boolean;
    selected_page_ranges?: { start_page: number; end_page: number; label?: string }[];
    use_full_document_for_context?: boolean;
  }) => api.post(`/process/documents/${documentId}/process`, options || {}),

  // Detect document sections using AI
  detectSections: (documentId: string) =>
    api.post<{
      document_id: string;
      sections: {
        id: string;
        title: string;
        description?: string;
        start_page: number;
        end_page: number;
        section_type?: string;
        confidence: number;
      }[];
      page_count?: number;
      warnings: string[];
    }>(`/documents/${documentId}/detect-sections`),

  getStatus: (documentId: string) =>
    api.get(`/documents/${documentId}`),

  downloadProcessed: (processedDocumentId: string) =>
    api.get(`/process/outputs/${processedDocumentId}/download`, {
      responseType: 'blob',
    }),

  downloadOriginal: (documentId: string) =>
    api.get(`/documents/${documentId}/download`, {
      responseType: 'blob',
    }),

  extractTerms: (documentId: string) =>
    api.post(`/documents/${documentId}/extract-terms`),
};

// Reference Library API
export const referenceLibraryApi = {
  listExamples: (params?: { page?: number; page_size?: number; category?: string }) =>
    api.get('/reference-library', { params }),

  getExample: (id: string) => api.get(`/reference-library/${id}`),

  createExample: (data: {
    name: string;
    description?: string;
    original_text: string;
    converted_text: string;
  }) => api.post('/reference-library', data),

  updateExample: (id: string, data: {
    name?: string;
    description?: string;
    original_text?: string;
    converted_text?: string;
  }) => api.put(`/reference-library/${id}`, data),

  deleteExample: (id: string) => api.delete(`/reference-library/${id}`),

  searchSimilar: (text: string, limit?: number) =>
    api.post('/reference-library/search', { text, limit }),
};

// Batch Processing API
export const batchApi = {
  create: (files: File[], options: {
    reference_example_ids?: string[];
    protected_terms?: string[];
    min_confidence?: number;
    highlight_changes?: boolean;
    generate_changes_report?: boolean;
  }) => {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));

    if (options.reference_example_ids) {
      formData.append('reference_example_ids', JSON.stringify(options.reference_example_ids));
    }
    if (options.protected_terms) {
      formData.append('protected_terms', JSON.stringify(options.protected_terms));
    }
    if (options.min_confidence !== undefined) {
      formData.append('min_confidence', options.min_confidence.toString());
    }
    if (options.highlight_changes !== undefined) {
      formData.append('highlight_changes', options.highlight_changes.toString());
    }
    if (options.generate_changes_report !== undefined) {
      formData.append('generate_changes_report', options.generate_changes_report.toString());
    }

    return api.post('/batch', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },

  list: (params?: { page?: number; page_size?: number; status?: string }) =>
    api.get('/batch', { params }),

  get: (id: string) => api.get(`/batch/${id}`),

  cancel: (id: string) => api.post(`/batch/${id}/cancel`),

  downloadResults: (id: string) =>
    api.get(`/batch/${id}/download`, { responseType: 'blob' }),

  // WebSocket connection for real-time updates
  connectWebSocket: (jobId: string, token: string): WebSocket => {
    const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/api/v1/batch/${jobId}/ws?token=${token}`;
    return new WebSocket(wsUrl);
  },
};

// Analytics API
export const analyticsApi = {
  getDashboard: (params?: { start_date?: string; end_date?: string }) =>
    api.get('/analytics/dashboard', { params }),

  getTermFrequency: (params?: { limit?: number; start_date?: string; end_date?: string }) =>
    api.get('/analytics/term-frequency', { params }),

  submitCorrection: (data: {
    processed_document_id: string;
    original_term: string;
    ai_replacement: string;
    user_correction: string;
    context?: string;
  }) => api.post('/analytics/corrections', data),

  getCorrections: (params?: { page?: number; page_size?: number }) =>
    api.get('/analytics/corrections', { params }),
};

export default api;
