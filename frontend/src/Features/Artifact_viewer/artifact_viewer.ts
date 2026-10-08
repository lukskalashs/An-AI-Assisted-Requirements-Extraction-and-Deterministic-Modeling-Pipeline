import { ChangeDetectorRef, Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiService } from '../../Core/Services/ApiService';
import * as plantumlEncoder from 'plantuml-encoder';
import { forkJoin } from 'rxjs';

@Component({
  selector: 'app-artifact-viewer',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './artifact_viewer.html',
  
})
export class ArtifactViewerComponent implements OnInit, OnDestroy {
  modelId!: number;
  umlDiagramUrl: string = '';
  erdDiagramUrl: string = '';

  //Progress Bar State
  isLoading: boolean = true;
  progressStep: string = "Initialising Request"
  progressValue: number = 10;
  ProgressInterval: any;

  errorMessage: string = '';

  constructor(
    private route: ActivatedRoute,
    private apiService: ApiService,
    private changeDetector: ChangeDetectorRef,
    private router: Router
  ) {}

  ngOnInit(): void {
    const idParam = this.route.snapshot.paramMap.get('modelId');
    if (idParam) {
      this.modelId = +idParam;
      this.loadDiagram();
    } else {
      this.errorMessage = "No Model ID provided.";
      this.isLoading = false;
    }
  }
  ngOnDestroy(): void {
    if (this.ProgressInterval) {
      clearInterval(this.ProgressInterval);
    }
  }

  loadDiagram(): void {
    this.isLoading = true;
    this.errorMessage = '';
    this.umlDiagramUrl = '';
    this.erdDiagramUrl = '';

    this.startProgressSimulation();
    

    forkJoin({
      uml: this.apiService.getGeneratedDiagram(this.modelId),
      erd: this.apiService.getErdVisual(this.modelId)
    }).subscribe({
      next: ({ uml, erd }) => {
        clearInterval(this.ProgressInterval);
        this.progressStep = "Encoding Diagrams for Render...";
        this.progressValue = 95;

        try {
          this.umlDiagramUrl = this.toPlantUmlUrl(uml?.plantuml_syntax);
          this.erdDiagramUrl = this.toPlantUmlUrl(erd?.plantuml_erd_syntax);

          if (!this.umlDiagramUrl || !this.erdDiagramUrl) {
            this.errorMessage = 'The server returned incomplete diagram data.';
          }
        } catch (e) {
          console.error('Encoding error:', e);
          this.errorMessage = 'Failed to encode the diagrams for rendering.';
        }

        this.progressStep = "Render Complete !"
        this.progressValue = 100;

        setTimeout(() => {
          this.isLoading = false;
          this.changeDetector.detectChanges();
        }, 500);

        // this.isLoading = false;
        // this.changeDetector.detectChanges();
      },
      error: (err) => {
        clearInterval(this.ProgressInterval);
        console.error('Diagram API error:', err);
        this.errorMessage = 'Could not generate both diagrams. Check the backend logs.';
        this.isLoading = false;
        this.changeDetector.detectChanges();
      }
    });
  }

  // Cycling Through pipelines messages to give the user deep visibility
  private startProgressSimulation(): void{
    const steps = [
      "Validating Extracted Entities...",
      "Mapping Class Relationships...",
      "Generating Deterministic PlantUML syantax...",
      "Compiling Final Architecture..."
    ];

    let i = 0;
    this.ProgressInterval = setInterval(() => {
      this.progressStep = steps[i % steps.length]
      this.progressValue = Math.min(90, this.progressValue + Math.floor(Math.random() * 15) + 5);
      i++;
      this.changeDetector.detectChanges();
    }, 3000);
  }

  private toPlantUmlUrl(syntax: string | undefined): string {
    if (!syntax) {
      return '';
    }
  

    const encoder = (plantumlEncoder as any).default || plantumlEncoder;
    return `https://www.plantuml.com/plantuml/svg/${encoder.encode(syntax)}`;
  }

  promptEdit(): void {
    const wantsToEdit = window.confirm("Would you like to edit this diagram? Clicking 'OK' will take you back to the Human-in-the-Loop Editing dashboard.");
    if (wantsToEdit) {
      this.router.navigate(['/hitl-dashboard', this.modelId]);
    }
  }

  private triggerDownload(blob: Blob, filename: string): void {
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
  }

  downloadCSharp(): void {
    this.apiService.downloadCSharpClasses(this.modelId).subscribe({
      next: blob => this.triggerDownload(blob, `DomainModels_${this.modelId}.zip`),
      error: (err) => {
        console.error('C# export API error:', err);
        this.errorMessage = 'Could not generate the C# classes. Check the backend logs.';
      },
    });
  }

  downloadDiagram(kind: 'uml' | 'erd', format: 'svg' | 'png' | 'drawio'): void {
    document.querySelectorAll<HTMLDetailsElement>('.diagram-download details').forEach(menu => {
      menu.open = false;
    });
    if (format === 'drawio') {
      this.apiService.downloadDiagram(this.modelId, kind, 'drawio').subscribe({
        next: blob => this.triggerDownload(blob, `${kind.toUpperCase()}_Model_${this.modelId}.drawio`),
        error: err => {
          console.error(`${kind.toUpperCase()} draw.io export error:`, err);
          this.errorMessage = `Could not generate the editable ${kind.toUpperCase()} draw.io diagram.`;
        }
      });
      return;
    }

    this.apiService.downloadDiagram(this.modelId, kind, 'svg').subscribe({
      next: svg => {
        if (format === 'svg') {
          this.triggerDownload(svg, `${kind.toUpperCase()}_Model_${this.modelId}.svg`);
          return;
        }
        this.svgToPng(svg).then(
          png => this.triggerDownload(png, `${kind.toUpperCase()}_Model_${this.modelId}.png`),
          error => {
            console.error(`${kind.toUpperCase()} PNG conversion error:`, error);
            this.errorMessage = `Could not convert the ${kind.toUpperCase()} diagram to PNG.`;
          }
        );
      },
      error: err => {
        console.error(`${kind.toUpperCase()} SVG export error:`, err);
        this.errorMessage = `Could not generate the ${kind.toUpperCase()} diagram download.`;
      }
    });
  }

  private svgToPng(svg: Blob): Promise<Blob> {
    return new Promise((resolve, reject) => {
      const sourceUrl = window.URL.createObjectURL(svg);
      const image = new Image();
      image.onload = () => {
        const scale = 2;
        const canvas = document.createElement('canvas');
        canvas.width = image.naturalWidth * scale;
        canvas.height = image.naturalHeight * scale;
        const context = canvas.getContext('2d');
        if (!context) {
          window.URL.revokeObjectURL(sourceUrl);
          reject(new Error('Canvas is unavailable for PNG export.'));
          return;
        }
        context.fillStyle = '#ffffff';
        context.fillRect(0, 0, canvas.width, canvas.height);
        context.scale(scale, scale);
        context.drawImage(image, 0, 0);
        canvas.toBlob(blob => {
          window.URL.revokeObjectURL(sourceUrl);
          if (blob) {
            resolve(blob);
          } else {
            reject(new Error('The browser could not encode the diagram as PNG.'));
          }
        }, 'image/png');
      };
      image.onerror = () => {
        window.URL.revokeObjectURL(sourceUrl);
        reject(new Error('The generated SVG could not be loaded for PNG export.'));
      };
      image.src = sourceUrl;
    });
  }

  downloadYaml(): void {
    this.apiService.exportOpenApi(this.modelId).subscribe({
      next: res => this.triggerDownload(new Blob([res], { type: 'text/yaml' }), `API_Contract_Models${this.modelId}.yaml`),
      error: err => {
        console.error('OpenAPI export API error:', err);
        this.errorMessage = err.error?.detail || 'Could not generate the OpenAPI contract.';
      }
    });
  }

  // onDiagramError(diagramName: string): void {
  //   this.errorMessage = `The PlantUML renderer could not load the ${diagramName} diagram.`;
  // }
}