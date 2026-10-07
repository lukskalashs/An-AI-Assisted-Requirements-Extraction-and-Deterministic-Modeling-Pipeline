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
      uml: this.apiService.generateDiagram(this.modelId),
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
      this.progressValue +- Math.floor(Math.random() * 15) + 5;

      if(this.progressValue > 90)
        this.progressValue = 90; //Cap at 90 until the backend return
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
    window.URL.revokeObjectURL(url);
  }

  // Dowload C# Code as .cs files

  downloadCSharp(): void {
    this.apiService.exportCSharpCode(this.modelId).subscribe({
      next: (res) => {
        //Combine all generated C# classes into a single file for easy download

        let combinedCode = "";

        for (const className in res.classes) {
          combinedCode += res.classes[className] + "\n\n";
        }

        const fileBlob = new Blob([combinedCode], { type: 'text/plain' });
        this.triggerDownload(fileBlob, `DomainModels_Models${this.modelId}.cs`);
      },
      error: (err) => {
        console.error('C# export API error:', err);
        this.errorMessage = err.error?.detail || 'Could not generate the C# classes. Check the backend logs.';
      },
    });
  }


  // Download OpenAPI YAML as .yaml file

  downloadYaml(): void {
    this.apiService.exportOpenApi(this.modelId).subscribe(res => {
      const fileBlob = new Blob([res], {type: 'text/yaml'} );

      this.triggerDownload(fileBlob, `API_Contract_Models${this.modelId}.yaml`)
    })
  }

  // onDiagramError(diagramName: string): void {
  //   this.errorMessage = `The PlantUML renderer could not load the ${diagramName} diagram.`;
  // }
}