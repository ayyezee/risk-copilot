import { useState, useCallback, useEffect, useRef } from 'react';
import { useMutation } from '@tanstack/react-query';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { Checkbox } from './ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './ui/dialog';
import { Badge } from './ui/badge';
import { Loader2, Check, X, Search, Plus, Trash2, Layers } from 'lucide-react';
import { documentsApi } from '../services/api';

export interface DetectedSection {
  id: string;
  title: string;
  description?: string;
  start_page: number;
  end_page: number;
  section_type?: string;
  confidence: number;
}

export interface PageRange {
  start_page: number;
  end_page: number;
  label?: string;
}

interface SectionSelectorProps {
  documentId: string;
  documentName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSectionsSelected: (sections: DetectedSection[], pageRanges: PageRange[]) => void;
  initialSections?: DetectedSection[];
  initialPageRanges?: PageRange[];
}

export function SectionSelector({
  documentId,
  documentName,
  open,
  onOpenChange,
  onSectionsSelected,
  initialSections,
  initialPageRanges,
}: SectionSelectorProps) {
  const [step, setStep] = useState<'detecting' | 'selecting'>('detecting');
  const [sections, setSections] = useState<DetectedSection[]>([]);
  const [pageCount, setPageCount] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [manualRanges, setManualRanges] = useState<PageRange[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [detectError, setDetectError] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const hasStartedDetection = useRef(false);

  // New manual range input state
  const [newRangeStart, setNewRangeStart] = useState('');
  const [newRangeEnd, setNewRangeEnd] = useState('');
  const [newRangeLabel, setNewRangeLabel] = useState('');

  // Detect sections mutation
  const detectMutation = useMutation({
    mutationFn: async () => {
      const response = await documentsApi.detectSections(documentId);
      return response.data;
    },
    onSuccess: (data) => {
      setSections(data.sections || []);
      setPageCount(data.page_count || null);
      setWarnings(data.warnings || []);
      // Pre-select all sections by default
      setSelectedIds(new Set((data.sections || []).map(s => s.id)));
      setStep('selecting');
    },
    onError: (error: Error) => {
      setDetectError(error.message || 'Failed to detect sections');
    },
  });

  // Start detection when dialog opens (unless we have initial data)
  useEffect(() => {
    if (open && !hasStartedDetection.current) {
      hasStartedDetection.current = true;

      if (initialSections && initialSections.length > 0) {
        // Use cached sections
        setSections(initialSections);
        setSelectedIds(new Set(initialSections.map(s => s.id)));
        setManualRanges(initialPageRanges || []);
        setStep('selecting');
      } else {
        // Detect sections
        setStep('detecting');
        setSections([]);
        setSelectedIds(new Set());
        setManualRanges([]);
        setDetectError(null);
        detectMutation.mutate();
      }
    }

    if (!open) {
      hasStartedDetection.current = false;
    }
  }, [open, initialSections, initialPageRanges]);

  const handleToggleSection = useCallback((sectionId: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(sectionId)) {
        next.delete(sectionId);
      } else {
        next.add(sectionId);
      }
      return next;
    });
  }, []);

  const handleSelectAll = useCallback(() => {
    setSelectedIds(new Set(sections.map(s => s.id)));
  }, [sections]);

  const handleDeselectAll = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const handleAddManualRange = useCallback(() => {
    const start = parseInt(newRangeStart, 10);
    const end = parseInt(newRangeEnd, 10);

    if (isNaN(start) || isNaN(end) || start < 1 || end < start) {
      return;
    }

    if (pageCount && end > pageCount) {
      return;
    }

    setManualRanges(prev => [
      ...prev,
      { start_page: start, end_page: end, label: newRangeLabel || undefined },
    ]);
    setNewRangeStart('');
    setNewRangeEnd('');
    setNewRangeLabel('');
  }, [newRangeStart, newRangeEnd, newRangeLabel, pageCount]);

  const handleRemoveManualRange = useCallback((index: number) => {
    setManualRanges(prev => prev.filter((_, i) => i !== index));
  }, []);

  const handleConfirm = useCallback(() => {
    const selectedSections = sections.filter(s => selectedIds.has(s.id));
    onSectionsSelected(selectedSections, manualRanges);
    onOpenChange(false);
  }, [sections, selectedIds, manualRanges, onSectionsSelected, onOpenChange]);

  const handleRetry = useCallback(() => {
    setDetectError(null);
    detectMutation.mutate();
  }, [detectMutation]);

  // Filter sections by search query
  const filteredSections = sections.filter(s =>
    s.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    (s.description || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
    (s.section_type || '').toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Calculate total selected pages
  const selectedPageCount = sections
    .filter(s => selectedIds.has(s.id))
    .reduce((total, s) => total + (s.end_page - s.start_page + 1), 0);

  const manualPageCount = manualRanges.reduce(
    (total, r) => total + (r.end_page - r.start_page + 1),
    0
  );

  const getSectionTypeBadge = (type?: string) => {
    if (!type) return null;
    const colors: Record<string, string> = {
      definitions: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
      risk_disclosures: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
      terms_and_conditions: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
      fee_structure: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
      regulatory: 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
    };
    return (
      <span className={`text-xs px-2 py-0.5 rounded-full ${colors[type] || 'bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200'}`}>
        {type.replace(/_/g, ' ')}
      </span>
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-3xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Layers className="h-5 w-5" />
            Select Sections to Process
          </DialogTitle>
          <DialogDescription>
            {documentName}
          </DialogDescription>
        </DialogHeader>

        {step === 'detecting' && (
          <div className="flex-1 flex flex-col items-center justify-center py-12">
            {detectError ? (
              <div className="text-center">
                <X className="mx-auto h-12 w-12 text-destructive" />
                <p className="mt-4 text-sm text-destructive">{detectError}</p>
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
                  Analyzing document structure...
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Detecting sections and page ranges
                </p>
              </div>
            )}
          </div>
        )}

        {step === 'selecting' && (
          <>
            {/* Stats bar */}
            <div className="flex items-center justify-between py-2 border-b">
              <div className="flex items-center gap-4">
                <p className="text-sm text-muted-foreground">
                  Found <strong>{sections.length}</strong> sections
                  {pageCount && <span className="ml-1">({pageCount} pages)</span>}
                </p>
                <div className="flex gap-2">
                  <Button variant="ghost" size="sm" onClick={handleSelectAll}>
                    Select All
                  </Button>
                  <Button variant="ghost" size="sm" onClick={handleDeselectAll}>
                    Deselect All
                  </Button>
                </div>
              </div>
              <Badge variant="outline">
                {selectedIds.size} selected ({selectedPageCount + manualPageCount} pages)
              </Badge>
            </div>

            {/* Search */}
            <div className="relative py-2">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search sections..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9"
              />
            </div>

            {/* Warnings */}
            {warnings.length > 0 && (
              <div className="text-xs text-amber-600 dark:text-amber-400 py-1">
                {warnings.map((w, i) => (
                  <p key={i}>{w}</p>
                ))}
              </div>
            )}

            {/* Section list */}
            <div className="flex-1 overflow-y-auto py-2 space-y-2 min-h-[200px] max-h-[300px]">
              {filteredSections.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  {sections.length === 0
                    ? 'No sections detected in this document.'
                    : 'No sections match your search.'}
                </div>
              ) : (
                filteredSections.map((section) => (
                  <div
                    key={section.id}
                    className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                      selectedIds.has(section.id)
                        ? 'bg-primary/5 border-primary/30'
                        : 'bg-card hover:bg-accent/50'
                    }`}
                    onClick={() => handleToggleSection(section.id)}
                  >
                    <Checkbox
                      checked={selectedIds.has(section.id)}
                      onCheckedChange={() => handleToggleSection(section.id)}
                      onClick={(e) => e.stopPropagation()}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-sm truncate">
                          {section.title}
                        </span>
                        {getSectionTypeBadge(section.section_type)}
                      </div>
                      {section.description && (
                        <p className="text-xs text-muted-foreground truncate mt-0.5">
                          {section.description}
                        </p>
                      )}
                    </div>
                    <div className="text-right flex-shrink-0">
                      <p className="text-sm font-mono">
                        {section.start_page === section.end_page
                          ? `p. ${section.start_page}`
                          : `pp. ${section.start_page}-${section.end_page}`}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {Math.round(section.confidence * 100)}% confidence
                      </p>
                    </div>
                  </div>
                ))
              )}
            </div>

            {/* Manual page ranges */}
            <div className="border-t pt-4">
              <Label className="text-sm font-medium">Manual Page Ranges</Label>
              <p className="text-xs text-muted-foreground mb-2">
                Add custom page ranges if section detection missed something
              </p>

              {/* Existing manual ranges */}
              {manualRanges.length > 0 && (
                <div className="space-y-2 mb-3">
                  {manualRanges.map((range, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-2 p-2 rounded bg-muted/50"
                    >
                      <span className="text-sm flex-1">
                        {range.label || `Custom range`}: Pages {range.start_page}-{range.end_page}
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleRemoveManualRange(i)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  ))}
                </div>
              )}

              {/* Add new range */}
              <div className="flex items-end gap-2">
                <div className="flex-1">
                  <Label className="text-xs">Label (optional)</Label>
                  <Input
                    placeholder="e.g., Appendix A"
                    value={newRangeLabel}
                    onChange={(e) => setNewRangeLabel(e.target.value)}
                    className="h-8"
                  />
                </div>
                <div className="w-20">
                  <Label className="text-xs">Start</Label>
                  <Input
                    type="number"
                    min={1}
                    max={pageCount || undefined}
                    placeholder="1"
                    value={newRangeStart}
                    onChange={(e) => setNewRangeStart(e.target.value)}
                    className="h-8"
                  />
                </div>
                <div className="w-20">
                  <Label className="text-xs">End</Label>
                  <Input
                    type="number"
                    min={1}
                    max={pageCount || undefined}
                    placeholder={pageCount?.toString() || ''}
                    value={newRangeEnd}
                    onChange={(e) => setNewRangeEnd(e.target.value)}
                    className="h-8"
                  />
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleAddManualRange}
                  disabled={!newRangeStart || !newRangeEnd}
                  className="h-8"
                >
                  <Plus className="h-4 w-4" />
                </Button>
              </div>
            </div>

            <DialogFooter className="border-t pt-4">
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button
                onClick={handleConfirm}
                disabled={selectedIds.size === 0 && manualRanges.length === 0}
              >
                <Check className="mr-2 h-4 w-4" />
                Confirm Selection
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
