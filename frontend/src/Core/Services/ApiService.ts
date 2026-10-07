import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private apiUrl = environment.apiUrl;

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

  getUmlModel(modelId: number): Observable<any> {
    return this.http.get(`${this.apiUrl}/Models/${modelId}`);
  }

  // Generates the UML class diagram syntax.
  generateDiagram(modelId: number): Observable<any> {
    return this.http.post(`${this.apiUrl}/models/${modelId}/generate`, {});
  }
  
  // Generates the normalized ERD syntax for the artifact viewer.
  getErdVisual(modelId: number): Observable<any> {
     return this.http.get(`${this.apiUrl}/models/${modelId}/erd-visual`);
  }

  // Export c# Code
  exportCSharpCode(modelId: number): Observable<any>{
    return this.http.get(`${this.apiUrl}/models/${modelId}/code/csharp`)
  }

  // Export OpenAPI YAML {expectss raw text response}

  exportOpenApi(modelId: number): Observable<any>{
    return this.http.get(`${this.apiUrl}/models/${modelId}/openapi`, {responseType: 'text'});
  }

  // Update a specific UML Class
  updateClass(classId: number, classData: any): Observable<any> {
    return this.http.put(`${this.apiUrl}/classes/${classId}`, classData)
  }

  createClass(modelId: number, classData: any): Observable<any> {
    return this.http.post(`${this.apiUrl}/models/${modelId}/classes`, classData);
  }

  //Update a specific UML Relationship
  updateRelationship(relId: number, relData: any): Observable<any>{
    return this.http.put(`${this.apiUrl}/relationships/${relId}`, relData)
  }

  createRelationship(modelId: number, relationshipData: any): Observable<any> {
    return this.http.post(`${this.apiUrl}/models/${modelId}/relationships`, relationshipData);
  }

  createAttribute(classId: number, attributeData: any): Observable<any> {
    return this.http.post(`${this.apiUrl}/classes/${classId}/attributes`, attributeData);
  }

  updateAttribute(attributeId: number, attributeData: any): Observable<any> {
    return this.http.put(`${this.apiUrl}/attributes/${attributeId}`, attributeData);
  }

  createMethod(classId: number, methodData: any): Observable<any> {
    return this.http.post(`${this.apiUrl}/classes/${classId}/methods`, methodData);
  }

  updateMethod(methodId: number, methodData: any): Observable<any> {
    return this.http.put(`${this.apiUrl}/methods/${methodId}`, methodData);
  }

  deleteClass(classId: number): Observable<any> {
    return this.http.delete(`${this.apiUrl}/classes/${classId}`);
  }

  deleteAttribute(attributeId: number): Observable<any> {
    return this.http.delete(`${this.apiUrl}/attributes/${attributeId}`);
  }

  deleteMethod(methodId: number): Observable<any> {
    return this.http.delete(`${this.apiUrl}/methods/${methodId}`);
  }

  deleteRelationship(relId: number): Observable<any> {
    return this.http.delete(`${this.apiUrl}/relationships/${relId}`);
  }

}