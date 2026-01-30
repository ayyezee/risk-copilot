import { useState, useCallback } from 'react';
import { useDocuments } from '../hooks/useDocuments';
import { Button } from './ui/button';
import { Progress } from './ui/progress';
import { Upload, File, X, CheckCircle2, Loader2 } from 'lucide-react';

interface DocumentUploadProps {
  onSuccess?: () => void;
}

export function DocumentUpload({ onSuccess }: DocumentUploadProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const { uploadDocument, uploadProgress, isUploading, uploadError } = useDocuments();

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);

    const file = e.dataTransfer.files[0];
    if (file && isValidFile(file)) {
      setSelectedFile(file);
    }
  }, []);

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = () => {
    setIsDragOver(false);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file && isValidFile(file)) {
      setSelectedFile(file);
    }
  };

  const isValidFile = (file: File): boolean => {
    const validTypes = [
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'application/pdf',
      'text/plain',
    ];
    return validTypes.includes(file.type) || file.name.endsWith('.docx') || file.name.endsWith('.pdf') || file.name.endsWith('.txt');
  };

  const handleUpload = async () => {
    if (!selectedFile) return;

    try {
      await uploadDocument(selectedFile);
      setSelectedFile(null);
      onSuccess?.();
    } catch (error) {
      // Error is handled by the mutation
    }
  };

  const progress = selectedFile ? uploadProgress[selectedFile.name] || 0 : 0;

  return (
    <div className="space-y-4">
      <div
        className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
          isDragOver
            ? 'border-primary bg-primary/5'
            : 'border-muted-foreground/25 hover:border-muted-foreground/50'
        }`}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
      >
        <Upload className="mx-auto h-10 w-10 text-muted-foreground/50" />
        <p className="mt-2 text-sm text-muted-foreground">
          Drag and drop a file here, or{' '}
          <label className="text-primary cursor-pointer hover:underline">
            browse
            <input
              type="file"
              accept=".docx,.pdf,.txt"
              className="hidden"
              onChange={handleFileSelect}
              disabled={isUploading}
            />
          </label>
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          DOCX, PDF, TXT up to 10MB
        </p>
      </div>

      {selectedFile && (
        <div className="flex items-center justify-between p-3 bg-muted rounded-lg">
          <div className="flex items-center space-x-3">
            <File className="h-5 w-5 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium truncate max-w-[200px]">
                {selectedFile.name}
              </p>
              <p className="text-xs text-muted-foreground">
                {(selectedFile.size / 1024).toFixed(1)} KB
              </p>
            </div>
          </div>
          {!isUploading && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setSelectedFile(null)}
            >
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
      )}

      {isUploading && (
        <div className="space-y-2">
          <div className="flex justify-between text-sm">
            <span>Uploading...</span>
            <span>{progress}%</span>
          </div>
          <Progress value={progress} />
        </div>
      )}

      {uploadError && (
        <div className="p-3 text-sm text-red-500 bg-red-50 border border-red-200 rounded-md">
          {(uploadError as Error).message || 'Failed to upload file'}
        </div>
      )}

      <Button
        className="w-full"
        onClick={handleUpload}
        disabled={!selectedFile || isUploading}
      >
        {isUploading ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Uploading...
          </>
        ) : (
          <>
            <Upload className="mr-2 h-4 w-4" />
            Upload Document
          </>
        )}
      </Button>
    </div>
  );
}
