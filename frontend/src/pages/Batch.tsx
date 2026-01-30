import { useState, useEffect, useCallback } from 'react';
import { useBatchJobs } from '../hooks/useDocuments';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Progress } from '../components/ui/progress';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '../components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui/table';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '../components/ui/dialog';
import {
  Layers,
  Download,
  XCircle,
  Loader2,
  Upload,
  FolderUp,
} from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

interface BatchJob {
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

function getStatusBadgeVariant(status: string) {
  switch (status) {
    case 'completed':
      return 'success';
    case 'processing':
      return 'warning';
    case 'failed':
    case 'cancelled':
      return 'destructive';
    default:
      return 'secondary';
  }
}

export function Batch() {
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [activeJobProgress, setActiveJobProgress] = useState<{
    processed: number;
    total: number;
  } | null>(null);

  const {
    batchJobs,
    isLoadingBatchJobs,
    createBatchJob,
    isCreatingBatch,
    cancelBatchJob,
    downloadBatchResults,
    connectToJobUpdates,
  } = useBatchJobs();

  // Connect to WebSocket for real-time updates
  useEffect(() => {
    if (!activeJobId) return;

    const ws = connectToJobUpdates(
      activeJobId,
      (data: { processed_documents: number; total_documents: number; status: string }) => {
        setActiveJobProgress({
          processed: data.processed_documents,
          total: data.total_documents,
        });

        if (data.status === 'completed' || data.status === 'failed') {
          setActiveJobId(null);
          setActiveJobProgress(null);
        }
      }
    );

    return () => {
      ws?.close();
    };
  }, [activeJobId, connectToJobUpdates]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      setSelectedFiles(Array.from(e.target.files));
    }
  };

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer.files).filter(
      (file) =>
        file.type === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' ||
        file.type === 'application/pdf' ||
        file.type === 'text/plain'
    );
    setSelectedFiles((prev) => [...prev, ...files]);
  }, []);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleCreateBatch = async () => {
    if (selectedFiles.length === 0) return;

    try {
      const result = await createBatchJob(selectedFiles, {
        highlight_changes: true,
        generate_changes_report: true,
      });
      setActiveJobId(result.id);
      setCreateDialogOpen(false);
      setSelectedFiles([]);
    } catch (error) {
      // Error handled by mutation
    }
  };

  const handleCancel = async (jobId: string) => {
    if (confirm('Are you sure you want to cancel this batch job?')) {
      await cancelBatchJob(jobId);
      if (activeJobId === jobId) {
        setActiveJobId(null);
        setActiveJobProgress(null);
      }
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Batch Processing</h1>
          <p className="text-muted-foreground">
            Process multiple documents at once
          </p>
        </div>
        <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <FolderUp className="mr-2 h-4 w-4" />
              New Batch Job
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>Create Batch Job</DialogTitle>
              <DialogDescription>
                Upload multiple documents to process them together.
              </DialogDescription>
            </DialogHeader>

            <div
              className="border-2 border-dashed border-muted-foreground/25 rounded-lg p-8 text-center hover:border-muted-foreground/50 transition-colors"
              onDrop={handleDrop}
              onDragOver={handleDragOver}
            >
              <Upload className="mx-auto h-10 w-10 text-muted-foreground/50" />
              <p className="mt-2 text-sm text-muted-foreground">
                Drag and drop files here, or{' '}
                <label className="text-primary cursor-pointer hover:underline">
                  browse
                  <input
                    type="file"
                    multiple
                    accept=".docx,.pdf,.txt"
                    className="hidden"
                    onChange={handleFileSelect}
                  />
                </label>
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                DOCX, PDF, TXT up to 10MB each
              </p>
            </div>

            {selectedFiles.length > 0 && (
              <div className="mt-4 max-h-48 overflow-y-auto">
                <p className="text-sm font-medium mb-2">
                  {selectedFiles.length} file{selectedFiles.length !== 1 ? 's' : ''} selected
                </p>
                <ul className="space-y-1">
                  {selectedFiles.map((file, index) => (
                    <li
                      key={index}
                      className="text-sm text-muted-foreground flex items-center justify-between"
                    >
                      <span className="truncate">{file.name}</span>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() =>
                          setSelectedFiles((prev) =>
                            prev.filter((_, i) => i !== index)
                          )
                        }
                      >
                        <XCircle className="h-4 w-4" />
                      </Button>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setCreateDialogOpen(false);
                  setSelectedFiles([]);
                }}
              >
                Cancel
              </Button>
              <Button
                onClick={handleCreateBatch}
                disabled={selectedFiles.length === 0 || isCreatingBatch}
              >
                {isCreatingBatch && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                Start Processing
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {activeJobProgress && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Processing in Progress</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span>
                  {activeJobProgress.processed} of {activeJobProgress.total} documents
                </span>
                <span>
                  {Math.round(
                    (activeJobProgress.processed / activeJobProgress.total) * 100
                  )}
                  %
                </span>
              </div>
              <Progress
                value={
                  (activeJobProgress.processed / activeJobProgress.total) * 100
                }
              />
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Batch Jobs</CardTitle>
          <CardDescription>
            {batchJobs.length} batch job{batchJobs.length !== 1 ? 's' : ''}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoadingBatchJobs ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : batchJobs.length === 0 ? (
            <div className="text-center py-12">
              <Layers className="mx-auto h-12 w-12 text-muted-foreground/50" />
              <h3 className="mt-4 text-lg font-medium">No batch jobs yet</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                Create a batch job to process multiple documents at once
              </p>
              <Button
                className="mt-4"
                onClick={() => setCreateDialogOpen(true)}
              >
                <FolderUp className="mr-2 h-4 w-4" />
                New Batch Job
              </Button>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Status</TableHead>
                  <TableHead>Progress</TableHead>
                  <TableHead>Documents</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {batchJobs.map((job: BatchJob) => (
                  <TableRow key={job.id}>
                    <TableCell>
                      <Badge variant={getStatusBadgeVariant(job.status)}>
                        {job.status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="w-32">
                        <Progress
                          value={
                            job.total_documents > 0
                              ? (job.processed_documents / job.total_documents) * 100
                              : 0
                          }
                          className="h-2"
                        />
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className="text-sm">
                        {job.processed_documents}/{job.total_documents}
                        {job.failed_documents > 0 && (
                          <span className="text-destructive ml-1">
                            ({job.failed_documents} failed)
                          </span>
                        )}
                      </span>
                    </TableCell>
                    <TableCell>
                      {formatDistanceToNow(new Date(job.created_at), {
                        addSuffix: true,
                      })}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end space-x-2">
                        {job.status === 'processing' && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleCancel(job.id)}
                          >
                            <XCircle className="h-4 w-4" />
                          </Button>
                        )}
                        {job.status === 'completed' && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => downloadBatchResults(job.id)}
                          >
                            <Download className="h-4 w-4" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
