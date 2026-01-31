import { useState } from 'react';
import { useDocuments } from '../hooks/useDocuments';
import { documentsApi } from '../services/api';
import { DocumentUpload } from '../components/DocumentUpload';
import { ProcessingStatus } from '../components/ProcessingStatus';
import { TermMapper } from '../components/TermMapper';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { ActionButton, ActionButtonGroup } from '../components/ui/action-button';
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
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '../components/ui/dialog';
import {
  FileText,
  Trash2,
  Sparkles,
  Download,
  Loader2,
  Upload,
  Settings2,
  CheckCircle,
  XCircle,
} from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '../components/ui/alert';
import { formatDistanceToNow } from 'date-fns';

interface Document {
  id: string;
  original_filename: string;
  file_type: string;
  file_size: number;
  status: string;
  created_at: string;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getStatusBadgeVariant(status: string) {
  switch (status) {
    case 'completed':
      return 'success';
    case 'processing':
      return 'warning';
    case 'failed':
      return 'destructive';
    default:
      return 'secondary';
  }
}

export function Documents() {
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [processingDocumentId, setProcessingDocumentId] = useState<string | null>(null);
  const [termMapperDoc, setTermMapperDoc] = useState<{ id: string; name: string } | null>(null);
  const {
    documents,
    isLoadingDocuments,
    deleteDocument,
    isDeleting,
    processDocument,
    isProcessing,
  } = useDocuments();

  const [processResult, setProcessResult] = useState<{
    success: boolean;
    message: string;
    documentId?: string;
  } | null>(null);

  // Track which documents have been processed (documentId -> outputFileId)
  const [processedDocs, setProcessedDocs] = useState<Record<string, string>>({});

  const handleProcess = async (documentId: string) => {
    setProcessingDocumentId(documentId);
    setProcessResult(null);
    try {
      const result = await processDocument(documentId, {
        highlight_changes: true,
        generate_changes_report: true,
      });
      console.log('Processing result:', result);
      // Store the processed output file ID for this document
      if (result.output_file_id) {
        setProcessedDocs(prev => ({ ...prev, [documentId]: result.output_file_id }));
      }
      setProcessResult({
        success: true,
        message: `Document processed successfully! ${result.total_replacements || 0} replacements made.`,
        documentId,
      });
    } catch (error) {
      console.error('Process error:', error);
      setProcessResult({
        success: false,
        message: error instanceof Error ? error.message : 'Processing failed',
      });
    } finally {
      setProcessingDocumentId(null);
    }
  };

  const handleDelete = async (documentId: string) => {
    if (confirm('Are you sure you want to delete this document?')) {
      await deleteDocument(documentId);
    }
  };

  const handleDownloadProcessed = async (outputId: string, filename: string) => {
    try {
      const response = await documentsApi.downloadProcessed(outputId);
      const blob = new Blob([response.data], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `processed_${filename}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Download error:', error);
      alert('Failed to download file');
    }
  };

  const handleDownloadOriginal = async (documentId: string, filename: string) => {
    try {
      const response = await documentsApi.downloadOriginal(documentId);
      const blob = new Blob([response.data], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Download error:', error);
      alert('Failed to download file');
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Documents</h1>
          <p className="text-muted-foreground">
            Upload and process your documents
          </p>
        </div>
        <Dialog open={uploadDialogOpen} onOpenChange={setUploadDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <Upload className="mr-2 h-4 w-4" />
              Upload Document
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-md">
            <DialogHeader>
              <DialogTitle>Upload Document</DialogTitle>
              <DialogDescription>
                Upload a document to process. Supported formats: DOCX, PDF, TXT
              </DialogDescription>
            </DialogHeader>
            <DocumentUpload onSuccess={() => setUploadDialogOpen(false)} />
          </DialogContent>
        </Dialog>
      </div>

      {processResult && (
        <Alert variant={processResult.success ? 'default' : 'destructive'}>
          {processResult.success ? (
            <CheckCircle className="h-4 w-4" />
          ) : (
            <XCircle className="h-4 w-4" />
          )}
          <AlertTitle>{processResult.success ? 'Success!' : 'Error'}</AlertTitle>
          <AlertDescription>{processResult.message}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Your Documents</CardTitle>
          <CardDescription>
            {documents.length} document{documents.length !== 1 ? 's' : ''} uploaded
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoadingDocuments ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : documents.length === 0 ? (
            <div className="text-center py-12">
              <FileText className="mx-auto h-12 w-12 text-muted-foreground/50" />
              <h3 className="mt-4 text-lg font-medium">No documents yet</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                Upload your first document to get started
              </p>
              <Button
                className="mt-4"
                onClick={() => setUploadDialogOpen(true)}
              >
                <Upload className="mr-2 h-4 w-4" />
                Upload Document
              </Button>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Size</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Uploaded</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.map((doc: Document) => (
                  <TableRow key={doc.id}>
                    <TableCell className="font-medium">
                      <button
                        className="flex items-center space-x-2 hover:text-primary transition-colors text-left"
                        onClick={() => handleDownloadOriginal(doc.id, doc.original_filename)}
                        title="Download original"
                      >
                        <FileText className="h-4 w-4 text-muted-foreground" />
                        <span className="truncate max-w-[200px] hover:underline">
                          {doc.original_filename}
                        </span>
                      </button>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{doc.file_type.toUpperCase()}</Badge>
                    </TableCell>
                    <TableCell>{formatFileSize(doc.file_size)}</TableCell>
                    <TableCell>
                      <Badge variant={getStatusBadgeVariant(doc.status)}>
                        {doc.status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {formatDistanceToNow(new Date(doc.created_at), {
                        addSuffix: true,
                      })}
                    </TableCell>
                    <TableCell className="text-right">
                      <ActionButtonGroup className="justify-end">
                        {doc.status === 'completed' && (
                          <>
                            <ActionButton
                              tooltip="Configure term mappings"
                              icon={<Settings2 className="h-4 w-4" />}
                              onClick={() => setTermMapperDoc({ id: doc.id, name: doc.original_filename })}
                            />
                            <ActionButton
                              tooltip="Process with AI"
                              icon={<Sparkles className="h-4 w-4" />}
                              onClick={() => handleProcess(doc.id)}
                              loading={isProcessing && processingDocumentId === doc.id}
                              primary
                            />
                            {processedDocs[doc.id] ? (
                              <ActionButton
                                tooltip="Download processed"
                                icon={<Download className="h-4 w-4" />}
                                onClick={() => handleDownloadProcessed(processedDocs[doc.id], doc.original_filename)}
                              />
                            ) : (
                              <ActionButton
                                tooltip="Download original"
                                icon={<Download className="h-4 w-4" />}
                                onClick={() => handleDownloadOriginal(doc.id, doc.original_filename)}
                              />
                            )}
                          </>
                        )}
                        <ActionButton
                          tooltip="Delete document"
                          icon={<Trash2 className="h-4 w-4" />}
                          onClick={() => handleDelete(doc.id)}
                          disabled={isDeleting}
                          destructive
                        />
                      </ActionButtonGroup>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {processingDocumentId && (
        <ProcessingStatus
          documentId={processingDocumentId}
          onComplete={() => setProcessingDocumentId(null)}
        />
      )}

      {termMapperDoc && (
        <TermMapper
          documentId={termMapperDoc.id}
          documentName={termMapperDoc.name}
          open={!!termMapperDoc}
          onOpenChange={(open) => !open && setTermMapperDoc(null)}
        />
      )}
    </div>
  );
}
