import { ChangeDetectorRef, Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { ApiService } from '../../Core/Services/ApiService'; 

@Component({
  selector: 'app-upload-window',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './upload-window.html',
  styleUrls: ['./upload-window.css']
})
export class UploadWindowComponent {
  selectedFile: File | null = null;
  errorMessage: string = '';
  isProcessing: boolean = false;
  pipelineStats: any = null;
  hasPipelineStats: boolean = false;

  constructor(
    private api: ApiService,
    private router: Router,
    private changeDetector: ChangeDetectorRef
  ) {}

  onFileSelected(event: any) {
    const file = event.target.files[0];
    
    // Validate the uploaded file type
    if (file && (file.name.endsWith('.txt') || file.name.endsWith('.pdf'))) {
      this.selectedFile = file;
      this.errorMessage = '';
    } else {
      // Reject unsupported formats with a descriptive error message
      this.errorMessage = 'Unsupported file type. Please upload a PDF or plain text (.txt) file.';
      this.selectedFile = null;
    }
  }

  processDocument() {
    const file = this.selectedFile;
    if (!file) return;
    this.isProcessing = true;
    this.pipelineStats = null;
    this.hasPipelineStats = false;
    
    this.api.createProject({
      project_name: file.name,
      description: 'Automatically created from an uploaded SRS document.',
    }).subscribe({
      next: (projectRes: any) => {
        this.api.uploadDocument(projectRes.project_id, file).subscribe({
          next: (docRes: any) => {
            // NLP chunking finishes during upload, so show its real metrics immediately.
            this.pipelineStats = docRes.nlp_pipeline;
            this.hasPipelineStats = !!this.pipelineStats;
            this.changeDetector.detectChanges();

            this.api.extractModel(docRes.document_id).subscribe({
              next: (extractRes: any) => {
                this.isProcessing = false;
                if (extractRes.nlp_pipeline?.sentence_count !== undefined) {
                  this.pipelineStats = extractRes.nlp_pipeline;
                  this.hasPipelineStats = true;
                }
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