/**
 * Response Rate Chart Component
 * Visualizes survey response rates over time
 */

'use client';

import React from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar
} from 'recharts';

interface ResponseRateChartProps {
  data: Record<string, any>;
  dateRange?: { start: string; end: string };
  chartType?: 'line' | 'bar';
}

export function ResponseRateChart({ 
  data, 
  dateRange, 
  chartType = 'line' 
}: ResponseRateChartProps) {
  const normalizeRate = (value?: number | null) => {
    if (typeof value !== 'number' || !Number.isFinite(value)) return undefined;
    if (value > 0 && value <= 1) return Math.round(value * 1000) / 10;
    return value;
  };

  const chartInfo = React.useMemo(() => {
    if (!data || Object.keys(data).length === 0) {
      return { data: [] as Array<Record<string, any>>, xKey: 'date' };
    }

    if (Array.isArray(data)) {
      const normalized = data.map((entry: any) => ({
        date: entry.date ?? entry.timestamp ?? entry.label,
        label: entry.label ?? entry.surveyId ?? entry.id,
        responses: entry.responses ?? entry.count ?? entry.total_responses,
        rate: normalizeRate(entry.rate ?? entry.response_rate ?? entry.completion_rate),
      }));
      return { data: normalized.filter((entry) => entry.date ?? entry.label), xKey: normalized.some((e) => e.date) ? 'date' : 'label' };
    }

    const series = (data as any).series ?? (data as any).timeline ?? (data as any).points ?? (data as any).data;
    if (Array.isArray(series)) {
      const normalized = series.map((entry: any) => ({
        date: entry.date ?? entry.timestamp ?? entry.label,
        label: entry.label ?? entry.surveyId ?? entry.id,
        responses: entry.responses ?? entry.count ?? entry.total_responses,
        rate: normalizeRate(entry.rate ?? entry.response_rate ?? entry.completion_rate),
      }));
      return { data: normalized.filter((entry) => entry.date ?? entry.label), xKey: normalized.some((e) => e.date) ? 'date' : 'label' };
    }

    const entries = Object.entries(data).filter(([, value]) => value && typeof value === 'object');
    const mapped = entries.map(([surveyId, rateData]: [string, any]) => ({
      label: surveyId.substring(0, 8),
      responses: rateData.responses ?? rateData.count ?? rateData.total_responses,
      rate: normalizeRate(rateData.rate ?? rateData.response_rate ?? rateData.completion_rate),
    }));
    return { data: mapped.filter((entry) => entry.responses != null || entry.rate != null), xKey: 'label' };
  }, [data]);

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (active && payload && payload.length) {
      return (
        <div className="bg-white p-3 border rounded-lg shadow-lg">
          <p className="font-medium">{label}</p>
          <p className="text-blue-600">
            {`Responses: ${payload[0].value}`}
          </p>
          {payload[0].payload?.rate != null && (
            <p className="text-green-600">
              {`Rate: ${payload[0].payload.rate}%`}
            </p>
          )}
        </div>
      );
    }
    return null;
  };

  if (!chartInfo.data.length) {
    return (
      <div className="flex h-[300px] items-center justify-center text-sm text-muted-foreground">
        No response-rate data yet.
      </div>
    );
  }

  if (chartType === 'bar') {
    return (
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={chartInfo.data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey={chartInfo.xKey} />
          <YAxis />
          <Tooltip content={<CustomTooltip />} />
          <Bar dataKey="responses" fill="#2563eb" />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={300}>
      <LineChart data={chartInfo.data} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey={chartInfo.xKey} />
        <YAxis />
        <Tooltip content={<CustomTooltip />} />
        <Line 
          type="monotone" 
          dataKey="responses" 
          stroke="#2563eb" 
          strokeWidth={2}
          dot={{ r: 4 }}
        />
        <Line 
          type="monotone" 
          dataKey="rate" 
          stroke="#16a34a" 
          strokeWidth={2}
          dot={{ r: 4 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
