import { Pipe, PipeTransform } from '@angular/core';

@Pipe({ name: 'workflowStatus', standalone: true })
export class WorkflowStatusPipe implements PipeTransform {
  transform(status: string | undefined | null, type: 'icon' | 'class'): string {
    let s = status?.toUpperCase();
    if (s?.startsWith('STATE_')) {
      s = s.replace('STATE_', '');
    }
    const config: any = {
      RUNNING: { icon: 'hourglass_top', class: '!bg-blue-500/20 !text-blue-300' },
      ACTIVE: { icon: 'hourglass_top', class: '!bg-blue-500/20 !text-blue-300' }, // Map ACTIVE to RUNNING style
      COMPLETED: { icon: 'check_circle', class: '!bg-green-500/20 !text-green-300' },
      SUCCEEDED: { icon: 'check_circle', class: '!bg-green-500/20 !text-green-300' },
      FAILED: { icon: 'error', class: '!bg-red-500/20 !text-red-300' },
      PENDING: { icon: 'schedule', class: '!bg-gray-500/20 !text-gray-300' },
      SKIPPED: { icon: 'skip_next', class: '!bg-amber-500/20 !text-amber-300' },
      CANCELLED: { icon: 'cancel', class: '!bg-red-500/20 !text-red-300' }
    };

    const def = config[s || ''] || { icon: 'help_outline', class: '!bg-gray-500/20 !text-gray-300' };
    return type === 'icon' ? def.icon : def.class;
  }
}
