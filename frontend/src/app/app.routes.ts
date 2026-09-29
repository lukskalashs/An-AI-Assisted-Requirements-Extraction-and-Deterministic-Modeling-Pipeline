import { Routes } from '@angular/router';
import { UploadWindowComponent } from '../Features/Upload/upload-window';
import { HitlDashboardComponent } from '../Features/hitl_dashboard/hitl-dashboard';
import { ArtifactViewerComponent } from '../Features/Artifact_viewer/artifact_viewer';


export const routes: Routes = [
    { path: '', redirectTo: 'upload', pathMatch: 'full' },
  { path: 'upload', component: UploadWindowComponent },
  { path: 'hitl-dashboard/:modelId', component: HitlDashboardComponent },
  { path: 'artifacts/:modelId', component: ArtifactViewerComponent }
];
