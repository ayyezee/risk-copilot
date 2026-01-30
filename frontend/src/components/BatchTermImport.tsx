import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Button } from './ui/button';
import { Textarea } from './ui/textarea';
import { Label } from './ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from './ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from './ui/table';
import { Upload, Loader2, Check, X, AlertCircle } from 'lucide-react';
import { referenceLibraryApi } from '../services/api';

interface ParsedMapping {
  original: string;
  replacement: string;
  valid: boolean;
}

export function BatchTermImport() {
  const [open, setOpen] = useState(false);
  const [inputText, setInputText] = useState('');
  const [parsedMappings, setParsedMappings] = useState<ParsedMapping[]>([]);
  const [step, setStep] = useState<'input' | 'preview'>('input');
  const queryClient = useQueryClient();

  const importMutation = useMutation({
    mutationFn: async (mappings: { original: string; replacement: string }[]) => {
      // Import each mapping as a reference example
      const results = await Promise.allSettled(
        mappings.map((mapping) =>
          referenceLibraryApi.createExample({
            name: `${mapping.original} → ${mapping.replacement}`,
            original_text: mapping.original,
            converted_text: mapping.replacement,
          })
        )
      );

      const succeeded = results.filter((r) => r.status === 'fulfilled').length;
      const failed = results.filter((r) => r.status === 'rejected').length;

      return { succeeded, failed };
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['referenceExamples'] });
      if (data.failed === 0) {
        handleClose();
      }
    },
  });

  const parseInput = () => {
    const lines = inputText.trim().split('\n');
    const mappings: ParsedMapping[] = [];

    for (const line of lines) {
      const trimmedLine = line.trim();
      if (!trimmedLine) continue;

      // Try different separators: " - ", " – ", " → ", " = ", tab
      const separators = [' - ', ' – ', ' → ', ' = ', '\t'];
      let parsed = false;

      for (const sep of separators) {
        const parts = trimmedLine.split(sep);
        if (parts.length >= 2) {
          const original = parts[0].trim();
          const replacement = parts.slice(1).join(sep).trim();

          if (original && replacement) {
            mappings.push({
              original,
              replacement,
              valid: true,
            });
            parsed = true;
            break;
          }
        }
      }

      if (!parsed && trimmedLine) {
        // Couldn't parse this line
        mappings.push({
          original: trimmedLine,
          replacement: '',
          valid: false,
        });
      }
    }

    setParsedMappings(mappings);
    setStep('preview');
  };

  const handleImport = () => {
    const validMappings = parsedMappings
      .filter((m) => m.valid)
      .map((m) => ({ original: m.original, replacement: m.replacement }));

    importMutation.mutate(validMappings);
  };

  const handleClose = () => {
    setOpen(false);
    setInputText('');
    setParsedMappings([]);
    setStep('input');
    importMutation.reset();
  };

  const validCount = parsedMappings.filter((m) => m.valid).length;
  const invalidCount = parsedMappings.filter((m) => !m.valid).length;

  return (
    <Dialog open={open} onOpenChange={(isOpen) => {
      if (!isOpen) handleClose();
      else setOpen(true);
    }}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <Upload className="mr-2 h-4 w-4" />
          Batch Import
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-2xl max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Batch Import Term Mappings</DialogTitle>
          <DialogDescription>
            Paste your term mappings below. Use format: <code className="bg-muted px-1 rounded">Original Term - Replacement Term</code>
          </DialogDescription>
        </DialogHeader>

        {step === 'input' && (
          <>
            <div className="space-y-4 flex-1">
              <div className="space-y-2">
                <Label htmlFor="mappings">Term Mappings</Label>
                <Textarea
                  id="mappings"
                  placeholder={`Fund - XYZ Series
Investment Manager - Investment Subadvisor
Limited Partners - Series Limited Partners
Partnership - Portfolio Funds`}
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  className="min-h-[300px] font-mono text-sm"
                />
              </div>
              <p className="text-xs text-muted-foreground">
                Supports separators: <code>-</code>, <code>–</code>, <code>→</code>, <code>=</code>, or tab
              </p>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={handleClose}>
                Cancel
              </Button>
              <Button onClick={parseInput} disabled={!inputText.trim()}>
                Preview Mappings
              </Button>
            </DialogFooter>
          </>
        )}

        {step === 'preview' && (
          <>
            <div className="flex-1 overflow-hidden flex flex-col">
              <div className="flex items-center gap-4 mb-4">
                <div className="flex items-center gap-2 text-sm">
                  <Check className="h-4 w-4 text-green-600" />
                  <span>{validCount} valid</span>
                </div>
                {invalidCount > 0 && (
                  <div className="flex items-center gap-2 text-sm text-destructive">
                    <AlertCircle className="h-4 w-4" />
                    <span>{invalidCount} invalid (will be skipped)</span>
                  </div>
                )}
              </div>

              <div className="border rounded-md overflow-auto flex-1">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-10"></TableHead>
                      <TableHead>Original Term</TableHead>
                      <TableHead>Replacement</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {parsedMappings.map((mapping, index) => (
                      <TableRow key={index} className={!mapping.valid ? 'bg-destructive/10' : ''}>
                        <TableCell>
                          {mapping.valid ? (
                            <Check className="h-4 w-4 text-green-600" />
                          ) : (
                            <X className="h-4 w-4 text-destructive" />
                          )}
                        </TableCell>
                        <TableCell className="font-mono text-sm">
                          {mapping.original}
                        </TableCell>
                        <TableCell className="font-mono text-sm">
                          {mapping.replacement || <span className="text-muted-foreground italic">Could not parse</span>}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              {importMutation.isSuccess && (
                <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-md text-sm text-green-800">
                  Successfully imported {importMutation.data.succeeded} mappings
                  {importMutation.data.failed > 0 && ` (${importMutation.data.failed} failed)`}
                </div>
              )}

              {importMutation.isError && (
                <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-800">
                  Error importing mappings. Please try again.
                </div>
              )}
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={() => setStep('input')}>
                Back
              </Button>
              <Button
                onClick={handleImport}
                disabled={validCount === 0 || importMutation.isPending}
              >
                {importMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Import {validCount} Mapping{validCount !== 1 ? 's' : ''}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
