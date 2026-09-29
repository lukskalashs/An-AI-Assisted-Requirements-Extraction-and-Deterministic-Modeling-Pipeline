import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { ApiService } from '../../Core/Services/ApiService'; 
import { finalize } from 'rxjs';
import { FormsModule } from '@angular/forms';

@Component({
  selector: 'app-hitl-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './hitl-dashboard.html',
  styleUrl: './hitl-dashboard.css'
})
export class HitlDashboardComponent implements OnInit {
  modelId!: number;
  umlModel: any = null;
  isLoading: boolean = true;
  errorMessage: string = '';

  //Editing State
  selectedClass: any = null;
  isNewClass: boolean = false;
  selectedRelationship: any = null;
  isNewRelationship: boolean = false;
  selectedMember: any = null;
  selectedMemberClass: any = null;
  selectedMemberType: 'attribute' | 'method' = 'attribute';
  isNewMember: boolean = false;
  evidenceItem: any = null;
  evidenceClass: any = null;
  evidenceType: 'class' | 'attribute' | 'method' | 'relationship' = 'class';
  isSaving: boolean = false;

  constructor(
    private route: ActivatedRoute,
    private api: ApiService,
    private router: Router,
    private changeDetector: ChangeDetectorRef
  ) {}

  ngOnInit(): void {
    const idParam = this.route.snapshot.paramMap.get('modelId');
    if (!idParam || Number.isNaN(Number(idParam))) {
      this.errorMessage = 'No valid model ID was provided.';
      this.isLoading = false;
      return;
    }

    this.modelId = Number(idParam);
    this.fetchModelData();
  }

  fetchModelData() {
    this.isLoading = true;
    this.errorMessage = '';

    this.api.getUmlModel(this.modelId).pipe(
      finalize(() => {
        this.isLoading = false;
        this.changeDetector.detectChanges();
      })
    ).subscribe({
      next: (data) => {
        this.umlModel = {
          ...data,
          classes: (data.classes || []).map((umlClass: any) => ({
            ...umlClass,
            attributes: umlClass.attributes || [],
            methods: umlClass.methods || []
          })),
          relationships: this.dedupeRelationships((data.relationships || []).map((relationship: any) => ({
            ...relationship,
            relationship_type: ['Association', 'Aggregation', 'Composition', 'Inheritance']
              .includes(relationship.relationship_type)
              ? relationship.relationship_type
              : 'Association',
            relationship_label: relationship.relationship_label
              || (['Association', 'Aggregation', 'Composition', 'Inheritance'].includes(relationship.relationship_type)
                ? null
                : relationship.relationship_type),
            multiplicity_source: relationship.multiplicity_source === '*'
              ? '0..*'
              : (relationship.multiplicity_source || '0..*'),
            multiplicity_target: relationship.multiplicity_target === '*'
              ? '0..*'
              : (relationship.multiplicity_target || '0..*')
          })))
        };
      },
      error: (err) => {
        this.errorMessage = `Failed to load extracted entities (${err.status || 'network error'}).`;
        console.error(err);
      }
    });
  }

  confirmAndGenerate() {
    this.isLoading = true;
    
    // FIX: Trigger the deterministic UML generation (UC-11)
    this.api.generateDiagram(this.modelId).subscribe({
      next: () => {
        this.isLoading = false;
        // Navigate to the final rendered diagram
        this.router.navigate(['/artifacts', this.modelId]);
      },
      error: (err) => {
        this.errorMessage = 'Failed to generate architecture.';
        this.isLoading = false;
        console.error(err);
      }
    });
  }

  //Class Editing logic
  openClassModal(cls: any){
    this.isNewClass = false;
    //Create a deep copy so we dont modify the tables directly until 'Save' is clicked

    this.selectedClass = JSON.parse(JSON.stringify(cls));
    const modal = document.getElementById('edit_class_modal') as HTMLDialogElement;
    modal?.showModal();
  }

  openNewClassModal() {
    this.isNewClass = true;
    this.selectedClass = {
      class_name: '',
      entity_kind: 'persistent_entity',
      is_abstract: false,
      is_validated: false,
      source_evidence: '',
      attributes: [],
      methods: []
    };
    const modal = document.getElementById('edit_class_modal') as HTMLDialogElement;
    modal?.showModal();
  }

  saveClassChanges(){
    if (!this.selectedClass) return;
    if (!this.selectedClass.class_name?.trim()) {
      this.errorMessage = 'Class name is required.';
      return;
    }

    const previousClassName = this.selectedClass.class_name;
    this.isSaving = true;

    const request = this.isNewClass
      ? this.api.createClass(this.modelId, this.selectedClass)
      : this.api.updateClass(this.selectedClass.class_id, this.selectedClass);

    request.subscribe({
      next: (savedClass) => {
        if (this.isNewClass) {
          this.umlModel.classes.push({
            ...savedClass,
            attributes: [],
            methods: []
          });
          this.isSaving = false;
          this.errorMessage = '';
          this.changeDetector.detectChanges();
          this.closeModal('edit_class_modal');
          return;
        }

        const index = this.umlModel.classes.findIndex((c: any) => c.class_id === this.selectedClass.class_id);

        if(index !== -1){
          const updatedClass = {
            ...this.umlModel.classes[index],
            ...this.selectedClass
          };

          this.umlModel.classes[index] = updatedClass;

          this.umlModel.relationships = this.umlModel.relationships.map((relationship: any) => ({
            ...relationship,
            source_class: relationship.source_class?.class_name === previousClassName
              ? { ...relationship.source_class, class_name: this.selectedClass.class_name }
              : relationship.source_class,
            target_class: relationship.target_class?.class_name === previousClassName
              ? { ...relationship.target_class, class_name: this.selectedClass.class_name }
              : relationship.target_class
          }));
        }

        this.isSaving = false;
        this.errorMessage = '';
        this.changeDetector.detectChanges();
        const modal = document.getElementById(`edit_class_modal`) as HTMLDialogElement;
        modal?.close();
      },
      error: (err) => {
        console.error("Failed to save class:", err);
        this.errorMessage = "Failed to save class updates to the database.";
        this.isSaving = false;
      }
    })
  }

  openRelationshipModal(rel: any){
    this.isNewRelationship = false;
    this.selectedRelationship = JSON.parse(JSON.stringify(rel));

    const modal = document.getElementById("edit_rel_modal") as HTMLDialogElement;
    modal?.showModal();
  }

  openNewRelationshipModal() {
    this.isNewRelationship = true;
    this.selectedRelationship = {
      source_class_id: null,
      target_class_id: null,
      relationship_type: 'Association',
      relationship_label: '',
      multiplicity_source: '1',
      multiplicity_target: '*'
    };

    const modal = document.getElementById('edit_rel_modal') as HTMLDialogElement;
    modal?.showModal();
  }

  openEvidence(item: any, type: 'class' | 'attribute' | 'method' | 'relationship', cls?: any) {
    this.evidenceItem = item;
    this.evidenceType = type;
    this.evidenceClass = cls || null;
    const modal = document.getElementById('evidence_modal') as HTMLDialogElement;
    modal?.showModal();
  }

  editEvidenceItem() {
    const item = this.evidenceItem;
    const type = this.evidenceType;
    this.closeModal('evidence_modal');
    if (type === 'class') this.openClassModal(item);
    if (type === 'attribute' || type === 'method') this.openMemberModal(this.evidenceClass, type, item);
    if (type === 'relationship') this.openRelationshipModal(item);
  }

  deleteClass(cls: any) {
    if (!window.confirm(`Delete class "${cls.class_name}" and its members?`)) return;
    this.isSaving = true;
    this.api.deleteClass(cls.class_id).subscribe({
      next: () => {
        this.umlModel.classes = this.umlModel.classes.filter((item: any) => item.class_id !== cls.class_id);
        this.umlModel.relationships = this.umlModel.relationships.filter((rel: any) =>
          rel.source_class?.class_id !== cls.class_id && rel.target_class?.class_id !== cls.class_id);
        this.isSaving = false;
        this.changeDetector.detectChanges();
      },
      error: () => {
        this.errorMessage = 'Failed to delete class.';
        this.isSaving = false;
      }
    });
  }

  deleteMember(cls: any, member: any, type: 'attribute' | 'method') {
    const name = type === 'attribute' ? member.attribute_name : member.method_name;
    if (!window.confirm(`Delete ${type} "${name}"?`)) return;
    this.isSaving = true;
    const request = type === 'attribute'
      ? this.api.deleteAttribute(member.attribute_id)
      : this.api.deleteMethod(member.method_id);
    request.subscribe({
      next: () => {
        const key = type === 'attribute' ? 'attributes' : 'methods';
        const idKey = type === 'attribute' ? 'attribute_id' : 'method_id';
        cls[key] = cls[key].filter((item: any) => item[idKey] !== member[idKey]);
        this.isSaving = false;
        this.changeDetector.detectChanges();
      },
      error: () => {
        this.errorMessage = `Failed to delete ${type}.`;
        this.isSaving = false;
      }
    });
  }

  deleteRelationship(rel: any) {
    if (!window.confirm('Delete this relationship?')) return;
    this.isSaving = true;
    this.api.deleteRelationship(rel.relationship_id).subscribe({
      next: () => {
        this.umlModel.relationships = this.umlModel.relationships.filter((item: any) =>
          item.relationship_id !== rel.relationship_id);
        this.isSaving = false;
        this.changeDetector.detectChanges();
      },
      error: () => {
        this.errorMessage = 'Failed to delete relationship.';
        this.isSaving = false;
      }
    });
  }

  saveRelationshipChanges(){
    if(!this.selectedRelationship) return;

    if (this.isNewRelationship && (
      !this.selectedRelationship.source_class_id ||
      !this.selectedRelationship.target_class_id
    )) {
      this.errorMessage = 'A relationship must have both a source and a target class.';
      return;
    }
    
    this.isSaving = true;

    const request = this.isNewRelationship
      ? this.api.createRelationship(this.modelId, this.selectedRelationship)
      : this.api.updateRelationship(this.selectedRelationship.relationship_id, this.selectedRelationship);

    request.subscribe({
      next: (savedRelationship) => {
        if (this.isNewRelationship) {
          const sourceClass = this.umlModel.classes.find((cls: any) =>
            cls.class_id === savedRelationship.source_class_id);
          const targetClass = this.umlModel.classes.find((cls: any) =>
            cls.class_id === savedRelationship.target_class_id);
          this.umlModel.relationships.push({
            ...savedRelationship,
            source_class: sourceClass,
            target_class: targetClass
          });
        }

        const index = this.umlModel.relationships.findIndex((r: any) => r.relationship_id === this.selectedRelationship.relationship_id);

        if(!this.isNewRelationship && index !== -1){
          this.umlModel.relationships[index] = {
            ...this.umlModel.relationships[index],
            ...this.selectedRelationship
          };
        }

        this.isSaving = false;
        this.errorMessage = '';
        this.changeDetector.detectChanges();
        const modal = document.getElementById("edit_rel_modal") as HTMLDialogElement;
        modal?.close();
      },
      error: (err) => {
        console.error("Failed to save relationship", err);
        this.errorMessage = "Failed To save relationship updates";
        this.isSaving = false;
      }
    });
  }

  openMemberModal(cls: any, type: 'attribute' | 'method', member?: any) {
    if (this.selectedClass === cls) {
      this.closeModal('edit_class_modal');
    }
    this.selectedMemberClass = cls;
    this.selectedMemberType = type;
    this.isNewMember = !member;
    this.selectedMember = member
      ? JSON.parse(JSON.stringify(member))
      : type === 'attribute'
        ? { attribute_name: '', data_type: 'String', visibility: 'public' }
        : { method_name: '', return_type: 'void', visibility: 'public' };

    const modal = document.getElementById('edit_member_modal') as HTMLDialogElement;
    modal?.showModal();
  }

  saveMemberChanges() {
    if (!this.selectedMember || !this.selectedMemberClass) return;

    const name = this.selectedMemberType === 'attribute'
      ? this.selectedMember.attribute_name
      : this.selectedMember.method_name;
    if (!name?.trim()) {
      this.errorMessage = `${this.selectedMemberType === 'attribute' ? 'Attribute' : 'Method'} name is required.`;
      return;
    }

    this.isSaving = true;
    const request = this.selectedMemberType === 'attribute'
      ? this.isNewMember
        ? this.api.createAttribute(this.selectedMemberClass.class_id, this.selectedMember)
        : this.api.updateAttribute(this.selectedMember.attribute_id, this.selectedMember)
      : this.isNewMember
        ? this.api.createMethod(this.selectedMemberClass.class_id, this.selectedMember)
        : this.api.updateMethod(this.selectedMember.method_id, this.selectedMember);

    request.subscribe({
      next: (savedMember) => {
        const memberKey = this.selectedMemberType === 'attribute' ? 'attributes' : 'methods';
        const members = this.selectedMemberClass[memberKey];
        const modelClass = this.umlModel.classes.find((cls: any) => cls.class_id === this.selectedMemberClass.class_id);
        const modelMembers = modelClass && modelClass !== this.selectedMemberClass
          ? modelClass[memberKey]
          : null;
        const idField = this.selectedMemberType === 'attribute' ? 'attribute_id' : 'method_id';
        const updateMembers = (targetMembers: any[]) => {
          const index = targetMembers.findIndex((member: any) => member[idField] === savedMember[idField]);
          if (index === -1) {
            targetMembers.push(savedMember);
          } else {
            targetMembers[index] = savedMember;
          }
        };

        updateMembers(members);
        if (modelMembers) {
          updateMembers(modelMembers);
        }

        this.isSaving = false;
        this.errorMessage = '';
        this.changeDetector.detectChanges();
        this.closeModal('edit_member_modal');
      },
      error: (err) => {
        console.error(`Failed to save ${this.selectedMemberType}`, err);
        this.errorMessage = `Failed to save ${this.selectedMemberType} changes to the database.`;
        this.isSaving = false;
      }
    });
  }

  closeModal(modalId: string){
    const modal = document.getElementById(modalId) as HTMLDialogElement
    modal?.close();
  }

  displayMethodName(methodName: string | undefined): string {
    return (methodName || '').replace(/\(\)\s*$/, '');
  }

  private dedupeRelationships(relationships: any[]): any[] {
    const seen = new Set<string>();
    return relationships.filter((relationship) => {
      const source = relationship.source_class?.class_id ?? relationship.source_class?.class_name;
      const target = relationship.target_class?.class_id ?? relationship.target_class?.class_name;
      const type = relationship.relationship_type || 'Association';
      const endpoints = type === 'Inheritance'
        ? `${source}|${target}`
        : [source, target].sort().join('|');
      const key = `${endpoints}|${type}`;
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    });
  }
}