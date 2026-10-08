import { Component, HostListener } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterOutlet } from '@angular/router';
import { ApiService } from '../Core/Services/ApiService';
import { filter } from 'rxjs';

@Component({
  selector: 'app-root',
  imports: [RouterLink, RouterOutlet],
  templateUrl: './app.html',
  styleUrl: './app.css'
})
export class App {
  currentStage: 'upload' | 'requirements' | 'diagrams' = 'upload';
  modelId = '';
  diagramsReady = false;
  showBackButton = false;

  constructor(private router: Router, private api: ApiService) {
    this.updateNavigation(this.router.url);
    this.router.events.pipe(filter(event => event instanceof NavigationEnd)).subscribe(event => {
      this.updateNavigation((event as NavigationEnd).urlAfterRedirects);
    });
  }

  goBack(): void {
    if (this.router.url.startsWith('/artifacts/')) {
      this.router.navigate(['/hitl-dashboard', this.modelId]);
    } else if (this.router.url.startsWith('/hitl-dashboard/')) {
      this.router.navigate(['/upload'], { queryParams: this.modelId ? { modelId: this.modelId } : {} });
    }
  }

  @HostListener('window:model-diagram-state', ['$event'])
  onModelDiagramState(event: Event): void {
    const detail = (event as CustomEvent<{ modelId: number; generated: boolean }>).detail;
    if (String(detail.modelId) === this.modelId) {
      this.diagramsReady = detail.generated;
    }
  }

  private updateNavigation(url: string): void {
    const [path, query = ''] = url.split('?');
    const segments = path.split('/').filter(Boolean);
    this.modelId = path.startsWith('/upload')
      ? new URLSearchParams(query).get('modelId') || ''
      : segments[segments.length - 1] || '';
    this.currentStage = path.startsWith('/artifacts/')
      ? 'diagrams'
      : path.startsWith('/hitl-dashboard/')
        ? 'requirements'
        : 'upload';
    this.showBackButton = this.currentStage !== 'upload';
    this.diagramsReady = false;

    if (this.modelId) {
      const requestedModelId = this.modelId;
      this.api.getUmlModel(Number(requestedModelId)).subscribe({
        next: model => {
          if (requestedModelId === this.modelId) {
            this.diagramsReady = model.status === 'diagram_generated';
            if (this.currentStage === 'diagrams' && !this.diagramsReady) {
              this.router.navigate(['/hitl-dashboard', this.modelId]);
            }
          }
        },
        error: error => {
          if (requestedModelId === this.modelId) {
            this.diagramsReady = false;
            if (this.currentStage === 'diagrams') {
              this.router.navigate(['/upload']);
            }
            console.error('Could not load model navigation state:', error);
          }
        }
      });
    }
  }
}
