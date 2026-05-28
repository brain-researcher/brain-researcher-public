/**
 * Question Editor Component
 * Advanced editor for survey questions with neuroimaging-specific features
 */

'use client';

import React, { useState, useEffect } from 'react';
import { 
  Type, 
  List, 
  Hash, 
  FileText, 
  BarChart, 
  Grid, 
  Brain, 
  Stethoscope,
  Microscope,
  Settings2,
  Plus,
  Trash2,
  Eye,
  EyeOff
} from 'lucide-react';

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
import { Switch } from '@/components/ui/switch';
import { Separator } from '@/components/ui/separator';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Alert, AlertDescription } from '@/components/ui/alert';

import { 
  SurveyQuestion, 
  QuestionType,
  QUESTION_TYPES,
  BRAIN_REGIONS,
  COGNITIVE_DOMAINS,
  SCANNER_PARAMETERS,
  ChoiceOption,
  ValidationRules,
  QuestionNeuroimagingContext
} from '@/types/survey';
import { NEUROIMAGING_QUESTION_TEMPLATES, getQuestionTemplate } from '@/lib/survey-templates';

interface QuestionEditorProps {
  question: Partial<SurveyQuestion>;
  onChange: (question: Partial<SurveyQuestion>) => void;
  onSave: () => void;
  onCancel: () => void;
  neuroimaging_templates?: any[];
}

const QUESTION_TYPE_ICONS: Record<QuestionType, React.ReactNode> = {
  'text': <Type className="h-4 w-4" />,
  'textarea': <FileText className="h-4 w-4" />,
  'single_choice': <List className="h-4 w-4" />,
  'multiple_choice': <List className="h-4 w-4" />,
  'scale': <BarChart className="h-4 w-4" />,
  'matrix': <Grid className="h-4 w-4" />,
  'neuroimaging_protocol': <Microscope className="h-4 w-4" />,
  'brain_region': <Brain className="h-4 w-4" />,
  'cognitive_battery': <Settings2 className="h-4 w-4" />,
  'medication_history': <Stethoscope className="h-4 w-4" />,
  'scanner_parameters': <Settings2 className="h-4 w-4" />
};

export function QuestionEditor({ 
  question, 
  onChange, 
  onSave, 
  onCancel,
  neuroimaging_templates = []
}: QuestionEditorProps) {
  const [activeTab, setActiveTab] = useState('basic');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [previewMode, setPreviewMode] = useState(false);

  // Initialize choices if needed
  useEffect(() => {
    const needsChoices = ['single_choice', 'multiple_choice'].includes(question.question_type || '');
    if (needsChoices && (!question.options?.choices || question.options.choices.length === 0)) {
      updateOptions({
        choices: [
          { id: '1', text: 'Option 1', value: 'option1' },
          { id: '2', text: 'Option 2', value: 'option2' }
        ]
      });
    }
  }, [question.question_type]);

  const updateField = (field: keyof SurveyQuestion, value: any) => {
    onChange({ ...question, [field]: value });
  };

  const updateOptions = (newOptions: Partial<typeof question.options>) => {
    updateField('options', { ...question.options, ...newOptions });
  };

  const updateValidationRules = (newRules: Partial<ValidationRules>) => {
    updateField('validation_rules', { ...question.validation_rules, ...newRules });
  };

  const updateNeuroimagingContext = (newContext: Partial<QuestionNeuroimagingContext>) => {
    updateField('neuroimaging_context', { ...question.neuroimaging_context, ...newContext });
  };

  const addChoice = () => {
    const currentChoices = question.options?.choices || [];
    const newChoice: ChoiceOption = {
      id: `choice_${Date.now()}`,
      text: `Option ${currentChoices.length + 1}`,
      value: `option${currentChoices.length + 1}`
    };
    updateOptions({ choices: [...currentChoices, newChoice] });
  };

  const updateChoice = (index: number, updates: Partial<ChoiceOption>) => {
    const currentChoices = [...(question.options?.choices || [])];
    currentChoices[index] = { ...currentChoices[index], ...updates };
    updateOptions({ choices: currentChoices });
  };

  const removeChoice = (index: number) => {
    const currentChoices = question.options?.choices || [];
    updateOptions({ choices: currentChoices.filter((_, i) => i !== index) });
  };

  const loadTemplate = (templateKey: string) => {
    const template = getQuestionTemplate(templateKey);
    if (template) {
      onChange({
        ...question,
        question_text: template.question_text,
        question_type: template.question_type,
        description: template.description,
        options: template.options,
        validation_rules: template.validation_rules,
        neuroimaging_context: template.neuroimaging_context,
        required: template.required
      });
    }
  };

  const isNeuroimagingQuestion = QUESTION_TYPES.find(
    qt => qt.value === question.question_type
  )?.neuroimaging;

  const renderBasicSettings = () => (
    <div className="space-y-6">
      {/* Question Type */}
      <div>
        <Label>Question Type</Label>
        <Select 
          value={question.question_type || ''} 
          onValueChange={(value: QuestionType) => updateField('question_type', value)}
        >
          <SelectTrigger>
            <SelectValue placeholder="Select question type" />
          </SelectTrigger>
          <SelectContent>
            {QUESTION_TYPES.map(type => (
              <SelectItem key={type.value} value={type.value}>
                <div className="flex items-center gap-2">
                  {QUESTION_TYPE_ICONS[type.value]}
                  <span>{type.label}</span>
                  {type.neuroimaging && (
                    <Badge variant="outline" className="text-xs">
                      <Brain className="h-3 w-3 mr-1" />
                      Neuro
                    </Badge>
                  )}
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Template Selection for Neuroimaging Questions */}
      {isNeuroimagingQuestion && (
        <div>
          <Label>Use Template</Label>
          <Select onValueChange={loadTemplate}>
            <SelectTrigger>
              <SelectValue placeholder="Choose a template (optional)" />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(NEUROIMAGING_QUESTION_TEMPLATES).map(([key, template]) => (
                <SelectItem key={key} value={key}>
                  {template.question_text.substring(0, 50)}...
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Question Text */}
      <div>
        <Label>Question Text *</Label>
        <Textarea
          value={question.question_text || ''}
          onChange={(e) => updateField('question_text', e.target.value)}
          placeholder="Enter your question"
          rows={3}
        />
      </div>

      {/* Description */}
      <div>
        <Label>Description (Optional)</Label>
        <Textarea
          value={question.description || ''}
          onChange={(e) => updateField('description', e.target.value)}
          placeholder="Provide additional context or instructions"
          rows={2}
        />
      </div>

      {/* Required Toggle */}
      <div className="flex items-center justify-between">
        <div>
          <Label>Required Question</Label>
          <p className="text-sm text-gray-600">Users must answer this question</p>
        </div>
        <Switch
          checked={question.required || false}
          onCheckedChange={(checked) => updateField('required', checked)}
        />
      </div>
    </div>
  );

  const renderChoiceEditor = () => {
    if (!['single_choice', 'multiple_choice', 'brain_region', 'cognitive_battery'].includes(question.question_type || '')) {
      return null;
    }

    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <Label>Answer Choices</Label>
          <Button onClick={addChoice} size="sm" variant="outline">
            <Plus className="h-4 w-4 mr-2" />
            Add Choice
          </Button>
        </div>

        <div className="space-y-3">
          {(question.options?.choices || []).map((choice, index) => (
            <div key={choice.id} className="flex items-center gap-3 p-3 border rounded-lg">
              <div className="flex-1 grid grid-cols-2 gap-2">
                <Input
                  value={choice.text}
                  onChange={(e) => updateChoice(index, { text: e.target.value })}
                  placeholder="Choice text"
                />
                <Input
                  value={choice.value?.toString() || ''}
                  onChange={(e) => updateChoice(index, { value: e.target.value })}
                  placeholder="Choice value"
                />
              </div>
              {question.options?.choices && question.options.choices.length > 2 && (
                <Button
                  onClick={() => removeChoice(index)}
                  size="sm"
                  variant="outline"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              )}
            </div>
          ))}
        </div>

        {/* Other Option Toggle */}
        <div className="flex items-center justify-between">
          <div>
            <Label>Allow "Other" Option</Label>
            <p className="text-sm text-gray-600">Let users provide custom answers</p>
          </div>
          <Switch
            checked={question.options?.other_option || false}
            onCheckedChange={(checked) => updateOptions({ other_option: checked })}
          />
        </div>
      </div>
    );
  };

  const renderScaleEditor = () => {
    if (question.question_type !== 'scale') return null;

    return (
      <div className="space-y-4">
        <div>
          <Label>Scale Type</Label>
          <Select
            value={question.options?.scale_type || 'numeric'}
            onValueChange={(value) => updateOptions({ scale_type: value as 'numeric' | 'likert' | 'visual_analog' })}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="numeric">Numeric (1-10)</SelectItem>
              <SelectItem value="likert">Likert Scale</SelectItem>
              <SelectItem value="visual_analog">Visual Analog Scale</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label>Minimum Value</Label>
            <Input
              type="number"
              value={question.options?.scale_min || 1}
              onChange={(e) => updateOptions({ scale_min: parseInt(e.target.value) })}
            />
          </div>
          <div>
            <Label>Maximum Value</Label>
            <Input
              type="number"
              value={question.options?.scale_max || 5}
              onChange={(e) => updateOptions({ scale_max: parseInt(e.target.value) })}
            />
          </div>
        </div>

        {question.options?.scale_type === 'likert' && (
          <div>
            <Label>Scale Labels</Label>
            <div className="grid grid-cols-2 gap-2 mt-2">
              <Input
                placeholder="Low label"
                value={question.options?.scale_labels?.[0] || ''}
                onChange={(e) => {
                  const labels = [...(question.options?.scale_labels || [])];
                  labels[0] = e.target.value;
                  updateOptions({ scale_labels: labels });
                }}
              />
              <Input
                placeholder="High label"
                value={question.options?.scale_labels?.[1] || ''}
                onChange={(e) => {
                  const labels = [...(question.options?.scale_labels || [])];
                  labels[1] = e.target.value;
                  updateOptions({ scale_labels: labels });
                }}
              />
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderTextEditor = () => {
    if (!['text', 'textarea'].includes(question.question_type || '')) return null;

    return (
      <div className="space-y-4">
        <div>
          <Label>Input Type</Label>
          <Select
            value={question.options?.input_type || 'text'}
            onValueChange={(value) => updateOptions({ input_type: value as 'text' | 'email' | 'number' | 'url' })}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="text">Text</SelectItem>
              <SelectItem value="email">Email</SelectItem>
              <SelectItem value="number">Number</SelectItem>
              <SelectItem value="url">URL</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label>Minimum Length</Label>
            <Input
              type="number"
              value={question.options?.min_length || ''}
              onChange={(e) => updateOptions({ min_length: parseInt(e.target.value) || undefined })}
              placeholder="No minimum"
            />
          </div>
          <div>
            <Label>Maximum Length</Label>
            <Input
              type="number"
              value={question.options?.max_length || ''}
              onChange={(e) => updateOptions({ max_length: parseInt(e.target.value) || undefined })}
              placeholder="No maximum"
            />
          </div>
        </div>
      </div>
    );
  };

  const renderValidationSettings = () => (
    <div className="space-y-6">
      <div>
        <Label>Custom Validation Message</Label>
        <Input
          value={question.validation_rules?.custom_message || ''}
          onChange={(e) => updateValidationRules({ custom_message: e.target.value })}
          placeholder="Custom error message for validation"
        />
      </div>

      {question.question_type === 'scale' && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Label>Minimum Value</Label>
              <Input
                type="number"
                value={question.validation_rules?.min_value || ''}
                onChange={(e) => updateValidationRules({ 
                  min_value: e.target.value ? parseFloat(e.target.value) : undefined 
                })}
              />
            </div>
            <div>
              <Label>Maximum Value</Label>
              <Input
                type="number"
                value={question.validation_rules?.max_value || ''}
                onChange={(e) => updateValidationRules({ 
                  max_value: e.target.value ? parseFloat(e.target.value) : undefined 
                })}
              />
            </div>
          </div>
        </div>
      )}

      {['text', 'textarea'].includes(question.question_type || '') && (
        <div>
          <Label>Regex Pattern</Label>
          <Input
            value={question.validation_rules?.regex_pattern || ''}
            onChange={(e) => updateValidationRules({ regex_pattern: e.target.value })}
            placeholder="Regular expression for validation"
          />
          <p className="text-sm text-gray-600 mt-1">
            Example: ^[A-Za-z\s]+$ (letters and spaces only)
          </p>
        </div>
      )}
    </div>
  );

  const renderNeuroimagingSettings = () => {
    if (!isNeuroimagingQuestion) return null;

    return (
      <div className="space-y-6">
        <Alert>
          <Brain className="h-4 w-4" />
          <AlertDescription>
            This question type includes neuroimaging-specific features and validation.
          </AlertDescription>
        </Alert>

        <div>
          <Label>Neuroimaging Category</Label>
          <Select
            value={question.neuroimaging_context?.category || ''}
            onValueChange={(value) => updateNeuroimagingContext({ category: value })}
          >
            <SelectTrigger>
              <SelectValue placeholder="Select category" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="acquisition_parameters">Acquisition Parameters</SelectItem>
              <SelectItem value="analysis_regions">Analysis Regions</SelectItem>
              <SelectItem value="behavioral_measures">Behavioral Measures</SelectItem>
              <SelectItem value="participant_characteristics">Participant Characteristics</SelectItem>
              <SelectItem value="quality_assessment">Quality Assessment</SelectItem>
              <SelectItem value="clinical_characteristics">Clinical Characteristics</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label>Required for Modalities</Label>
          <div className="flex flex-wrap gap-2 mt-2">
            {['fMRI', 'sMRI', 'DTI', 'EEG', 'MEG', 'PET'].map(modality => (
              <Badge
                key={modality}
                variant="outline"
                className="cursor-pointer hover:bg-blue-50"
                onClick={() => {
                  const current = question.neuroimaging_context?.required_for || [];
                  const updated = current.includes(modality)
                    ? current.filter(m => m !== modality)
                    : [...current, modality];
                  updateNeuroimagingContext({ required_for: updated });
                }}
              >
                {modality}
              </Badge>
            ))}
          </div>
        </div>

        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <Label>Atlas Support</Label>
              <p className="text-sm text-gray-600">Enable brain atlas integration</p>
            </div>
            <Switch
              checked={question.neuroimaging_context?.atlas_support || false}
              onCheckedChange={(checked) => updateNeuroimagingContext({ atlas_support: checked })}
            />
          </div>

          <div className="flex items-center justify-between">
            <div>
              <Label>Statistical Covariates</Label>
              <p className="text-sm text-gray-600">Use in statistical analysis</p>
            </div>
            <Switch
              checked={question.neuroimaging_context?.statistical_covariates || false}
              onCheckedChange={(checked) => updateNeuroimagingContext({ statistical_covariates: checked })}
            />
          </div>

          <div className="flex items-center justify-between">
            <div>
              <Label>Synchronized with Imaging</Label>
              <p className="text-sm text-gray-600">Collected during scan</p>
            </div>
            <Switch
              checked={question.neuroimaging_context?.synchronized_with_imaging || false}
              onCheckedChange={(checked) => updateNeuroimagingContext({ synchronized_with_imaging: checked })}
            />
          </div>
        </div>
      </div>
    );
  };

  const renderQuestionPreview = () => {
    if (!previewMode) return null;

    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Question Preview</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {/* Question text */}
            <div>
              <h3 className="font-semibold text-lg">
                {question.question_text || 'Question text will appear here'}
                {question.required && <span className="text-red-500 ml-1">*</span>}
              </h3>
              {question.description && (
                <p className="text-gray-600 mt-2">{question.description}</p>
              )}
            </div>

            {/* Question input based on type */}
            <div>
              {question.question_type === 'text' && (
                <Input placeholder="Text input" disabled />
              )}
              
              {question.question_type === 'textarea' && (
                <Textarea placeholder="Textarea input" rows={3} disabled />
              )}
              
              {['single_choice', 'multiple_choice'].includes(question.question_type || '') && (
                <div className="space-y-2">
                  {(question.options?.choices || []).map((choice, index) => (
                    <label key={choice.id} className="flex items-center gap-2">
                      <input
                        type={question.question_type === 'single_choice' ? 'radio' : 'checkbox'}
                        name={`preview_${question.id}`}
                        disabled
                      />
                      <span>{choice.text}</span>
                    </label>
                  ))}
                  {question.options?.other_option && (
                    <label className="flex items-center gap-2">
                      <input
                        type={question.question_type === 'single_choice' ? 'radio' : 'checkbox'}
                        disabled
                      />
                      <span>Other:</span>
                      <Input placeholder="Please specify" className="h-8 text-sm" disabled />
                    </label>
                  )}
                </div>
              )}
              
              {question.question_type === 'scale' && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm">{question.options?.scale_labels?.[0] || question.options?.scale_min || 1}</span>
                    <span className="text-sm">{question.options?.scale_labels?.[1] || question.options?.scale_max || 5}</span>
                  </div>
                  <input
                    type="range"
                    min={question.options?.scale_min || 1}
                    max={question.options?.scale_max || 5}
                    disabled
                    className="w-full"
                  />
                </div>
              )}
            </div>

            {/* Neuroimaging context indicator */}
            {question.neuroimaging_context && (
              <Badge variant="outline" className="text-xs">
                <Brain className="h-3 w-3 mr-1" />
                Neuroimaging: {question.neuroimaging_context.category}
              </Badge>
            )}
          </div>
        </CardContent>
      </Card>
    );
  };

  return (
    <div className="space-y-6">
      {/* Preview Toggle */}
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold">Question Configuration</h3>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setPreviewMode(!previewMode)}
        >
          {previewMode ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          {previewMode ? 'Hide' : 'Preview'}
        </Button>
      </div>

      {/* Preview */}
      {renderQuestionPreview()}

      {/* Editor Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid grid-cols-4 w-full">
          <TabsTrigger value="basic">Basic</TabsTrigger>
          <TabsTrigger value="options">Options</TabsTrigger>
          <TabsTrigger value="validation">Validation</TabsTrigger>
          {isNeuroimagingQuestion && (
            <TabsTrigger value="neuroimaging">Neuroimaging</TabsTrigger>
          )}
        </TabsList>

        <TabsContent value="basic" className="mt-6">
          {renderBasicSettings()}
        </TabsContent>

        <TabsContent value="options" className="mt-6">
          <div className="space-y-6">
            {renderChoiceEditor()}
            {renderScaleEditor()}
            {renderTextEditor()}
            
            {question.question_type === 'matrix' && (
              <div>
                <Alert>
                  <Grid className="h-4 w-4" />
                  <AlertDescription>
                    Matrix questions allow multiple sub-questions in a table format.
                  </AlertDescription>
                </Alert>
              </div>
            )}
          </div>
        </TabsContent>

        <TabsContent value="validation" className="mt-6">
          {renderValidationSettings()}
        </TabsContent>

        {isNeuroimagingQuestion && (
          <TabsContent value="neuroimaging" className="mt-6">
            {renderNeuroimagingSettings()}
          </TabsContent>
        )}
      </Tabs>

      {/* Action Buttons */}
      <div className="flex items-center justify-between pt-4 border-t">
        <Button variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button onClick={onSave}>
          Save Question
        </Button>
      </div>
    </div>
  );
}
