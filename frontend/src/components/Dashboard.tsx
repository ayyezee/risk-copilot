import { useQuery } from '@tanstack/react-query';
import { analyticsApi } from '../services/api';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from './ui/card';
// import { Progress } from './ui/progress';
import {
  FileText,
  TrendingUp,
  Clock,
  CheckCircle2,
  Loader2,
} from 'lucide-react';

interface DashboardData {
  total_documents_processed: number;
  total_replacements: number;
  average_processing_time_ms: number;
  success_rate: number;
  recent_activity: Array<{
    date: string;
    documents_processed: number;
    replacements: number;
  }>;
}

export function Dashboard() {
  const { data: dashboard, isLoading } = useQuery({
    queryKey: ['dashboard'],
    queryFn: async () => {
      const response = await analyticsApi.getDashboard();
      return response.data as DashboardData;
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const stats = [
    {
      title: 'Documents Processed',
      value: dashboard?.total_documents_processed || 0,
      icon: FileText,
      description: 'Total documents',
    },
    {
      title: 'Total Replacements',
      value: dashboard?.total_replacements || 0,
      icon: TrendingUp,
      description: 'Terms corrected',
    },
    {
      title: 'Avg. Processing Time',
      value: dashboard?.average_processing_time_ms
        ? `${(dashboard.average_processing_time_ms / 1000).toFixed(1)}s`
        : '0s',
      icon: Clock,
      description: 'Per document',
    },
    {
      title: 'Success Rate',
      value: dashboard?.success_rate
        ? `${(dashboard.success_rate * 100).toFixed(1)}%`
        : '100%',
      icon: CheckCircle2,
      description: 'Processing success',
    },
  ];

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat) => (
          <Card key={stat.title}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">{stat.title}</CardTitle>
              <stat.icon className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stat.value}</div>
              <p className="text-xs text-muted-foreground">{stat.description}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {dashboard?.recent_activity && dashboard.recent_activity.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Recent Activity</CardTitle>
            <CardDescription>
              Document processing over the past period
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {dashboard.recent_activity.slice(0, 5).map((activity, index) => (
                <div key={index} className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium">{activity.date}</p>
                    <p className="text-xs text-muted-foreground">
                      {activity.documents_processed} document
                      {activity.documents_processed !== 1 ? 's' : ''}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-medium">
                      {activity.replacements} replacements
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
