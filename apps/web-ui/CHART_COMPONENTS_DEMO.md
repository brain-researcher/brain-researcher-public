# 📊 Chart Components Library - Live Demo

## 🎉 Access the Live Demo!

Open your browser and navigate to: **http://localhost:3002/charts**

## What You'll See:

### 1. 📈 **BOLD Time Series Chart**
- **Interactive Line Chart** showing fMRI BOLD signals over time
- 3 different brain networks (DMN, Executive, Salience) in different colors
- **Zoom & Brush control** at the bottom to focus on specific time ranges
- Hover over lines to see exact values
- Export menu (⋮) in top-right corner

### 2. 📊 **Regional Brain Activation Bar Chart**
- Comparison of activation levels across 6 brain regions
- Task activation (green) vs Baseline (gray) bars
- Clean labels and grid for easy reading
- Tooltip shows exact beta values on hover

### 3. 🔥 **Functional Connectivity Heatmap**
- 7x7 correlation matrix between brain networks
- Cool color scheme (blue to red) showing correlation strength
- Interactive tooltips showing exact correlation values
- Color legend on the right side
- Networks: DMN, FPN, VAN, DAN, SMN, VIS, AUD

### 4. 🔵 **Brain Volume vs Age Scatter Plot**
- Shows relationship between age and brain volume
- Points colored by cognitive score (green=high, blue=medium, red=low)
- Automatic trendline calculation
- Bubble size represents cognitive score

### 5. 👥 **Group Comparison Scatter Plot**
- Three groups: Control, MCI (Mild Cognitive Impairment), AD (Alzheimer's)
- Different colors for each group
- Normal range highlighted with green background
- Shows hippocampal volume vs memory performance

## 🎨 Features to Try:

### Export Options (Available on Every Chart):
1. Click the **⋮** menu in the top-right of any chart
2. Choose export format:
   - **PNG** - High-resolution image for publications
   - **SVG** - Vector format for editing
   - **CSV** - Raw data for analysis

### Interactive Features:
- **Hover** over any data point for detailed information
- **Brush** control on time series chart - drag to zoom
- **Responsive** - resize your browser window to see charts adapt
- **Dark Mode Compatible** - works with system theme

## 🚀 Quick Test Commands:

```bash
# The dev server should already be running at http://localhost:3002
# If not, run:
cd apps/web-ui
npm run dev -- --port 3002

# Then open in browser:
# http://localhost:3002/charts
```

## 📝 Sample Data Used:

1. **Time Series**: 100 time points (TR=2s) with simulated BOLD signals
2. **Bar Chart**: 6 brain regions with activation values
3. **Heatmap**: 7 resting-state networks with correlation values
4. **Scatter Plot**: 50 subjects with age, brain volume, and cognitive scores
5. **Group Comparison**: 60 subjects (20 per group) with hippocampal volumes

## 🎯 Ready for Integration:

These components are now ready to be used in:
- **NEURO-18**: PI Dashboard Layout
- Analysis result visualizations
- Real-time monitoring displays
- Publication-ready figures

## 🔧 Component Usage Example:

```tsx
import { LineChart, BarChart, Heatmap, ScatterPlot } from '@/components/charts'

// Use in your component
<LineChart
  data={yourData}
  lines={[
    { dataKey: 'roi1', name: 'Region 1', color: '#8b5cf6' }
  ]}
  xAxisKey="time"
  xAxisLabel="Time (s)"
  yAxisLabel="BOLD Signal"
/>
```

---

**Navigate to http://localhost:3002/charts to see all charts in action!** 🎉
