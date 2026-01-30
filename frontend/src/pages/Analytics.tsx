import { useQuery } from '@tanstack/react-query';
import { analyticsApi } from '../services/api';
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import {
  BarChart3,
  FileText,
  Clock,
  CheckCircle2,
  XCircle,
  TrendingUp,
  Loader2,
} from 'lucide-react';

interface DashboardData {
  total_documents_processed: number;
  total_replacements: number;
  average_processing_time_ms: number;
  success_rate: number;
  total_corrections: number;
  recent_activity: Array<{
    date: string;
    documents_processed: number;
    replacements: number;
  }>;
}

interface TermFrequencyItem {
  original_term: string;
  replacement: string;
  count: number;
  last_used: string;
}

interface Correction {
  id: string;
  original_term: string;
  ai_replacement: string;
  user_correction: string;
  context?: string;
  created_at: string;
}

export function Analytics() {
  const { data: dashboard, isLoading: isLoadingDashboard } = useQuery({
    queryKey: ['analytics', 'dashboard'],
    queryFn: async () => {
      const response = await analyticsApi.getDashboard();
      return response.data as DashboardData;
    },
  });

  const { data: termFrequency, isLoading: isLoadingTermFrequency } = useQuery({
    queryKey: ['analytics', 'termFrequency'],
    queryFn: async () => {
      const response = await analyticsApi.getTermFrequency({ limit: 20 });
      return response.data as TermFrequencyItem[];
    },
  });

  const { data: correctionsData, isLoading: isLoadingCorrections } = useQuery({
    queryKey: ['analytics', 'corrections'],
    queryFn: async () => {
      const response = await analyticsApi.getCorrections({ page_size: 10 });
      return response.data;
    },
  });

  const isLoading = isLoadingDashboard || isLoadingTermFrequency || isLoadingCorrections;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Analytics</h1>
        <p className="text-muted-foreground">
          Track your document processing metrics and insights
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Documents Processed
            </CardTitle>
            <FileText className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {dashboard?.total_documents_processed || 0}
            </div>
            <p className="text-xs text-muted-foreground">
              Total documents processed
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Total Replacements
            </CardTitle>
            <TrendingUp className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {dashboard?.total_replacements || 0}
            </div>
            <p className="text-xs text-muted-foreground">
              Terms corrected
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">
              Avg. Processing Time
            </CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {dashboard?.average_processing_time_ms
                ? `${(dashboard.average_processing_time_ms / 1000).toFixed(1)}s`
                : '0s'}
            </div>
            <p className="text-xs text-muted-foreground">
              Per document
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Success Rate</CardTitle>
            <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {dashboard?.success_rate
                ? `${(dashboard.success_rate * 100).toFixed(1)}%`
                : '100%'}
            </div>
            <p className="text-xs text-muted-foreground">
              Processing success rate
            </p>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="terms" className="space-y-4">
        <TabsList>
          <TabsTrigger value="terms">Top Terms</TabsTrigger>
          <TabsTrigger value="corrections">User Corrections</TabsTrigger>
          <TabsTrigger value="activity">Recent Activity</TabsTrigger>
        </TabsList>

        <TabsContent value="terms">
          <Card>
            <CardHeader>
              <CardTitle>Most Frequent Replacements</CardTitle>
              <CardDescription>
                Terms that are most commonly replaced during processing
              </CardDescription>
            </CardHeader>
            <CardContent>
              {termFrequency && termFrequency.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Original Term</TableHead>
                      <TableHead>Replacement</TableHead>
                      <TableHead className="text-right">Count</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {termFrequency.map((term: TermFrequencyItem, index: number) => (
                      <TableRow key={index}>
                        <TableCell className="font-mono text-sm text-muted-foreground">
                          {term.original_term}
                        </TableCell>
                        <TableCell className="font-mono text-sm">
                          {term.replacement}
                        </TableCell>
                        <TableCell className="text-right">
                          <Badge variant="secondary">{term.count}</Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <div className="text-center py-8">
                  <BarChart3 className="mx-auto h-12 w-12 text-muted-foreground/50" />
                  <h3 className="mt-4 text-lg font-medium">No data yet</h3>
                  <p className="mt-2 text-sm text-muted-foreground">
                    Process some documents to see term frequency data
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="corrections">
          <Card>
            <CardHeader>
              <CardTitle>User Corrections</CardTitle>
              <CardDescription>
                Corrections submitted by users to improve AI accuracy
              </CardDescription>
            </CardHeader>
            <CardContent>
              {correctionsData?.items && correctionsData.items.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Original</TableHead>
                      <TableHead>AI Suggested</TableHead>
                      <TableHead>User Correction</TableHead>
                      <TableHead>Context</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {correctionsData.items.map((correction: Correction) => (
                      <TableRow key={correction.id}>
                        <TableCell className="font-mono text-sm text-muted-foreground">
                          {correction.original_term}
                        </TableCell>
                        <TableCell>
                          <span className="font-mono text-sm line-through text-red-500">
                            {correction.ai_replacement}
                          </span>
                        </TableCell>
                        <TableCell>
                          <span className="font-mono text-sm text-green-600">
                            {correction.user_correction}
                          </span>
                        </TableCell>
                        <TableCell className="max-w-[200px] truncate text-sm text-muted-foreground">
                          {correction.context || '-'}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <div className="text-center py-8">
                  <XCircle className="mx-auto h-12 w-12 text-muted-foreground/50" />
                  <h3 className="mt-4 text-lg font-medium">No corrections yet</h3>
                  <p className="mt-2 text-sm text-muted-foreground">
                    User corrections help improve AI accuracy over time
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="activity">
          <Card>
            <CardHeader>
              <CardTitle>Recent Activity</CardTitle>
              <CardDescription>
                Document processing activity over the past period
              </CardDescription>
            </CardHeader>
            <CardContent>
              {dashboard?.recent_activity && dashboard.recent_activity.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Date</TableHead>
                      <TableHead className="text-right">Documents</TableHead>
                      <TableHead className="text-right">Replacements</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {dashboard.recent_activity.map((activity, index) => (
                      <TableRow key={index}>
                        <TableCell>{activity.date}</TableCell>
                        <TableCell className="text-right">
                          {activity.documents_processed}
                        </TableCell>
                        <TableCell className="text-right">
                          {activity.replacements}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <div className="text-center py-8">
                  <Clock className="mx-auto h-12 w-12 text-muted-foreground/50" />
                  <h3 className="mt-4 text-lg font-medium">No recent activity</h3>
                  <p className="mt-2 text-sm text-muted-foreground">
                    Process some documents to see activity data
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
