/**
 * Template Library Component
 * Browse and select from pre-built neuroimaging survey templates
 */

'use client';

import React, { useState, useEffect } from 'react';
import { 
  Search, 
  Filter, 
  Star, 
  Eye, 
  Download, 
  Brain,
  Users,
  Clock,
  CheckCircle,
  X,
  Microscope,
  Activity,
  Settings
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from '@/components/ui/select';
import { Alert, AlertDescription } from '@/components/ui/alert';

import { SurveyTemplate } from '@/types/survey';
import { SURVEY_TEMPLATES, getTemplatesByCategory, getTemplatesByModality } from '@/lib/survey-templates';

interface TemplateLibraryProps {
  onSelectTemplate: (template: SurveyTemplate) => void;
  onClose: () => void;
}

const TEMPLATE_ICONS: Record<string, React.ReactNode> = {
  'neuroimaging_protocol': <Brain className="h-5 w-5" />,
  'clinical_research': <Microscope className="h-5 w-5" />,
  'quality_assessment': <CheckCircle className="h-5 w-5" />,
  'user_feedback': <Users className="h-5 w-5" />,
  'demographic_survey': <Users className="h-5 w-5" />,
  'baseline_assessment': <Activity className="h-5 w-5" />,
  'followup_assessment': <Activity className="h-5 w-5" />,
  'custom': <Settings className="h-5 w-5" />
};

export function TemplateLibrary({ onSelectTemplate, onClose }: TemplateLibraryProps) {
  const [templates, setTemplates] = useState<SurveyTemplate[]>(SURVEY_TEMPLATES);
  const [filteredTemplates, setFilteredTemplates] = useState<SurveyTemplate[]>(SURVEY_TEMPLATES);
  const [selectedTemplate, setSelectedTemplate] = useState<SurveyTemplate | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<string>('all');
  const [modalityFilter, setModalityFilter] = useState<string>('all');
  const [loading, setLoading] = useState(false);

  // Filter templates based on search and filters
  useEffect(() => {
    let filtered = templates;

    // Apply search filter
    if (searchTerm) {
      filtered = filtered.filter(template =>
        template.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        template.description.toLowerCase().includes(searchTerm.toLowerCase()) ||
        template.tags.some(tag => tag.toLowerCase().includes(searchTerm.toLowerCase()))
      );
    }

    // Apply category filter
    if (categoryFilter !== 'all') {
      filtered = filtered.filter(template => template.category === categoryFilter);
    }

    // Apply modality filter
    if (modalityFilter !== 'all') {
      filtered = filtered.filter(template =>
        template.neuroimaging_focus.includes(modalityFilter)
      );
    }

    setFilteredTemplates(filtered);
  }, [templates, searchTerm, categoryFilter, modalityFilter]);

  const getCategories = () => {
    const categories = Array.from(new Set(templates.map(t => t.category)));
    return categories.map(cat => ({
      value: cat,
      label: cat.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase())
    }));
  };

  const getModalities = () => {
    const modalities = Array.from(new Set(templates.flatMap(t => t.neuroimaging_focus)));
    return modalities.filter(m => m !== 'custom' && m !== 'platform');
  };

  const handleTemplateSelect = (template: SurveyTemplate) => {
    setSelectedTemplate(template);
  };

  const handleUseTemplate = (template: SurveyTemplate) => {
    onSelectTemplate(template);
    onClose();
  };

  const renderTemplateCard = (template: SurveyTemplate) => (
    <Card 
      key={template.id}
      className={`cursor-pointer transition-all hover:shadow-lg ${
        selectedTemplate?.id === template.id ? 'ring-2 ring-blue-500' : ''
      }`}
      onClick={() => handleTemplateSelect(template)}
    >
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex items-start gap-3">
            <div className="p-2 bg-blue-100 rounded-lg">
              {TEMPLATE_ICONS[template.category] || <Settings className="h-5 w-5" />}
            </div>
            <div className="flex-1">
              <CardTitle className="text-lg mb-1">{template.name}</CardTitle>
              <p className="text-sm text-gray-600 line-clamp-2">
                {template.description}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1 text-yellow-500">
            <Star className="h-4 w-4" />
            <span className="text-sm font-medium">
              {(template.usage_count / 10).toFixed(1)}
            </span>
          </div>
        </div>
      </CardHeader>
      
      <CardContent className="pt-0 space-y-3">
        {/* Category and Tags */}
        <div className="flex flex-wrap gap-2">
          <Badge variant="outline">
            {template.category.replace('_', ' ')}
          </Badge>
          {template.neuroimaging_focus.filter(focus => focus !== 'custom').map(focus => (
            <Badge key={focus} variant="secondary" className="text-xs">
              <Brain className="h-3 w-3 mr-1" />
              {focus}
            </Badge>
          ))}
        </div>

        {/* Metadata */}
        <div className="grid grid-cols-3 gap-4 text-sm text-gray-600">
          <div className="flex items-center gap-1">
            <CheckCircle className="h-4 w-4" />
            <span>{template.template_questions.length} questions</span>
          </div>
          <div className="flex items-center gap-1">
            <Clock className="h-4 w-4" />
            <span>~{Math.ceil(template.template_questions.length * 1.5)} min</span>
          </div>
          <div className="flex items-center gap-1">
            <Users className="h-4 w-4" />
            <span>{template.usage_count} uses</span>
          </div>
        </div>

        {/* Study Types */}
        {template.study_types.length > 0 && (
          <div>
            <div className="text-xs text-gray-500 mb-1">Study Types:</div>
            <div className="flex flex-wrap gap-1">
              {template.study_types.map(type => (
                <Badge key={type} variant="outline" className="text-xs">
                  {type}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Cognitive Domains */}
        {template.cognitive_domains.length > 0 && (
          <div>
            <div className="text-xs text-gray-500 mb-1">Cognitive Domains:</div>
            <div className="flex flex-wrap gap-1">
              {template.cognitive_domains.map(domain => (
                <Badge key={domain} variant="outline" className="text-xs">
                  {domain.replace('_', ' ')}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );

  const renderTemplateDetail = () => {
    if (!selectedTemplate) return null;

    return (
      <div className="space-y-6">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-2xl font-bold mb-2">{selectedTemplate.name}</h3>
            <p className="text-gray-600">{selectedTemplate.description}</p>
          </div>
          <Button
            onClick={() => handleUseTemplate(selectedTemplate)}
            size="lg"
            className="bg-green-600 hover:bg-green-700"
          >
            <Download className="h-4 w-4 mr-2" />
            Use This Template
          </Button>
        </div>

        <div className="grid grid-cols-2 gap-6">
          {/* Template Info */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Template Information</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <div className="text-sm font-medium text-gray-700 mb-2">Category</div>
                <Badge variant="outline">
                  {selectedTemplate.category.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase())}
                </Badge>
              </div>

              <div>
                <div className="text-sm font-medium text-gray-700 mb-2">Neuroimaging Focus</div>
                <div className="flex flex-wrap gap-2">
                  {selectedTemplate.neuroimaging_focus.map(focus => (
                    <Badge key={focus} variant="secondary">
                      <Brain className="h-3 w-3 mr-1" />
                      {focus}
                    </Badge>
                  ))}
                </div>
              </div>

              <div>
                <div className="text-sm font-medium text-gray-700 mb-2">Study Types</div>
                <div className="flex flex-wrap gap-2">
                  {selectedTemplate.study_types.map(type => (
                    <Badge key={type} variant="outline">
                      {type}
                    </Badge>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <div className="font-medium text-gray-700">Questions</div>
                  <div className="text-2xl font-bold text-blue-600">
                    {selectedTemplate.template_questions.length}
                  </div>
                </div>
                <div>
                  <div className="font-medium text-gray-700">Est. Time</div>
                  <div className="text-2xl font-bold text-green-600">
                    ~{Math.ceil(selectedTemplate.template_questions.length * 1.5)} min
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Questions Preview */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Questions Preview</CardTitle>
            </CardHeader>
            <CardContent className="max-h-96 overflow-y-auto">
              <div className="space-y-3">
                {selectedTemplate.template_questions.map((question, index) => (
                  <div key={index} className="border-l-4 border-blue-200 pl-4">
                    <div className="flex items-start gap-2 mb-2">
                      <Badge variant="outline" className="text-xs">
                        {index + 1}
                      </Badge>
                      <Badge variant="secondary" className="text-xs">
                        {question.question_type.replace('_', ' ')}
                      </Badge>
                      {question.required && (
                        <Badge variant="destructive" className="text-xs">
                          Required
                        </Badge>
                      )}
                      {question.neuroimaging_context && (
                        <Badge variant="outline" className="text-xs">
                          <Brain className="h-3 w-3 mr-1" />
                          Neuro
                        </Badge>
                      )}
                    </div>
                    <div className="text-sm font-medium text-gray-900 mb-1">
                      {question.question_text}
                    </div>
                    {question.description && (
                      <div className="text-xs text-gray-600">
                        {question.description}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Settings Preview */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Default Settings</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-6 text-sm">
              <div>
                <div className="font-medium text-gray-700 mb-2">Theme</div>
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <div 
                      className="w-4 h-4 rounded"
                      style={{ backgroundColor: selectedTemplate.default_settings.theme?.primary_color }}
                    />
                    <span>Primary Color</span>
                  </div>
                  <div className="text-xs text-gray-600">
                    Font: {selectedTemplate.default_settings.theme?.font_family}
                  </div>
                </div>
              </div>
              
              <div>
                <div className="font-medium text-gray-700 mb-2">Validation</div>
                <div className="space-y-1 text-xs">
                  <div>Required questions: {selectedTemplate.default_settings.validation?.require_all_questions ? 'Yes' : 'No'}</div>
                  <div>Email validation: {selectedTemplate.default_settings.validation?.email_validation ? 'Yes' : 'No'}</div>
                </div>
              </div>

              <div>
                <div className="font-medium text-gray-700 mb-2">Privacy</div>
                <div className="space-y-1 text-xs">
                  <div>Anonymous: {selectedTemplate.default_settings.privacy?.anonymous_responses ? 'Yes' : 'No'}</div>
                  <div>GDPR: {selectedTemplate.default_settings.privacy?.gdpr_compliant ? 'Yes' : 'No'}</div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  };

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between p-6 border-b">
        <div>
          <h2 className="text-2xl font-bold">Survey Templates</h2>
          <p className="text-gray-600">Choose from pre-built neuroimaging survey templates</p>
        </div>
        <Button variant="outline" size="sm" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Filters */}
      <div className="p-6 border-b bg-gray-50">
        <div className="flex items-center gap-4">
          <div className="flex-1">
            <div className="relative">
              <Search className="h-4 w-4 absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" />
              <Input
                placeholder="Search templates..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="pl-10"
              />
            </div>
          </div>
          
          <div className="flex items-center gap-3">
            <Select value={categoryFilter} onValueChange={setCategoryFilter}>
              <SelectTrigger className="w-40">
                <SelectValue placeholder="All Categories" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Categories</SelectItem>
                {getCategories().map(category => (
                  <SelectItem key={category.value} value={category.value}>
                    {category.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={modalityFilter} onValueChange={setModalityFilter}>
              <SelectTrigger className="w-40">
                <SelectValue placeholder="All Modalities" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Modalities</SelectItem>
                {getModalities().map(modality => (
                  <SelectItem key={modality} value={modality}>
                    {modality}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="flex items-center justify-between mt-4">
          <div className="text-sm text-gray-600">
            {filteredTemplates.length} of {templates.length} templates
          </div>
          
          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-gray-400" />
            <span className="text-sm text-gray-600">
              {categoryFilter !== 'all' && `Category: ${categoryFilter}`}
              {categoryFilter !== 'all' && modalityFilter !== 'all' && ' • '}
              {modalityFilter !== 'all' && `Modality: ${modalityFilter}`}
            </span>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Template Grid */}
        <div className="flex-1 p-6 overflow-y-auto">
          {loading ? (
            <div className="text-center py-12">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
              <p>Loading templates...</p>
            </div>
          ) : filteredTemplates.length === 0 ? (
            <div className="text-center py-12">
              <Search className="h-16 w-16 mx-auto mb-4 text-gray-400" />
              <h3 className="text-xl font-semibold mb-2">No templates found</h3>
              <p className="text-gray-600 mb-4">Try adjusting your search or filters</p>
              <Button variant="outline" onClick={() => {
                setSearchTerm('');
                setCategoryFilter('all');
                setModalityFilter('all');
              }}>
                Clear Filters
              </Button>
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {filteredTemplates.map(renderTemplateCard)}
            </div>
          )}
        </div>

        {/* Template Detail */}
        {selectedTemplate && (
          <div className="w-1/2 border-l bg-white p-6 overflow-y-auto">
            {renderTemplateDetail()}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="p-6 border-t bg-gray-50">
        <Alert>
          <Brain className="h-4 w-4" />
          <AlertDescription>
            All templates are designed specifically for neuroimaging research and include 
            appropriate validation rules and neuroimaging-specific question types.
          </AlertDescription>
        </Alert>
      </div>
    </div>
  );
}