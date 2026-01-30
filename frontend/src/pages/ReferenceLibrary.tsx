import { useState } from 'react';
import { useReferenceLibrary } from '../hooks/useDocuments';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import { Badge } from '../components/ui/badge';
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
  BookOpen,
  Plus,
  Edit,
  Trash2,
  Search,
  Loader2,
} from 'lucide-react';
import { formatDistanceToNow } from 'date-fns';

interface ReferenceExample {
  id: string;
  name: string;
  category?: string;
  original_text: string;
  corrected_text: string;
  notes?: string;
  created_at: string;
}

export function ReferenceLibraryPage() {
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editingExample, setEditingExample] = useState<ReferenceExample | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [formData, setFormData] = useState({
    name: '',
    category: '',
    original_text: '',
    corrected_text: '',
    notes: '',
  });

  const {
    examples,
    isLoadingExamples,
    createExample,
    isCreatingExample,
    updateExample,
    isUpdatingExample,
    deleteExample,
    isDeletingExample,
    searchSimilar,
    isSearching,
    searchResults,
  } = useReferenceLibrary();

  const handleCreateOrUpdate = async () => {
    if (editingExample) {
      await updateExample(editingExample.id, formData);
      setEditingExample(null);
    } else {
      await createExample(formData);
    }
    setCreateDialogOpen(false);
    resetForm();
  };

  const handleEdit = (example: ReferenceExample) => {
    setEditingExample(example);
    setFormData({
      name: example.name,
      category: example.category || '',
      original_text: example.original_text,
      corrected_text: example.corrected_text,
      notes: example.notes || '',
    });
    setCreateDialogOpen(true);
  };

  const handleDelete = async (id: string) => {
    if (confirm('Are you sure you want to delete this example?')) {
      await deleteExample(id);
    }
  };

  const handleSearch = () => {
    if (searchQuery.trim()) {
      searchSimilar(searchQuery, 10);
    }
  };

  const resetForm = () => {
    setFormData({
      name: '',
      category: '',
      original_text: '',
      corrected_text: '',
      notes: '',
    });
    setEditingExample(null);
  };

  const filteredExamples = examples.filter(
    (example: ReferenceExample) =>
      example.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      example.original_text.toLowerCase().includes(searchQuery.toLowerCase()) ||
      example.corrected_text.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Reference Library</h1>
          <p className="text-muted-foreground">
            Manage your reference examples for text processing
          </p>
        </div>
        <Dialog
          open={createDialogOpen}
          onOpenChange={(open) => {
            setCreateDialogOpen(open);
            if (!open) resetForm();
          }}
        >
          <DialogTrigger asChild>
            <Button>
              <Plus className="mr-2 h-4 w-4" />
              Add Example
            </Button>
          </DialogTrigger>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle>
                {editingExample ? 'Edit Example' : 'Add New Example'}
              </DialogTitle>
              <DialogDescription>
                {editingExample
                  ? 'Update this reference example'
                  : 'Create a new reference example for text processing'}
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="name">Name</Label>
                <Input
                  id="name"
                  placeholder="Example name"
                  value={formData.name}
                  onChange={(e) =>
                    setFormData({ ...formData, name: e.target.value })
                  }
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="category">Category (optional)</Label>
                <Input
                  id="category"
                  placeholder="e.g., Grammar, Style, Terminology"
                  value={formData.category}
                  onChange={(e) =>
                    setFormData({ ...formData, category: e.target.value })
                  }
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="original_text">Original Text</Label>
                <Textarea
                  id="original_text"
                  placeholder="Text before correction"
                  value={formData.original_text}
                  onChange={(e) =>
                    setFormData({ ...formData, original_text: e.target.value })
                  }
                  rows={3}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="corrected_text">Corrected Text</Label>
                <Textarea
                  id="corrected_text"
                  placeholder="Text after correction"
                  value={formData.corrected_text}
                  onChange={(e) =>
                    setFormData({ ...formData, corrected_text: e.target.value })
                  }
                  rows={3}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="notes">Notes (optional)</Label>
                <Textarea
                  id="notes"
                  placeholder="Additional context or explanation"
                  value={formData.notes}
                  onChange={(e) =>
                    setFormData({ ...formData, notes: e.target.value })
                  }
                  rows={2}
                />
              </div>
            </div>

            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setCreateDialogOpen(false);
                  resetForm();
                }}
              >
                Cancel
              </Button>
              <Button
                onClick={handleCreateOrUpdate}
                disabled={
                  !formData.name ||
                  !formData.original_text ||
                  !formData.corrected_text ||
                  isCreatingExample ||
                  isUpdatingExample
                }
              >
                {(isCreatingExample || isUpdatingExample) && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                {editingExample ? 'Update' : 'Create'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Examples</CardTitle>
              <CardDescription>
                {examples.length} example{examples.length !== 1 ? 's' : ''} in your library
              </CardDescription>
            </div>
            <div className="flex items-center space-x-2">
              <Input
                placeholder="Search examples..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-64"
              />
              <Button variant="outline" size="icon" onClick={handleSearch}>
                {isSearching ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Search className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isLoadingExamples ? (
            <div className="flex justify-center py-8">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : filteredExamples.length === 0 ? (
            <div className="text-center py-12">
              <BookOpen className="mx-auto h-12 w-12 text-muted-foreground/50" />
              <h3 className="mt-4 text-lg font-medium">No examples yet</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                Add your first reference example to improve processing accuracy
              </p>
              <Button
                className="mt-4"
                onClick={() => setCreateDialogOpen(true)}
              >
                <Plus className="mr-2 h-4 w-4" />
                Add Example
              </Button>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Category</TableHead>
                  <TableHead>Original</TableHead>
                  <TableHead>Corrected</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredExamples.map((example: ReferenceExample) => (
                  <TableRow key={example.id}>
                    <TableCell className="font-medium">{example.name}</TableCell>
                    <TableCell>
                      {example.category ? (
                        <Badge variant="outline">{example.category}</Badge>
                      ) : (
                        <span className="text-muted-foreground">-</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <span className="truncate max-w-[150px] block text-sm text-muted-foreground">
                        {example.original_text}
                      </span>
                    </TableCell>
                    <TableCell>
                      <span className="truncate max-w-[150px] block text-sm">
                        {example.corrected_text}
                      </span>
                    </TableCell>
                    <TableCell>
                      {formatDistanceToNow(new Date(example.created_at), {
                        addSuffix: true,
                      })}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end space-x-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleEdit(example)}
                        >
                          <Edit className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => handleDelete(example.id)}
                          disabled={isDeletingExample}
                        >
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {searchResults && searchResults.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Similar Examples Found</CardTitle>
            <CardDescription>
              Based on semantic similarity to your search query
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {searchResults.map((result: { id: string; name: string; similarity: number }) => (
                <li
                  key={result.id}
                  className="flex items-center justify-between p-2 bg-muted rounded"
                >
                  <span>{result.name}</span>
                  <Badge variant="secondary">
                    {Math.round(result.similarity * 100)}% similar
                  </Badge>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
