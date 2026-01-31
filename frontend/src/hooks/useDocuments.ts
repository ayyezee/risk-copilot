import { useCallback, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { documentsApi, batchApi, referenceLibraryApi } from '../services/api';
import { useAuthStore } from '../stores/authStore';

export interface Document {
  id: string;
  filename: string;
  original_filename: string;
  file_type: string;
  file_size: number;
  content_text?: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ProcessedDocument {
  id: string;
  document_id: string;
  output_filename: string;
  total_replacements: number;
  processing_time_ms: number;
  changes_summary?: Record<string, unknown>;
  created_at: string;
}

export interface BatchJob {
  id: string;
  status: string;
  total_documents: number;
  processed_documents: number;
  failed_documents: number;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  created_at: string;
}

export function useDocuments() {
  const queryClient = useQueryClient();
  const [uploadProgress, setUploadProgress] = useState<Record<string, number>>({});

  // List documents
  const {
    data: documentsData,
    isLoading: isLoadingDocuments,
    error: documentsError,
    refetch: refetchDocuments,
  } = useQuery({
    queryKey: ['documents'],
    queryFn: async () => {
      const response = await documentsApi.list();
      return response.data;
    },
  });

  // Upload document mutation
  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const response = await documentsApi.upload(file, (progress) => {
        setUploadProgress((prev) => ({ ...prev, [file.name]: progress }));
      });
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
    onSettled: (_, __, file) => {
      setUploadProgress((prev) => {
        const { [file.name]: _, ...rest } = prev;
        return rest;
      });
    },
  });

  // Delete document mutation
  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      await documentsApi.delete(id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
  });

  // Process document mutation (full AI pipeline)
  const processMutation = useMutation({
    mutationFn: async ({
      documentId,
      options,
    }: {
      documentId: string;
      options?: {
        reference_example_ids?: string[];
        top_k_examples?: number;
        protected_terms?: string[];
        min_confidence?: number;
        highlight_changes?: boolean;
        generate_changes_report?: boolean;
      };
    }) => {
      const response = await documentsApi.process(documentId, options);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
    },
  });

  const uploadDocument = useCallback(
    (file: File) => uploadMutation.mutateAsync(file),
    [uploadMutation]
  );

  const deleteDocument = useCallback(
    (id: string) => deleteMutation.mutateAsync(id),
    [deleteMutation]
  );

  const processDocument = useCallback(
    (documentId: string, options: Parameters<typeof processMutation.mutateAsync>[0]['options']) =>
      processMutation.mutateAsync({ documentId, options }),
    [processMutation]
  );

  return {
    documents: documentsData?.items || [],
    totalDocuments: documentsData?.total || 0,
    isLoadingDocuments,
    documentsError,
    refetchDocuments,

    uploadDocument,
    uploadProgress,
    isUploading: uploadMutation.isPending,
    uploadError: uploadMutation.error,

    deleteDocument,
    isDeleting: deleteMutation.isPending,
    deleteError: deleteMutation.error,

    processDocument,
    isProcessing: processMutation.isPending,
    processError: processMutation.error,
  };
}

export function useBatchJobs() {
  const queryClient = useQueryClient();
  const { accessToken } = useAuthStore();

  // List batch jobs
  const {
    data: batchJobsData,
    isLoading: isLoadingBatchJobs,
    error: batchJobsError,
    refetch: refetchBatchJobs,
  } = useQuery({
    queryKey: ['batchJobs'],
    queryFn: async () => {
      const response = await batchApi.list();
      return response.data;
    },
  });

  // Create batch job mutation
  const createBatchMutation = useMutation({
    mutationFn: async ({
      files,
      options,
    }: {
      files: File[];
      options: {
        reference_example_ids?: string[];
        protected_terms?: string[];
        min_confidence?: number;
        highlight_changes?: boolean;
        generate_changes_report?: boolean;
      };
    }) => {
      const response = await batchApi.create(files, options);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['batchJobs'] });
    },
  });

  // Cancel batch job mutation
  const cancelBatchMutation = useMutation({
    mutationFn: async (id: string) => {
      const response = await batchApi.cancel(id);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['batchJobs'] });
    },
  });

  // Connect to WebSocket for real-time updates
  const connectToJobUpdates = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (jobId: string, onMessage: (data: any) => void, onError?: (error: Event) => void) => {
      if (!accessToken) return null;

      const ws = batchApi.connectWebSocket(jobId, accessToken);

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        onMessage(data);
      };

      ws.onerror = (error) => {
        onError?.(error);
      };

      ws.onclose = () => {
        queryClient.invalidateQueries({ queryKey: ['batchJobs'] });
      };

      return ws;
    },
    [accessToken, queryClient]
  );

  const createBatchJob = useCallback(
    (files: File[], options: Parameters<typeof createBatchMutation.mutateAsync>[0]['options']) =>
      createBatchMutation.mutateAsync({ files, options }),
    [createBatchMutation]
  );

  const cancelBatchJob = useCallback(
    (id: string) => cancelBatchMutation.mutateAsync(id),
    [cancelBatchMutation]
  );

  const downloadBatchResults = useCallback(async (id: string) => {
    const response = await batchApi.downloadResults(id);
    const blob = new Blob([response.data], { type: 'application/zip' });
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `batch-${id}-results.zip`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.URL.revokeObjectURL(url);
  }, []);

  return {
    batchJobs: batchJobsData?.items || [],
    totalBatchJobs: batchJobsData?.total || 0,
    isLoadingBatchJobs,
    batchJobsError,
    refetchBatchJobs,

    createBatchJob,
    isCreatingBatch: createBatchMutation.isPending,
    createBatchError: createBatchMutation.error,

    cancelBatchJob,
    isCancellingBatch: cancelBatchMutation.isPending,
    cancelBatchError: cancelBatchMutation.error,

    downloadBatchResults,
    connectToJobUpdates,
  };
}

export function useReferenceLibrary() {
  const queryClient = useQueryClient();

  // List reference examples
  const {
    data: examplesData,
    isLoading: isLoadingExamples,
    error: examplesError,
    refetch: refetchExamples,
  } = useQuery({
    queryKey: ['referenceExamples'],
    queryFn: async () => {
      const response = await referenceLibraryApi.listExamples();
      return response.data;
    },
  });

  // Create example mutation
  const createExampleMutation = useMutation({
    mutationFn: async (data: {
      name: string;
      description?: string;
      original_text: string;
      converted_text: string;
    }) => {
      const response = await referenceLibraryApi.createExample(data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['referenceExamples'] });
    },
  });

  // Update example mutation
  const updateExampleMutation = useMutation({
    mutationFn: async ({
      id,
      data,
    }: {
      id: string;
      data: {
        name?: string;
        description?: string;
        original_text?: string;
        converted_text?: string;
      };
    }) => {
      const response = await referenceLibraryApi.updateExample(id, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['referenceExamples'] });
    },
  });

  // Delete example mutation
  const deleteExampleMutation = useMutation({
    mutationFn: async (id: string) => {
      await referenceLibraryApi.deleteExample(id);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['referenceExamples'] });
    },
  });

  // Search similar examples mutation
  const searchSimilarMutation = useMutation({
    mutationFn: async ({ text, limit }: { text: string; limit?: number }) => {
      const response = await referenceLibraryApi.searchSimilar(text, limit);
      return response.data;
    },
  });

  const createExample = useCallback(
    (data: Parameters<typeof createExampleMutation.mutateAsync>[0]) =>
      createExampleMutation.mutateAsync(data),
    [createExampleMutation]
  );

  const updateExample = useCallback(
    (id: string, data: Parameters<typeof updateExampleMutation.mutateAsync>[0]['data']) =>
      updateExampleMutation.mutateAsync({ id, data }),
    [updateExampleMutation]
  );

  const deleteExample = useCallback(
    (id: string) => deleteExampleMutation.mutateAsync(id),
    [deleteExampleMutation]
  );

  const searchSimilar = useCallback(
    (text: string, limit?: number) => searchSimilarMutation.mutateAsync({ text, limit }),
    [searchSimilarMutation]
  );

  return {
    examples: examplesData?.items || [],
    totalExamples: examplesData?.total || 0,
    isLoadingExamples,
    examplesError,
    refetchExamples,

    createExample,
    isCreatingExample: createExampleMutation.isPending,
    createExampleError: createExampleMutation.error,

    updateExample,
    isUpdatingExample: updateExampleMutation.isPending,
    updateExampleError: updateExampleMutation.error,

    deleteExample,
    isDeletingExample: deleteExampleMutation.isPending,
    deleteExampleError: deleteExampleMutation.error,

    searchSimilar,
    isSearching: searchSimilarMutation.isPending,
    searchResults: searchSimilarMutation.data,
    searchError: searchSimilarMutation.error,
  };
}
