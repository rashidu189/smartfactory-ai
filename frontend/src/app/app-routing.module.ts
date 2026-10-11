import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { ActionsComponent } from './pages/actions.component';
import { AgentsComponent } from './pages/agents.component';
import { BottlenecksComponent } from './pages/bottlenecks.component';
import { CompareComponent } from './pages/compare.component';
import { CopilotComponent } from './pages/copilot.component';
import { DataComponent } from './pages/data.component';
import { InsightsComponent } from './pages/insights.component';
import { InspectionComponent } from './pages/inspection.component';
import { IntegrationsComponent } from './pages/integrations.component';
import { MachinesComponent } from './pages/machines.component';
import { OverviewComponent } from './pages/overview.component';
import { PatternsComponent } from './pages/patterns.component';
import { WorkflowComponent } from './pages/workflow.component';

const t = (x: string) => `${x} · SmartFactory AI`;
const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'overview' },
  { path: 'data', component: DataComponent, title: t('Data') },
  { path: 'overview', component: OverviewComponent, title: t('Overview') },
  { path: 'patterns', component: PatternsComponent, title: t('Patterns') },
  { path: 'compare', component: CompareComponent, title: t('Compare periods') },
  { path: 'insights', component: InsightsComponent, title: t('AI insights') },
  { path: 'copilot', component: CopilotComponent, title: t('Copilot') },
  { path: 'agents', component: AgentsComponent, title: t('Agents') },
  { path: 'agents/:id', component: WorkflowComponent, title: t('Agent workflow') },
  { path: 'inspection', component: InspectionComponent, title: t('Visual inspection') },
  { path: 'machines', component: MachinesComponent, title: t('Machine health') },
  { path: 'bottlenecks', component: BottlenecksComponent, title: t('Bottlenecks') },
  { path: 'actions', component: ActionsComponent, title: t('Actions & approvals') },
  { path: 'integrations', component: IntegrationsComponent, title: t('Integrations') },
  { path: '**', redirectTo: 'overview' },
];

@NgModule({
  imports: [RouterModule.forRoot(routes, { scrollPositionRestoration: 'top' })],
  exports: [RouterModule],
})
export class AppRoutingModule {}
