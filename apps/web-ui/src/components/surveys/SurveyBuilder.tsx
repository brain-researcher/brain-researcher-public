/**
 * Survey Builder Component
 * Main interface for creating and editing surveys with neuroimaging-specific features
 */

'use client';

import React, { useState, useEffect } from 'react';
import { useRouter, useParams } from 'next/navigation';
import {
  Save,
  Eye,
  Plus,
  Trash2,
  ChevronLeft,
  ChevronRight,
  Settings,
  LayoutTemplate,
  Brain,
  AlertCircle,
  CheckCircle
} from 'lucide-react';
import { DragDropContext, Droppable, Draggable } from 'react-beautiful-dnd';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Progress } from '@/components/ui/progress';

import { useSurveyBuilder, useSurvey } from '@/hooks/useSurvey';
import { QuestionEditor } from './QuestionEditor';
import { SurveyPreview } from './SurveyPreview';
import { TemplateLibrary } from './TemplateLibrary';
import { LogicBuilder } from './LogicBuilder';
import { 
  Survey, 
  SurveyQuestion, 
  QUESTION_TYPES, 
  SURVEY_CATEGORIES, 
  NEUROIMAGING_MODALITIES 
} from '@/types/survey';

interface SurveyBuilderProps {
  surveyId?: string;
  initialSurvey?: Partial<Survey>;
}

export function SurveyBuilder({ surveyId, initialSurvey }: SurveyBuilderProps) {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState('builder');
  const [showTemplates, setShowTemplates] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  // Load existing survey if editing
  const { survey: existingSurvey, loading: surveyLoading } = useSurvey(surveyId || null);

  // Survey builder hook
  const {
    state,
    updateSurvey,
    addQuestion,
    updateQuestion,
    removeQuestion,
    reorderQuestions,
    setCurrentQuestion,
    togglePreview,
    validateSurvey,
    saveSurvey,
    loadFromTemplate
  } = useSurveyBuilder(initialSurvey || existingSurvey || undefined);

  // Auto-save effect
  useEffect(() => {
    if (state.unsaved_changes) {
      const timer = setTimeout(() => {
        handleAutoSave();
      }, 30000); // Auto-save every 30 seconds

      return () => clearTimeout(timer);
    }
  }, [state.unsaved_changes]);

  const handleAutoSave = async () => {
    if (state.unsaved_changes && validateSurvey()) {
      setIsSaving(true);
      await saveSurvey();
      setIsSaving(false);
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    const result = await saveSurvey();
    setIsSaving(false);
    
    if (result.success && result.data?.survey_id && !surveyId) {
      router.push(`/surveys/${result.data.survey_id}/edit`);
    }
  };

  const handlePublish = async () => {
    const saveResult = await saveSurvey();
    if (saveResult.success && surveyId) {
      // Would trigger publish endpoint
      router.push(`/surveys/${surveyId}`);
    }
  };

  const handleQuestionDragEnd = (result: any) => {
    if (!result.destination) return;
    
    const sourceIndex = result.source.index;
    const destinationIndex = result.destination.index;
    
    if (sourceIndex !== destinationIndex) {
      reorderQuestions(sourceIndex, destinationIndex);
    }
  };

  const renderValidationErrors = () => {
    const errors = Object.entries(state.validation_errors);
    if (errors.length === 0) return null;

    return (
      <Alert variant="destructive" className="mb-4">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>
          <div className="font-semibold">Please fix the following errors:</div>
          <ul className="mt-2 list-disc list-inside text-sm">
            {errors.map(([field, error]) => (
              <li key={field}>{error}</li>
            ))}
          </ul>
        </AlertDescription>
      </Alert>
    );
  };

  const renderSurveySettings = () => (
    <div className="space-y-6">
      <div>
        <Label htmlFor="title">Survey Title *</Label>
        <Input
          id="title"
          value={state.survey.title || ''}
          onChange={(e) => updateSurvey({ title: e.target.value })}
          placeholder="Enter survey title"
          className={state.validation_errors.title ? 'border-red-500' : ''}
        />
        {state.validation_errors.title && (
          <p className="text-sm text-red-600 mt-1">{state.validation_errors.title}</p>
        )}
      </div>

      <div>
        <Label htmlFor="description">Description</Label>
        <Textarea
          id="description"
          value={state.survey.description || ''}
          onChange={(e) => updateSurvey({ description: e.target.value })}
          placeholder="Describe the purpose and scope of your survey"
          rows={3}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <Label htmlFor="category">Category *</Label>
          <Select 
            value={state.survey.category || ''} 
            onValueChange={(value) => updateSurvey({ category: value })}
          >
            <SelectTrigger className={state.validation_errors.category ? 'border-red-500' : ''}>
              <SelectValue placeholder="Select category" />
            </SelectTrigger>
            <SelectContent>
              {SURVEY_CATEGORIES.map(category => (
                <SelectItem key={category} value={category}>
                  {category.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase())}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {state.validation_errors.category && (
            <p className="text-sm text-red-600 mt-1">{state.validation_errors.category}</p>
          )}
        </div>

        <div>
          <Label htmlFor="target_audience">Target Audience</Label>
          <Select 
            value={state.survey.target_audience || ''} 
            onValueChange={(value) => updateSurvey({ target_audience: value })}
          >
            <SelectTrigger>
              <SelectValue placeholder="Select audience" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="researchers">Researchers</SelectItem>
              <SelectItem value="participants">Study Participants</SelectItem>
              <SelectItem value="clinicians">Clinicians</SelectItem>
              <SelectItem value="general">General Users</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Neuroimaging Context */}
      <div className="border rounded-lg p-4 space-y-4">
        <div className="flex items-center gap-2">
          <Brain className="h-5 w-5 text-blue-600" />
          <h3 className="font-semibold">Neuroimaging Context</h3>
        </div>
        
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label>Imaging Modalities</Label>
            <div className="flex flex-wrap gap-2 mt-2">
              {NEUROIMAGING_MODALITIES.map(modality => (
                <Badge
                  key={modality}
                  variant="outline"
                  className="cursor-pointer hover:bg-blue-50"
                  onClick={() => {
                    const currentModalities = state.survey.neuroimaging_context?.imaging_modalities || [];
                    const newModalities = currentModalities.includes(modality)
                      ? currentModalities.filter(m => m !== modality)
                      : [...currentModalities, modality];
                    
                    updateSurvey({
                      neuroimaging_context: {
                        ...state.survey.neuroimaging_context,
                        imaging_modalities: newModalities
                      }
                    });
                  }}
                >
                  {modality}
                </Badge>
              ))}
            </div>
          </div>

          <div>
            <Label>Study Types</Label>
            <div className="flex flex-wrap gap-2 mt-2">
              {['task-based', 'resting-state', 'structural', 'diffusion', 'clinical'].map(type => (
                <Badge
                  key={type}
                  variant="outline"
                  className="cursor-pointer hover:bg-green-50"
                  onClick={() => {
                    const currentTypes = state.survey.neuroimaging_context?.study_type || [];
                    const newTypes = currentTypes.includes(type)
                      ? currentTypes.filter(t => t !== type)
                      : [...currentTypes, type];
                    
                    updateSurvey({
                      neuroimaging_context: {
                        ...state.survey.neuroimaging_context,
                        study_type: newTypes
                      }
                    });
                  }}
                >
                  {type}
                </Badge>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );

  const renderQuestionsList = () => (
    <div className="space-y-4">
      {state.questions.length === 0 ? (
        <div className="text-center py-12 border-2 border-dashed border-gray-300 rounded-lg">
          <div className="text-gray-500">
            <Plus className="h-12 w-12 mx-auto mb-4 text-gray-400" />
            <h3 className="text-lg font-semibold mb-2">No questions yet</h3>
            <p className="mb-4">Start building your survey by adding questions</p>
            <Button onClick={() => addQuestion({ question_type: 'text' })}>
              Add First Question
            </Button>
          </div>
        </div>
      ) : (
        <DragDropContext onDragEnd={handleQuestionDragEnd}>
          <Droppable droppableId="questions">
            {(provided) => (
              <div {...provided.droppableProps} ref={provided.innerRef}>
                {state.questions.map((question, index) => (
                  <Draggable key={question.id} draggableId={question.id} index={index}>
                    {(provided, snapshot) => (
                      <div
                        ref={provided.innerRef}
                        {...provided.draggableProps}
                        {...provided.dragHandleProps}
                        className={`mb-4 ${snapshot.isDragging ? 'opacity-75' : ''}`}
                      >
                        <Card className={`cursor-pointer transition-colors ${
                          index === state.current_question_index 
                            ? 'border-blue-500 bg-blue-50' 
                            : 'hover:bg-gray-50'
                        }`}>
                          <CardHeader 
                            className="pb-3"
                            onClick={() => setCurrentQuestion(index)}
                          >
                            <div className="flex items-start justify-between">
                              <div className="flex-1">
                                <div className="flex items-center gap-2 mb-2">
                                  <Badge variant="outline">
                                    {index + 1}
                                  </Badge>
                                  <Badge variant="secondary">
                                    {QUESTION_TYPES.find(qt => qt.value === question.question_type)?.label}
                                  </Badge>
                                  {question.required && (
                                    <Badge variant="destructive" className="text-xs">
                                      Required
                                    </Badge>
                                  )}
                                  {question.neuroimaging_context && (
                                    <Badge variant="outline" className="text-xs">
                                      <Brain className="h-3 w-3 mr-1" />
                                      Neuroimaging
                                    </Badge>
                                  )}
                                </div>
                                <h4 className="font-medium text-sm">
                                  {question.question_text || 'Untitled Question'}
                                </h4>
                                {question.description && (
                                  <p className="text-xs text-gray-600 mt-1">
                                    {question.description}
                                  </p>
                                )}
                              </div>
                              <div className="flex items-center gap-2">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setCurrentQuestion(index);
                                  }}
                                >
                                  Edit
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    removeQuestion(index);
                                  }}
                                >
                                  <Trash2 className="h-4 w-4" />
                                </Button>
                              </div>
                            </div>
                          </CardHeader>
                        </Card>
                      </div>
                    )}
                  </Draggable>
                ))}
                {provided.placeholder}
              </div>
            )}
          </Droppable>
        </DragDropContext>
      )}

      {/* Add Question Button */}
      <Card className="border-dashed">
        <CardContent className="pt-6 text-center">
          <Button 
            onClick={() => addQuestion({ question_type: 'text' })}
            variant="outline"
            className="w-full"
          >
            <Plus className="h-4 w-4 mr-2" />
            Add Question
          </Button>
        </CardContent>
      </Card>
    </div>
  );

  const renderProgressIndicator = () => {
    const totalSteps = ['Settings', 'Questions', 'Logic', 'Preview'];
    const currentStep = activeTab === 'settings' ? 0 : 
                      activeTab === 'builder' ? 1 :
                      activeTab === 'logic' ? 2 : 3;
    
    return (
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium">Survey Builder Progress</span>
          <span className="text-sm text-gray-600">
            Step {currentStep + 1} of {totalSteps.length}
          </span>
        </div>
        <Progress value={(currentStep + 1) / totalSteps.length * 100} />
        <div className="flex justify-between mt-2 text-xs text-gray-500">
          {totalSteps.map((step, index) => (
            <span 
              key={step}
              className={index <= currentStep ? 'text-blue-600 font-medium' : ''}
            >
              {step}
            </span>
          ))}
        </div>
      </div>
    );
  };

  if (surveyLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p>Loading survey...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">
            {surveyId ? 'Edit Survey' : 'Create Survey'}
          </h1>
          <p className="text-gray-600 mt-1">
            {surveyId ? 'Modify your existing survey' : 'Build a new neuroimaging survey'}
          </p>
        </div>

        <div className="flex items-center gap-3">
          {state.unsaved_changes && (
            <Badge variant="outline" className="text-orange-600">
              {isSaving ? 'Saving...' : 'Unsaved changes'}
            </Badge>
          )}
          
          <Button
            variant="outline"
            onClick={() => setShowTemplates(true)}
            disabled={isSaving}
          >
            <LayoutTemplate className="h-4 w-4 mr-2" />
            Templates
          </Button>

          <Button
            variant="outline"
            onClick={handleSave}
            disabled={isSaving}
          >
            <Save className="h-4 w-4 mr-2" />
            {isSaving ? 'Saving...' : 'Save'}
          </Button>

          {surveyId && (
            <Button onClick={handlePublish}>
              Publish Survey
            </Button>
          )}
        </div>
      </div>

      {/* Progress Indicator */}
      {renderProgressIndicator()}

      {/* Validation Errors */}
      {renderValidationErrors()}

      {/* Main Content */}
      <div className="grid grid-cols-12 gap-6">
        {/* Main Content Area */}
        <div className="col-span-8">
          <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
            <TabsList className="grid grid-cols-4 w-full mb-6">
              <TabsTrigger value="settings">Settings</TabsTrigger>
              <TabsTrigger value="builder">Questions</TabsTrigger>
              <TabsTrigger value="logic">Logic</TabsTrigger>
              <TabsTrigger value="preview">Preview</TabsTrigger>
            </TabsList>

            <TabsContent value="settings">
              <Card>
                <CardHeader>
                  <CardTitle>Survey Configuration</CardTitle>
                </CardHeader>
                <CardContent>
                  {renderSurveySettings()}
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="builder">
              <div className="space-y-6">
                {renderQuestionsList()}
              </div>
            </TabsContent>

            <TabsContent value="logic">
              <LogicBuilder
                questions={state.questions}
                logic={state.survey.settings?.logic}
                onChange={(logic) => updateSurvey({
                  settings: {
                    ...state.survey.settings,
                    logic
                  }
                })}
              />
            </TabsContent>

            <TabsContent value="preview">
              <SurveyPreview
                survey={{
                  ...state.survey,
                  questions: state.questions
                } as Survey}
              />
            </TabsContent>
          </Tabs>
        </div>

        {/* Sidebar */}
        <div className="col-span-4">
          {activeTab === 'builder' && state.questions.length > 0 && (
            <Card className="sticky top-6">
              <CardHeader>
                <CardTitle className="text-lg">Question Editor</CardTitle>
              </CardHeader>
              <CardContent>
                <QuestionEditor
                  question={state.questions[state.current_question_index]}
                  onChange={(updatedQuestion) => 
                    updateQuestion(state.current_question_index, updatedQuestion)
                  }
                  onSave={handleSave}
                  onCancel={() => setCurrentQuestion(0)}
                />
              </CardContent>
            </Card>
          )}

          {activeTab === 'settings' && (
            <Card className="sticky top-6">
              <CardHeader>
                <CardTitle className="text-lg">Survey Statistics</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex justify-between">
                  <span className="text-sm text-gray-600">Questions</span>
                  <span className="font-medium">{state.questions.length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-sm text-gray-600">Required Questions</span>
                  <span className="font-medium">
                    {state.questions.filter(q => q.required).length}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-sm text-gray-600">Neuroimaging Questions</span>
                  <span className="font-medium">
                    {state.questions.filter(q => q.neuroimaging_context).length}
                  </span>
                </div>
                <Separator />
                <div className="flex justify-between">
                  <span className="text-sm text-gray-600">Est. Completion Time</span>
                  <span className="font-medium">
                    {Math.ceil(state.questions.length * 1.5)} min
                  </span>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* Template Library Modal */}
      {showTemplates && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg max-w-4xl w-full max-h-[80vh] overflow-hidden">
            <TemplateLibrary
              onSelectTemplate={loadFromTemplate}
              onClose={() => setShowTemplates(false)}
            />
          </div>
        </div>
      )}
    </div>
  );
}