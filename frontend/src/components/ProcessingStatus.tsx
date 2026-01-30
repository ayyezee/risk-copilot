import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { documentsApi } from '../services/api';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from './ui/card';
import { Progress } from './ui/progress';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import {
  Loader2,
  CheckCircle2,
  XCircle,
  Download,
  FileText,
} from 'lucide-react';

interface ProcessingStatusProps {
  documentId: string;
  onComplete?: () => void;
}

interface ProcessingResult {
  status: string;
  progress?: number;
  processed_document_id?: string;
  total_replacements?: number;
  processing_time_ms?: number;
  error_message?: string;
  changes_summary?: {
    replacements: Array<{
      original: string;
      replacement: string;
      count: number;
    }>;
  };
}

export function ProcessingStatus({ documentId, onComplete }: ProcessingStatusProps) {
  const [isComplete, setIsComplete] = useState(false);

  const { data: status, isLoading } = useQuery({
    queryKey: ['processingStatus', documentId],
    queryFn: async () => {
      const response = await documentsApi.getProcessingStatus(documentId);
      return response.data as ProcessingResult;
    },
    refetchInterval: (query) => {
      const data = query.state.data as ProcessingResult | undefined;
      if (data?.status === 'completed' || data?.status === 'failed') {
        return false;
      }
      return 2000; // Poll every 2 seconds while processing
    },
    enabled: !isComplete,
  });

  useEffect(() => {
    if (status?.status === 'completed' || status?.status === 'failed') {
      setIsComplete(true);
      onComplete?.();
    }
  }, [status, onComplete]);

  const handleDownload = async () => {
    if (status?.processed_document_id) {
      const response = await documentsApi.downloadProcessed(status.processed_document_id);
      const blob = new Blob([response.data], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `processed-${documentId}.docx`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    }
  };

  if (isLoading && !status) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  const getStatusIcon = () => {
    switch (status?.status) {
      case 'completed':
        return <CheckCircle2 className="h-6 w-6 text-green-500" />;
      case 'failed':
        return <XCircle className="h-6 w-6 text-red-500" />;
      default:
        return <Loader2 className="h-6 w-6 animate-spin text-primary" />;
    }
  };

  const getStatusBadge = () => {
    switch (status?.status) {
      case 'completed':
        return <Badge variant="success">Completed</Badge>;
      case 'failed':
        return <Badge variant="destructive">Failed</Badge>;
      case 'processing':
        return <Badge variant="warning">Processing</Badge>;
      default:
        return <Badge variant="secondary">{status?.status || 'Unknown'}</Badge>;
    }
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            {getStatusIcon()}
            <div>
              <CardTitle className="text-lg">Document Processing</CardTitle>
              <CardDescription>
                {status?.status === 'processing'
                  ? 'Your document is being processed...'
                  : status?.status === 'completed'
                  ? 'Processing complete!'
                  : status?.status === 'failed'
                  ? 'Processing failed'
                  : 'Waiting to process...'}
              </CardDescription>
            </div>
          </div>
          {getStatusBadge()}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {status?.status === 'processing' && (
          <div className="space-y-2">
            <Progress value={status.progress || 0} />
            <p className="text-sm text-muted-foreground text-center">
              {status.progress || 0}% complete
            </p>
          </div>
        )}

        {status?.status === 'failed' && status.error_message && (
          <div className="p-3 text-sm text-red-500 bg-red-50 border border-red-200 rounded-md">
            {status.error_message}
          </div>
        )}

        {status?.status === 'completed' && (
          <>
            <div className="grid grid-cols-2 gap-4">
              <div className="p-3 bg-muted rounded-lg">
                <p className="text-sm text-muted-foreground">Replacements</p>
                <p className="text-2xl font-bold">
                  {status.total_replacements || 0}
                </p>
              </div>
              <div className="p-3 bg-muted rounded-lg">
                <p className="text-sm text-muted-foreground">Processing Time</p>
                <p className="text-2xl font-bold">
                  {status.processing_time_ms
                    ? `${(status.processing_time_ms / 1000).toFixed(1)}s`
                    : '-'}
                </p>
              </div>
            </div>

            {status.changes_summary?.replacements &&
              status.changes_summary.replacements.length > 0 && (
                <div className="space-y-2">
                  <p className="text-sm font-medium">Changes Made:</p>
                  <div className="max-h-48 overflow-y-auto space-y-1">
                    {status.changes_summary.replacements
                      .slice(0, 10)
                      .map((change, index) => (
                        <div
                          key={index}
                          className="flex items-center justify-between p-2 bg-muted rounded text-sm"
                        >
                          <span className="text-muted-foreground line-through">
                            {change.original}
                          </span>
                          <span className="mx-2">→</span>
                          <span className="font-medium">{change.replacement}</span>
                          <Badge variant="secondary" className="ml-2">
                            x{change.count}
                          </Badge>
                        </div>
                      ))}
                    {status.changes_summary.replacements.length > 10 && (
                      <p className="text-xs text-muted-foreground text-center">
                        +{status.changes_summary.replacements.length - 10} more
                        changes
                      </p>
                    )}
                  </div>
                </div>
              )}

            <Button className="w-full" onClick={handleDownload}>
              <Download className="mr-2 h-4 w-4" />
              Download Processed Document
            </Button>
          </>
        )}
      </CardContent>
    </Card>
  );
}
