import { Component, EventEmitter, Input, Output } from '@angular/core';
import { FormControl } from '@angular/forms';
import { StepInput } from '../../step.model';

@Component({
  selector: 'app-step-input-field',
  templateUrl: './step-input-field.component.html',
  styleUrls: ['./step-input-field.component.scss']
})
export class StepInputFieldComponent {
  @Input() control!: FormControl;
  @Input() config!: StepInput;
  @Input() mode: 'fixed' | 'linked' | 'mixed' = 'fixed';
  @Input() compatibleOutputs: any[] = [];
  @Input() showValidationErrors = false;
  @Input() maxMediaItems = 1;

  @Output() modeChange = new EventEmitter<'fixed' | 'linked' | 'mixed'>();

  toggleInputMode(newMode: 'fixed' | 'linked' | 'mixed') {
    this.modeChange.emit(newMode);
  }

  compareFn(o1: any, o2: any): boolean {
    return o1 && o2 ? o1.step === o2.step && o1.output === o2.output : o1 === o2;
  }
}
