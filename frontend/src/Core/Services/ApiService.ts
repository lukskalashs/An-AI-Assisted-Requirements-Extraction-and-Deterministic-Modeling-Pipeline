import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, catchError, of, shareReplay, tap, throwError } from 'rxjs';
import { environment } from '../../environments/environment';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private apiUrl = environment.apiUrl;
  private modelCache = new Map<number, any>();
  private modelRequests = new Map<number, Observable<any>>();

  constructor(private http: HttpClient) { }

  createProject(projectData: { project_name: string; description?: string }): Observable<any> {
    return this.http.post(`${this.apiUrl}/projects/`, projectData);
  }

  uploadDocument(projectId: number, file: File): Observable<any> {
    const formData = new FormData();
    formData.append('file', file);
    return this.http.post(`${this.apiUrl}/projects/${projectId}/documents/`, formData);
  }

  extractModel(documentId: number): Observable<any> {
    return this.http.post(`${this.apiUrl}/documents/${documentId}/extract`, {});
  }

  extractProject(projectId: number): Observable<any> {
    return this.http.post(`${this.apiUrl}/projects/${projectId}/extract`, {});
  }

  getUmlModel(modelId: number): Observable<any> {
    const cachedModel = this.modelCache.get(modelId);
    if (cachedModel) {
      return of(cachedModel);
    }

    const pendingRequest = this.modelRequests.get(modelId);
    if (pendingRequest) {
      return pendingRequest;
    }

    const request = this.http.get(`${this.apiUrl}/Models/${modelId}`).pipe(
      tap(model => {
        this.modelCache.set(modelId, model);
        this.modelRequests.delete(modelId);
      }),
      catchError(error => {
        this.modelRequests.delete(modelId);
        return throwError(() => error);
      }),
      shareReplay({ bufferSize: 1, refCount: false })
    );
    this.modelRequests.set(modelId, request);
    return request;
  }

  getModelSourceDocuments(modelId: number): Observable<any[]> {
    return this.http.get<any[]>(`${this.apiUrl}/models/${modelId}/source-documents`);
  }

  // Generates the UML class diagram syntax.
  generateDiagram(modelId: number): Observable<any> {
    return this.http.post(`${this.apiUrl}/models/${modelId}/generate`, {}).pipe(
      tap(() => {
        const model = this.modelCache.get(modelId);
        if (model) {
          this.modelCache.set(modelId, { ...model, status: 'diagram_generated' });
        }
      })
    );
  }

  getGeneratedDiagram(modelId: number): Observable<any> {
    return this.http.get(`${this.apiUrl}/models/${modelId}/generated-diagram`);
  }
  
  // Generates the normalized ERD syntax for the artifact viewer.
  getErdVisual(modelId: number): Observable<any> {
     return this.http.get(`${this.apiUrl}/models/${modelId}/erd-visual`);
  }

  // Export c# Code
  exportCSharpCode(modelId: number): Observable<any>{
    return this.http.get(`${this.apiUrl}/models/${modelId}/code/csharp`)
  }

  downloadCSharpClasses(modelId: number): Observable<Blob> {
    return this.http.get(`${this.apiUrl}/models/${modelId}/code/csharp/download`, { responseType: 'blob' });
  }

  downloadDiagram(modelId: number, diagramType: 'uml' | 'erd', format: 'svg' | 'drawio'): Observable<Blob> {
    return this.http.get(
      `${this.apiUrl}/models/${modelId}/diagram/${diagramType}/${format}`,
      { responseType: 'blob' }
    );
  }

  // Export OpenAPI YAML {expectss raw text response}

  exportOpenApi(modelId: number): Observable<any>{
    return this.http.get(`${this.apiUrl}/models/${modelId}/openapi`, {responseType: 'text'});
  }

  // Update a specific UML Class
  updateClass(classId: number, classData: any): Observable<any> {
    return this.invalidateModelsAfter(this.http.put(`${this.apiUrl}/classes/${classId}`, classData));
  }

  createClass(modelId: number, classData: any): Observable<any> {
    return this.invalidateModelsAfter(this.http.post(`${this.apiUrl}/models/${modelId}/classes`, classData));
  }

  //Update a specific UML Relationship
  updateRelationship(relId: number, relData: any): Observable<any>{
    return this.invalidateModelsAfter(this.http.put(`${this.apiUrl}/relationships/${relId}`, relData));
  }

  createRelationship(modelId: number, relationshipData: any): Observable<any> {
    return this.invalidateModelsAfter(this.http.post(`${this.apiUrl}/models/${modelId}/relationships`, relationshipData));
  }

  createAttribute(classId: number, attributeData: any): Observable<any> {
    return this.invalidateModelsAfter(this.http.post(`${this.apiUrl}/classes/${classId}/attributes`, attributeData));
  }

  updateAttribute(attributeId: number, attributeData: any): Observable<any> {
    return this.invalidateModelsAfter(this.http.put(`${this.apiUrl}/attributes/${attributeId}`, attributeData));
  }

  createMethod(classId: number, methodData: any): Observable<any> {
    return this.invalidateModelsAfter(this.http.post(`${this.apiUrl}/classes/${classId}/methods`, methodData));
  }

  updateMethod(methodId: number, methodData: any): Observable<any> {
    return this.invalidateModelsAfter(this.http.put(`${this.apiUrl}/methods/${methodId}`, methodData));
  }

  deleteClass(classId: number): Observable<any> {
    return this.invalidateModelsAfter(this.http.delete(`${this.apiUrl}/classes/${classId}`));
  }

  deleteAttribute(attributeId: number): Observable<any> {
    return this.invalidateModelsAfter(this.http.delete(`${this.apiUrl}/attributes/${attributeId}`));
  }

  deleteMethod(methodId: number): Observable<any> {
    return this.invalidateModelsAfter(this.http.delete(`${this.apiUrl}/methods/${methodId}`));
  }

  deleteRelationship(relId: number): Observable<any> {
    return this.invalidateModelsAfter(this.http.delete(`${this.apiUrl}/relationships/${relId}`));
  }

  private invalidateModelsAfter<T>(request: Observable<T>): Observable<T> {
    return request.pipe(tap(() => {
      this.modelCache.clear();
      this.modelRequests.clear();
    }));
  }
}