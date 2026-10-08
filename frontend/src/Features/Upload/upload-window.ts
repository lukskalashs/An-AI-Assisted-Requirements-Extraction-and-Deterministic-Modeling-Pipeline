import { ChangeDetectorRef, Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { ApiService } from '../../Core/Services/ApiService'; 
import { concatMap, from, toArray } from 'rxjs';

@Component({
  selector: 'app-upload-window',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './upload-window.html',
  styleUrls: ['./upload-window.css']
})
export class UploadWindowComponent {
  selectedFiles: File[] = [];
  errorMessage: string = '';
  isProcessing: boolean = false;
  pipelineStats: any = null;
  hasPipelineStats: boolean = false;

  constructor(
    private api: ApiService,
    private router: Router,
    private changeDetector: ChangeDetectorRef
  ) {}

  onFileSelected(event: Event) {
    const input = event.target as HTMLInputElement;
    const files = Array.from(input.files || []);
    if (files.length && files.every(file => /\.(txt|pdf)$/i.test(file.name))) {
      this.selectedFiles = files;
      this.errorMessage = '';
    } else {
      this.errorMessage = 'Unsupported file type. Please upload PDF or plain text (.txt) files.';
      this.selectedFiles = [];
    }
  }

  processDocument() {
    if (!this.selectedFiles.length) return;
    this.isProcessing = true;
    this.pipelineStats = null;
    this.hasPipelineStats = false;
    
    this.api.createProject({
      project_name: this.selectedFiles.length === 1
        ? this.selectedFiles[0].name
        : `Specifications (${this.selectedFiles.length} documents)`,
      description: 'Automatically created from uploaded specification documents.',
    }).subscribe({
      next: (projectRes: any) => {
        from(this.selectedFiles).pipe(
          concatMap(file => this.api.uploadDocument(projectRes.project_id, file)),
          toArray()
        ).subscribe({
          next: (documents: any[]) => {
            const stats = documents.map(document => document.nlp_pipeline).filter(Boolean);
            if (stats.length) {
              this.pipelineStats = {
                sanitised: stats.every(stat => stat.sanitised),
                sentence_count: stats.reduce((total, stat) => total + stat.sentence_count, 0),
                chunk_count: stats.reduce((total, stat) => total + stat.chunk_count, 0),
                overlap_words: stats[0].overlap_words
              };
              this.hasPipelineStats = true;
              this.changeDetector.detectChanges();
            }
            this.api.extractProject(projectRes.project_id).subscribe({
              next: (extractRes: any) => {
                this.isProcessing = false;
                this.pipelineStats = extractRes.nlp_pipeline;
                this.hasPipelineStats = !!this.pipelineStats;
                this.changeDetector.detectChanges();
                this.router.navigate(['/hitl-dashboard', extractRes.model_id]);
              },
              error: (err: any) => this.handleError(err)
            });
          },
          error: (err: any) => this.handleError(err)
        });
      },
      error: (err: any) => this.handleError(err)
    });
  }

  handleError(error: any) {
    this.isProcessing = false;
    this.errorMessage = error.error?.detail || 'An error occurred during communication with the AI pipeline. Please try again.';
    console.error(error);
  }
}