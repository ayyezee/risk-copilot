import { useState, useCallback, useEffect, useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Button } from './ui/button';
import { Input } from './ui/input';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from './ui/tooltip';
import { Badge } from './ui/badge';
import { Loader2, Check, X, Sparkles, ArrowRight } from 'lucide-react';
import { documentsApi, referenceLibraryApi } from '../services/api';

interface ExtractedTerm {
  term: string;
  contexts: string[];
  definition: string | null;
  suggested_replacement: string | null;
}

interface TermMapping {
  original: string;
  replacement: string;
  contexts: string[];
  hasSuggestion: boolean;
}

interface TermMapperProps {
  documentId: string;
  documentName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function TermMapper({ documentId, documentName, open, onOpenChange }: TermMapperProps) {
  const [step, setStep] = useState<'extracting' | 'mapping' | 'saving'>('extracting');
  const [terms, setTerms] = useState<ExtractedTerm[]>([]);
  const [mappings, setMappings] = useState<Record<string, string>>({});
  const [extractError, setExtractError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const hasStartedExtraction = useRef(false);

  // Extract terms mutation
  const extractMutation = useMutation({
    mutationFn: async () => {
      const response = await documentsApi.extractTerms(documentId);
      return response.data;
    },
    onSuccess: (data) => {
      setTerms(data.terms || []);
      // Pre-fill with suggestions
      const initialMappings: Record<string, string> = {};
      for (const term of data.terms || []) {
        if (term.suggested_replacement) {
          initialMappings[term.term] = term.suggested_replacement;
        }
      }
      setMappings(initialMappings);
      setStep('mapping');
    },
    onError: (error: Error) => {
      setExtractError(error.message || 'Failed to extract terms');
    },
  });

  // Save mappings mutation
  const saveMutation = useMutation({
    mutationFn: async (termMappings: TermMapping[]) => {
      const results = await Promise.allSettled(
        termMappings.map((mapping) =>
          referenceLibraryApi.createExample({
            name: `${mapping.original} → ${mapping.replacement}`,
            original_text: mapping.original,
            converted_text: mapping.replacement,
            description: mapping.contexts[0] ? `Context: "${mapping.contexts[0].substring(0, 200)}..."` : undefined,
          })
        )
      );

      const succeeded = results.filter((r) => r.status === 'fulfilled').length;
      const failed = results.filter((r) => r.status === 'rejected').length;

      return { succeeded, failed };
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['referenceExamples'] });
      onOpenChange(false);
    },
  });

  // Start extraction when dialog opens
  useEffect(() => {
    if (open && !hasStartedExtraction.current) {
      hasStartedExtraction.current = true;
      setStep('extracting');
      setTerms([]);
      setMappings({});
      setExtractError(null);
      extractMutation.mutate();
    }

    if (!open) {
      hasStartedExtraction.current = false;
    }
  }, [open]);

  const handleMappingChange = useCallback((term: string, value: string) => {
    setMappings((prev) => ({
      ...prev,
      [term]: value,
    }));
  }, []);

  const handleSave = useCallback(() => {
    const mappingsToSave: TermMapping[] = [];

    for (const term of terms) {
      const replacement = mappings[term.term];
      if (replacement && replacement.trim() && replacement !== term.term) {
        mappingsToSave.push({
          original: term.term,
          replacement: replacement.trim(),
          contexts: term.contexts,
          hasSuggestion: !!term.suggested_replacement,
        });
      }
    }

    if (mappingsToSave.length > 0) {
      setStep('saving');
      saveMutation.mutate(mappingsToSave);
    }
  }, [terms, mappings, saveMutation]);

  const handleRetry = useCallback(() => {
    setExtractError(null);
    extractMutation.mutate();
  }, [extractMutation]);

  const mappedCount = Object.entries(mappings).filter(
    ([term, replacement]) => replacement && replacement.trim() && replacement !== term
  ).length;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle>Map Defined Terms</DialogTitle>
          <DialogDescription>
            {documentName}
          </DialogDescription>
        </DialogHeader>

        {step === 'extracting' && (
          <div className="flex-1 flex flex-col items-center justify-center py-12">
            {extractError ? (
              <div className="text-center">
                <X className="mx-auto h-12 w-12 text-destructive" />
                <p className="mt-4 text-sm text-destructive">{extractError}</p>
                <Button
                  className="mt-4"
                  variant="outline"
                  onClick={handleRetry}
                >
                  Try Again
                </Button>
              </div>
            ) : (
              <div className="text-center">
                <Loader2 className="mx-auto h-12 w-12 animate-spin text-primary" />
                <p className="mt-4 text-sm text-muted-foreground">
                  Analyzing document for defined terms...
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  This may take a few seconds
                </p>
              </div>
            )}
          </div>
        )}

        {step === 'mapping' && (
          <>
            <div className="flex items-center justify-between py-2 border-b">
              <p className="text-sm text-muted-foreground">
                Found <strong>{terms.length}</strong> defined terms
              </p>
              <Badge variant="outline">
                {mappedCount} mapped
              </Badge>
            </div>

            <div className="flex-1 overflow-y-auto py-4 space-y-3">
              <TooltipProvider delayDuration={300}>
                {terms.map((term) => (
                  <div
                    key={term.term}
                    className="flex items-center gap-3 p-3 rounded-lg border bg-card hover:bg-accent/50 transition-colors"
                  >
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div className="flex-1 min-w-0 cursor-help">
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm font-medium truncate">
                              {term.term}
                            </span>
                            {term.suggested_replacement && (
                              <Sparkles className="h-3 w-3 text-amber-500 flex-shrink-0" />
                            )}
                          </div>
                          {term.definition && (
                            <p className="text-xs text-muted-foreground truncate mt-0.5">
                              {term.definition}
                            </p>
                          )}
                        </div>
                      </TooltipTrigger>
                      <TooltipContent
                        side="left"
                        align="start"
                        className="max-w-md p-4"
                      >
                        <p className="font-medium mb-2">Context in document:</p>
                        <div className="space-y-2">
                          {term.contexts.slice(0, 2).map((ctx, i) => (
                            <p key={i} className="text-sm text-muted-foreground italic">
                              "...{ctx.length > 150 ? ctx.substring(0, 150) + '...' : ctx}..."
                            </p>
                          ))}
                          {term.contexts.length === 0 && (
                            <p className="text-sm text-muted-foreground italic">No context available</p>
                          )}
                        </div>
                        {term.definition && (
                          <div className="mt-3 pt-2 border-t">
                            <p className="text-xs font-medium">Definition:</p>
                            <p className="text-xs text-muted-foreground">{term.definition}</p>
                          </div>
                        )}
                      </TooltipContent>
                    </Tooltip>

                    <ArrowRight className="h-4 w-4 text-muted-foreground flex-shrink-0" />

                    <div className="flex-1 min-w-0">
                      <Input
                        placeholder="Enter replacement..."
                        value={mappings[term.term] || ''}
                        onChange={(e) => handleMappingChange(term.term, e.target.value)}
                        className="h-9 font-mono text-sm"
                      />
                    </div>
                  </div>
                ))}
              </TooltipProvider>

              {terms.length === 0 && (
                <div className="text-center py-8">
                  <p className="text-muted-foreground">No defined terms found in this document.</p>
                </div>
              )}
            </div>

            <DialogFooter className="border-t pt-4">
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button onClick={handleSave} disabled={mappedCount === 0}>
                Save {mappedCount} Mapping{mappedCount !== 1 ? 's' : ''}
              </Button>
            </DialogFooter>
          </>
        )}

        {step === 'saving' && (
          <div className="flex-1 flex flex-col items-center justify-center py-12">
            {saveMutation.isSuccess ? (
              <div className="text-center">
                <Check className="mx-auto h-12 w-12 text-green-600" />
                <p className="mt-4 text-sm">
                  Successfully saved {saveMutation.data?.succeeded} term mappings!
                </p>
              </div>
            ) : (
              <div className="text-center">
                <Loader2 className="mx-auto h-12 w-12 animate-spin text-primary" />
                <p className="mt-4 text-sm text-muted-foreground">
                  Saving mappings to reference library...
                </p>
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
