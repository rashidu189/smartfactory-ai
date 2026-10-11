import { AfterViewInit, Component, ElementRef, Input, NgZone, OnChanges, OnDestroy, ViewChild } from '@angular/core';
import { Chart, ChartConfiguration, registerables } from 'chart.js';

Chart.register(...registerables);
Chart.defaults.font.family = 'IBM Plex Sans, system-ui, sans-serif';
Chart.defaults.color = '#5d6670';

/** Thin wrapper around Chart.js: re-renders whenever `config` changes. */
@Component({
  selector: 'app-chart',
  template: '<div class="canvas-wrap" [style.height.px]="height"><canvas #canvas></canvas></div>',
})
export class ChartComponent implements AfterViewInit, OnChanges, OnDestroy {
  @Input() config!: ChartConfiguration;
  @Input() height = 260;
  @ViewChild('canvas') canvas!: ElementRef<HTMLCanvasElement>;
  private chart?: Chart;

  constructor(private zone: NgZone) {}

  ngAfterViewInit(): void { this.render(); }
  ngOnChanges(): void { if (this.canvas) this.render(); }
  ngOnDestroy(): void { this.zone.runOutsideAngular(() => this.chart?.destroy()); }

  private render(): void {
    // Outside Angular's zone: Chart.js resize/mouse events must not trigger change detection
    // (that can create a resize ↔ re-render feedback loop).
    this.zone.runOutsideAngular(() => {
      this.chart?.destroy();
      if (this.config) this.chart = new Chart(this.canvas.nativeElement, this.config);
    });
  }
}
