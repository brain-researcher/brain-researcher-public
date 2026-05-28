/**
 * Question Renderer Component
 * Renders individual questions with appropriate input controls based on question type
 */

'use client';

import React, { useState, useEffect } from 'react';
import { Brain, MapPin, Clock, Stethoscope } from 'lucide-react';

import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Checkbox } from '@/components/ui/checkbox';
import { Slider } from '@/components/ui/slider';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';

import { SurveyQuestion, ChoiceOption } from '@/types/survey';

interface QuestionRendererProps {
  question: SurveyQuestion;
  value: any;
  onChange: (value: any, metadata?: Record<string, any>) => void;
  readonly?: boolean;
  theme?: {
    primaryColor?: string;
    secondaryColor?: string;
    fontFamily?: string;
  };
}

export function QuestionRenderer({ 
  question, 
  value, 
  onChange, 
  readonly = false,
  theme
}: QuestionRendererProps) {
  const [otherValue, setOtherValue] = useState('');
  const [validationError, setValidationError] = useState<string | null>(null);

  // Clear validation error when value changes
  useEffect(() => {
    if (value !== undefined && value !== '') {
      setValidationError(null);
    }
  }, [value]);

  const validateInput = (inputValue: any): string | null => {
    const rules = question.validation_rules;
    
    if (question.required && (inputValue === undefined || inputValue === '' || 
        (Array.isArray(inputValue) && inputValue.length === 0))) {
      return 'This field is required';
    }

    if (inputValue && rules) {
      // Text length validation
      if (typeof inputValue === 'string') {
        if (question.options?.min_length && inputValue.length < question.options.min_length) {
          return `Minimum length is ${question.options.min_length} characters`;
        }
        if (question.options?.max_length && inputValue.length > question.options.max_length) {
          return `Maximum length is ${question.options.max_length} characters`;
        }
        if (rules.regex_pattern) {
          const regex = new RegExp(rules.regex_pattern);
          if (!regex.test(inputValue)) {
            return rules.custom_message || 'Invalid format';
          }
        }
      }

      // Numeric validation
      if (typeof inputValue === 'number' || (typeof inputValue === 'string' && !isNaN(Number(inputValue)))) {
        const numValue = Number(inputValue);
        if (rules.min_value !== undefined && numValue < rules.min_value) {
          return `Minimum value is ${rules.min_value}`;
        }
        if (rules.max_value !== undefined && numValue > rules.max_value) {
          return `Maximum value is ${rules.max_value}`;
        }
      }
    }

    return null;
  };

  const handleChange = (newValue: any) => {
    if (readonly) return;

    const error = validateInput(newValue);
    setValidationError(error);

    onChange(newValue, {
      question_type: question.question_type,
      has_error: !!error,
      neuroimaging_context: question.neuroimaging_context?.category
    });
  };

  const renderTextInput = () => {
    const inputType = question.options?.input_type || 'text';
    const isTextarea = question.question_type === 'textarea';

    if (isTextarea) {
      return (
        <Textarea
          value={value || ''}
          onChange={(e) => handleChange(e.target.value)}
          placeholder="Enter your response..."
          rows={4}
          disabled={readonly}
          className={validationError ? 'border-red-500' : ''}
        />
      );
    }

    return (
      <Input
        type={inputType}
        value={value || ''}
        onChange={(e) => handleChange(e.target.value)}
        placeholder="Enter your response..."
        disabled={readonly}
        className={validationError ? 'border-red-500' : ''}
      />
    );
  };

  const renderSingleChoice = () => {
    const choices = question.options?.choices || [];
    const hasOther = question.options?.other_option;

    return (
      <div className="space-y-3">
        <RadioGroup
          value={value?.toString() || ''}
          onValueChange={(newValue) => {
            if (newValue === 'other') {
              handleChange({ value: 'other', other_text: otherValue });
            } else {
              handleChange(newValue);
            }
          }}
          disabled={readonly}
        >
          {choices.map((choice) => (
            <div key={choice.id} className="flex items-center space-x-2">
              <RadioGroupItem value={choice.value?.toString() || choice.text} id={choice.id} />
              <Label htmlFor={choice.id} className="flex-1 cursor-pointer">
                <div className="flex items-center gap-2">
                  <span>{choice.text}</span>
                  {choice.neuroimaging_metadata && (
                    <Badge variant="outline" className="text-xs">
                      <Brain className="h-3 w-3 mr-1" />
                      {choice.neuroimaging_metadata.domain}
                    </Badge>
                  )}
                </div>
                {choice.description && (
                  <p className="text-sm text-gray-600 mt-1">{choice.description}</p>
                )}
              </Label>
            </div>
          ))}
          
          {hasOther && (
            <div className="flex items-center space-x-2">
              <RadioGroupItem value="other" id="other" />
              <Label htmlFor="other" className="cursor-pointer">Other:</Label>
              <Input
                placeholder="Please specify..."
                value={otherValue}
                onChange={(e) => {
                  setOtherValue(e.target.value);
                  if (value === 'other' || (value && value.value === 'other')) {
                    handleChange({ value: 'other', other_text: e.target.value });
                  }
                }}
                disabled={readonly}
                className="ml-2 max-w-xs"
              />
            </div>
          )}
        </RadioGroup>
      </div>
    );
  };

  const renderMultipleChoice = () => {
    const choices = question.options?.choices || [];
    const hasOther = question.options?.other_option;
    const selectedValues = Array.isArray(value) ? value : [];

    const handleChoiceChange = (choiceValue: string, checked: boolean) => {
      let newValues;
      if (checked) {
        newValues = [...selectedValues, choiceValue];
      } else {
        newValues = selectedValues.filter(v => v !== choiceValue);
      }
      handleChange(newValues);
    };

    return (
      <div className="space-y-3">
        {choices.map((choice) => (
          <div key={choice.id} className="flex items-center space-x-2">
            <Checkbox
              id={choice.id}
              checked={selectedValues.includes(choice.value?.toString() || choice.text)}
              onCheckedChange={(checked) => 
                handleChoiceChange(choice.value?.toString() || choice.text, checked as boolean)
              }
              disabled={readonly}
            />
            <Label htmlFor={choice.id} className="flex-1 cursor-pointer">
              <div className="flex items-center gap-2">
                <span>{choice.text}</span>
                {choice.neuroimaging_metadata && (
                  <Badge variant="outline" className="text-xs">
                    <Brain className="h-3 w-3 mr-1" />
                    {choice.neuroimaging_metadata.domain}
                  </Badge>
                )}
              </div>
              {choice.description && (
                <p className="text-sm text-gray-600 mt-1">{choice.description}</p>
              )}
            </Label>
          </div>
        ))}
        
        {hasOther && (
          <div className="flex items-center space-x-2">
            <Checkbox
              id="other"
              checked={selectedValues.includes('other')}
              onCheckedChange={(checked) => {
                if (checked) {
                  handleChange([...selectedValues, 'other']);
                } else {
                  handleChange(selectedValues.filter(v => v !== 'other'));
                  setOtherValue('');
                }
              }}
              disabled={readonly}
            />
            <Label htmlFor="other" className="cursor-pointer">Other:</Label>
            <Input
              placeholder="Please specify..."
              value={otherValue}
              onChange={(e) => setOtherValue(e.target.value)}
              disabled={readonly || !selectedValues.includes('other')}
              className="ml-2 max-w-xs"
            />
          </div>
        )}
      </div>
    );
  };

  const renderScaleQuestion = () => {
    const min = question.options?.scale_min || 1;
    const max = question.options?.scale_max || 5;
    const scaleType = question.options?.scale_type || 'numeric';
    const labels = question.options?.scale_labels || [];

    if (scaleType === 'visual_analog') {
      return (
        <div className="space-y-4">
          <div className="px-4">
            <Slider
              value={[value || min]}
              onValueChange={([newValue]) => handleChange(newValue)}
              min={min}
              max={max}
              step={0.1}
              disabled={readonly}
              className="w-full"
            />
          </div>
          <div className="flex justify-between text-sm text-gray-600">
            <span>{labels[0] || min}</span>
            <span className="font-medium">Current: {(value || min).toFixed(1)}</span>
            <span>{labels[1] || max}</span>
          </div>
        </div>
      );
    }

    // Numeric or Likert scale
    const scaleValues = Array.from({ length: max - min + 1 }, (_, i) => min + i);
    
    return (
      <div className="space-y-4">
        <RadioGroup
          value={value?.toString() || ''}
          onValueChange={(newValue) => handleChange(parseInt(newValue))}
          disabled={readonly}
          className="flex justify-center"
        >
          <div className="flex items-center space-x-4">
            {scaleValues.map((scaleValue) => (
              <div key={scaleValue} className="text-center">
                <RadioGroupItem 
                  value={scaleValue.toString()} 
                  id={`scale-${scaleValue}`}
                  className="mx-auto"
                />
                <Label 
                  htmlFor={`scale-${scaleValue}`} 
                  className="block mt-2 text-sm cursor-pointer"
                >
                  {scaleValue}
                </Label>
              </div>
            ))}
          </div>
        </RadioGroup>
        
        {labels.length >= 2 && (
          <div className="flex justify-between text-sm text-gray-600 mt-2">
            <span>{labels[0]}</span>
            <span>{labels[1]}</span>
          </div>
        )}
      </div>
    );
  };

  const renderMatrixQuestion = () => {
    const rows = question.options?.rows || [];
    const columns = question.options?.columns || [];
    const matrixValue = value || {};

    return (
      <div className="overflow-x-auto">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="text-left p-2"></th>
              {columns.map((col, colIndex) => (
                <th key={colIndex} className="text-center p-2 border-b font-medium">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                <td className="p-2 font-medium border-b">{row}</td>
                {columns.map((col, colIndex) => (
                  <td key={colIndex} className="text-center p-2 border-b">
                    <RadioGroup
                      value={matrixValue[row] || ''}
                      onValueChange={(newValue) => {
                        const newMatrixValue = { ...matrixValue, [row]: newValue };
                        handleChange(newMatrixValue);
                      }}
                      disabled={readonly}
                    >
                      <RadioGroupItem 
                        value={col} 
                        id={`matrix-${rowIndex}-${colIndex}`}
                      />
                    </RadioGroup>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const renderNeuroimagingProtocol = () => {
    const scannerParams = question.options?.scanner_parameters;
    const protocols = Array.isArray(scannerParams) ? scannerParams : scannerParams ? [scannerParams] : [];
    
    return (
      <div className="space-y-4">
        <Alert>
          <Brain className="h-4 w-4" />
          <AlertDescription>
            Select or specify the neuroimaging protocol parameters used in your study.
          </AlertDescription>
        </Alert>
        
        <div className="grid gap-4">
          {protocols.map((protocol, index) => (
            <Card 
              key={index}
              className={`cursor-pointer transition-colors ${
                JSON.stringify(value) === JSON.stringify(protocol) 
                  ? 'ring-2 ring-blue-500 bg-blue-50' 
                  : 'hover:bg-gray-50'
              }`}
              onClick={() => !readonly && handleChange(protocol)}
            >
              <CardContent className="p-4">
                <div className="flex justify-between items-start">
                  <div>
                    <div className="font-medium">{protocol.field_strength} {protocol.manufacturer}</div>
                    <div className="text-sm text-gray-600">{protocol.pulse_sequence}</div>
                    <div className="text-xs text-gray-500 mt-1">
                      Voxel: {protocol.voxel_size?.join('×')}mm | TR: {protocol.repetition_time}ms
                    </div>
                  </div>
                  <Badge variant={JSON.stringify(value) === JSON.stringify(protocol) ? 'default' : 'outline'}>
                    {JSON.stringify(value) === JSON.stringify(protocol) ? 'Selected' : 'Select'}
                  </Badge>
                </div>
              </CardContent>
            </Card>
          ))}
          
          {question.options?.custom_allowed && (
            <Card className="border-dashed">
              <CardContent className="p-4">
                <div className="text-center">
                  <Button 
                    variant="outline" 
                    onClick={() => !readonly && handleChange('custom')}
                    disabled={readonly}
                  >
                    Specify Custom Parameters
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    );
  };

  const renderBrainRegionSelector = () => {
    const regions = question.options?.brain_regions || [];
    const selectedRegions = Array.isArray(value) ? value : [];

    return (
      <div className="space-y-4">
        <Alert>
          <MapPin className="h-4 w-4" />
          <AlertDescription>
            Select the brain regions that were analyzed or are relevant to your study.
          </AlertDescription>
        </Alert>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {regions.map((region, index) => (
            <Card 
              key={index}
              className={`cursor-pointer transition-colors ${
                selectedRegions.some((r: any) => r.name === region.name)
                  ? 'ring-2 ring-blue-500 bg-blue-50' 
                  : 'hover:bg-gray-50'
              }`}
              onClick={() => {
                if (readonly) return;
                
                const isSelected = selectedRegions.some((r: any) => r.name === region.name);
                if (isSelected) {
                  handleChange(selectedRegions.filter((r: any) => r.name !== region.name));
                } else {
                  handleChange([...selectedRegions, region]);
                }
              }}
            >
              <CardContent className="p-3">
                <div className="flex justify-between items-center">
                  <div>
                    <div className="font-medium text-sm">{region.name}</div>
                    <div className="text-xs text-gray-500">
                      {region.atlas} | {region.hemisphere}
                    </div>
                    {region.coordinates && (
                      <div className="text-xs text-gray-400">
                        ({region.coordinates.x}, {region.coordinates.y}, {region.coordinates.z})
                      </div>
                    )}
                  </div>
                  <Checkbox
                    checked={selectedRegions.some((r: any) => r.name === region.name)}
                    onChange={() => {}}
                    disabled={readonly}
                  />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  };

  const renderCognitiveBattery = () => {
    const assessments = question.options?.cognitive_assessments || [];
    const selectedAssessments = Array.isArray(value) ? value : [];

    return (
      <div className="space-y-4">
        <Alert>
          <Clock className="h-4 w-4" />
          <AlertDescription>
            Select the cognitive assessments that were administered in your study.
          </AlertDescription>
        </Alert>
        
        <div className="space-y-2">
          {assessments.map((domain, domainIndex) => (
            <div key={domainIndex} className="border rounded-lg p-4">
              <div className="font-medium text-sm mb-3 text-blue-900">{domain.name}</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {domain.assessments?.map((assessment, assessmentIndex) => (
                  <label key={assessmentIndex} className="flex items-center space-x-2 cursor-pointer">
                    <Checkbox
                      checked={selectedAssessments.includes(assessment)}
                      onCheckedChange={(checked) => {
                        if (readonly) return;
                        
                        if (checked) {
                          handleChange([...selectedAssessments, assessment]);
                        } else {
                          handleChange(selectedAssessments.filter(a => a !== assessment));
                        }
                      }}
                      disabled={readonly}
                    />
                    <span className="text-sm">{assessment}</span>
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const renderMedicationHistory = () => {
    const categories = question.options?.medication_categories || [];

    return (
      <div className="space-y-4">
        <Alert>
          <Stethoscope className="h-4 w-4" />
          <AlertDescription>
            Please provide medication information that may affect neuroimaging results.
            This information is kept confidential and used only for research purposes.
          </AlertDescription>
        </Alert>
        
        <RadioGroup
          value={value?.toString() || ''}
          onValueChange={(newValue) => handleChange(newValue)}
          disabled={readonly}
        >
          {categories.map((category, index) => (
            <div key={index} className="flex items-center space-x-2">
              <RadioGroupItem value={category} id={`med-${index}`} />
              <Label htmlFor={`med-${index}`} className="flex-1 cursor-pointer">
                {category}
              </Label>
            </div>
          ))}
        </RadioGroup>
      </div>
    );
  };

  const renderByQuestionType = () => {
    switch (question.question_type) {
      case 'text':
      case 'textarea':
        return renderTextInput();
      case 'single_choice':
        return renderSingleChoice();
      case 'multiple_choice':
        return renderMultipleChoice();
      case 'scale':
        return renderScaleQuestion();
      case 'matrix':
        return renderMatrixQuestion();
      case 'neuroimaging_protocol':
      case 'scanner_parameters':
        return renderNeuroimagingProtocol();
      case 'brain_region':
        return renderBrainRegionSelector();
      case 'cognitive_battery':
        return renderCognitiveBattery();
      case 'medication_history':
        return renderMedicationHistory();
      default:
        return renderTextInput();
    }
  };

  return (
    <div className="space-y-4">
      {renderByQuestionType()}
      
      {validationError && (
        <Alert variant="destructive">
          <AlertDescription>{validationError}</AlertDescription>
        </Alert>
      )}
      
      {readonly && value !== undefined && (
        <div className="text-sm text-gray-600 italic">
          Response recorded: {JSON.stringify(value)}
        </div>
      )}
    </div>
  );
}