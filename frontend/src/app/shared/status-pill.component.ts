import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-tag',
  template: '<span class="tag" [ngClass]="kind">{{ label || kind }}</span>',
})
export class TagComponent {
  @Input() kind = '';
  @Input() label = '';
}
