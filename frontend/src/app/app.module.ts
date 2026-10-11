import { HTTP_INTERCEPTORS, HttpClientModule } from '@angular/common/http';
import { NgModule } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { BrowserModule } from '@angular/platform-browser';

import { AppRoutingModule } from './app-routing.module';
import { AppComponent } from './app.component';
import { UserHeaderInterceptor } from './core/user.service';
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
import { ActionListComponent } from './shared/action-list.component';
import { ChartComponent } from './shared/chart.component';
import { CitesComponent } from './shared/cites.component';
import { EmptyComponent } from './shared/empty.component';
import { FindingsListComponent } from './shared/findings-list.component';
import { TagComponent } from './shared/status-pill.component';

@NgModule({
  declarations: [
    AppComponent, DataComponent, OverviewComponent, PatternsComponent, CompareComponent, InsightsComponent, CopilotComponent,
    AgentsComponent, WorkflowComponent, InspectionComponent, MachinesComponent, BottlenecksComponent, ActionsComponent,
    IntegrationsComponent, ChartComponent, CitesComponent, TagComponent, EmptyComponent, FindingsListComponent, ActionListComponent,
  ],
  imports: [BrowserModule, HttpClientModule, FormsModule, AppRoutingModule],
  providers: [{ provide: HTTP_INTERCEPTORS, useClass: UserHeaderInterceptor, multi: true }],
  bootstrap: [AppComponent],
})
export class AppModule {}
