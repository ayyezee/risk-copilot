import * as React from 'react';
import { Button, type ButtonProps } from './button';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from './tooltip';
import { cn } from '@/lib/utils';
import { Loader2 } from 'lucide-react';

interface ActionButtonProps extends Omit<ButtonProps, 'size'> {
  tooltip: string;
  icon: React.ReactNode;
  loading?: boolean;
  destructive?: boolean;
  primary?: boolean;
}

export function ActionButton({
  tooltip,
  icon,
  loading,
  destructive,
  primary,
  className,
  disabled,
  ...props
}: ActionButtonProps) {
  return (
    <TooltipProvider delayDuration={300}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant={primary ? 'default' : 'ghost'}
            size="icon"
            className={cn(
              'h-8 w-8 rounded-lg transition-all duration-200',
              !primary && [
                'text-muted-foreground',
                'hover:text-foreground hover:bg-accent/80',
                'active:scale-95',
              ],
              primary && [
                'bg-primary/90 hover:bg-primary',
                'shadow-sm hover:shadow-md',
                'active:scale-95',
              ],
              destructive && [
                'text-muted-foreground',
                'hover:text-destructive hover:bg-destructive/10',
              ],
              disabled && 'opacity-50 cursor-not-allowed',
              className
            )}
            disabled={disabled || loading}
            {...props}
          >
            {loading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <span className="flex items-center justify-center">{icon}</span>
            )}
          </Button>
        </TooltipTrigger>
        <TooltipContent
          side="bottom"
          className="bg-foreground text-background text-xs font-medium px-2 py-1 rounded-md"
        >
          {tooltip}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

// Action button group for consistent spacing
export function ActionButtonGroup({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('flex items-center gap-1', className)}>{children}</div>
  );
}
