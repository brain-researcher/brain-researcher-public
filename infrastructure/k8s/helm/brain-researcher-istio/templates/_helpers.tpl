{{/*
Expand the name of the chart.
*/}}
{{- define "brain-researcher-istio.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "brain-researcher-istio.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "brain-researcher-istio.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "brain-researcher-istio.labels" -}}
helm.sh/chart: {{ include "brain-researcher-istio.chart" . }}
{{ include "brain-researcher-istio.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
project: {{ .Values.labels.project | default "brain-researcher" }}
component: {{ .Values.labels.component | default "service-mesh" }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "brain-researcher-istio.selectorLabels" -}}
app.kubernetes.io/name: {{ include "brain-researcher-istio.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Brain Researcher namespace
*/}}
{{- define "brain-researcher-istio.namespace" -}}
{{- .Values.global.brainResearcher.namespace | default "brain-researcher" }}
{{- end }}

{{/*
Istio namespace
*/}}
{{- define "brain-researcher-istio.istioNamespace" -}}
{{- .Values.global.istioNamespace | default "istio-system" }}
{{- end }}

{{/*
Mesh ID
*/}}
{{- define "brain-researcher-istio.meshId" -}}
{{- .Values.global.brainResearcher.meshId | default "brain-researcher-mesh" }}
{{- end }}

{{/*
Service account name for service
*/}}
{{- define "brain-researcher-istio.serviceAccountName" -}}
{{- printf "%s-service-account" . }}
{{- end }}

{{/*
Generate destination rule spec
*/}}
{{- define "brain-researcher-istio.destinationRuleSpec" -}}
host: {{ printf "%s.%s.svc.cluster.local" .serviceName (include "brain-researcher-istio.namespace" .) }}
trafficPolicy:
  loadBalancer:
    simple: {{ .trafficPolicy.loadBalancer | default "ROUND_ROBIN" }}
  {{- if .trafficPolicy.connectionPool }}
  connectionPool:
    {{- if .trafficPolicy.connectionPool.tcp }}
    tcp:
      {{- toYaml .trafficPolicy.connectionPool.tcp | nindent 6 }}
    {{- end }}
    {{- if .trafficPolicy.connectionPool.http }}
    http:
      {{- toYaml .trafficPolicy.connectionPool.http | nindent 6 }}
    {{- end }}
  {{- end }}
  {{- if .trafficPolicy.outlierDetection }}
  outlierDetection:
    {{- toYaml .trafficPolicy.outlierDetection | nindent 4 }}
  {{- end }}
  tls:
    mode: ISTIO_MUTUAL
{{- end }}

{{/*
Generate peer authentication spec
*/}}
{{- define "brain-researcher-istio.peerAuthSpec" -}}
selector:
  matchLabels:
    app: {{ .serviceName }}
mtls:
  mode: {{ .security.mtlsMode | default "STRICT" }}
{{- end }}

{{/*
Generate authorization policy spec
*/}}
{{- define "brain-researcher-istio.authPolicySpec" -}}
selector:
  matchLabels:
    app: {{ .serviceName }}
{{- if .security.authorizationRules }}
rules:
{{- toYaml .security.authorizationRules | nindent 0 }}
{{- end }}
{{- end }}

{{/*
Generate virtual service spec
*/}}
{{- define "brain-researcher-istio.virtualServiceSpec" -}}
hosts:
{{- range .hosts }}
- {{ . | quote }}
{{- end }}
gateways:
- {{ include "brain-researcher-istio.name" $ }}-gateway
http:
{{- range .routes }}
- match:
  {{- range .match }}
  - uri:
      {{- toYaml . | nindent 6 }}
  {{- end }}
  route:
  {{- range .route }}
  - destination:
      {{- toYaml . | nindent 6 }}
  {{- end }}
  {{- if .timeout }}
  timeout: {{ .timeout }}
  {{- end }}
  {{- if .retries }}
  retries:
    {{- toYaml .retries | nindent 4 }}
  {{- end }}
{{- end }}
{{- end }}

{{/*
Generate custom resource name
*/}}
{{- define "brain-researcher-istio.resourceName" -}}
{{- printf "%s-%s" . (include "brain-researcher-istio.name" $) }}
{{- end }}

{{/*
Generate telemetry configuration
*/}}
{{- define "brain-researcher-istio.telemetrySpec" -}}
{{- if .Values.telemetry.metrics.enabled }}
metrics:
- providers:
  - name: prometheus
{{- if .Values.telemetry.metrics.prometheus.customMetrics }}
- overrides:
  {{- range .Values.telemetry.metrics.prometheus.customMetrics }}
  - match:
      metric: {{ .name }}
    {{- if .dimensions }}
    tagOverrides:
      {{- range $key, $value := .dimensions }}
      {{ $key }}:
        value: {{ $value | quote }}
      {{- end }}
    {{- end }}
    {{- if .buckets }}
    histogram:
      buckets: {{ .buckets }}
    {{- end }}
  {{- end }}
{{- end }}
{{- end }}
{{- if .Values.telemetry.tracing.enabled }}
tracing:
- providers:
  - name: jaeger
{{- if .Values.telemetry.tracing.customTags }}
- customTags:
  {{- range $key, $value := .Values.telemetry.tracing.customTags }}
  {{ $key }}:
    {{- toYaml $value | nindent 4 }}
  {{- end }}
{{- end }}
{{- end }}
{{- if .Values.telemetry.accessLogging.enabled }}
accessLogging:
- providers:
  - name: envoy
{{- if .Values.telemetry.accessLogging.format }}
- format:
    text: |
{{ .Values.telemetry.accessLogging.format | indent 6 }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Generate gateway ports
*/}}
{{- define "brain-researcher-istio.gatewayPorts" -}}
- port:
    number: {{ .Values.gateways.main.ports.http }}
    name: http
    protocol: HTTP
  hosts:
  - "*"
  {{- if .Values.gateways.main.tls.enabled }}
  tls:
    httpsRedirect: true
- port:
    number: {{ .Values.gateways.main.ports.https }}
    name: https
    protocol: HTTPS
  tls:
    mode: SIMPLE
    credentialName: {{ .Values.gateways.main.tls.credentialName }}
  hosts:
  {{- range .Values.gateways.main.hosts }}
  - {{ . | quote }}
  {{- end }}
  {{- end }}
{{- range $name, $port := (omit .Values.gateways.main.ports "http" "https") }}
- port:
    number: {{ $port }}
    name: {{ $name }}
    protocol: HTTP
  hosts:
  {{- range $.Values.gateways.main.hosts }}
  - {{ . | quote }}
  {{- end }}
{{- end }}
{{- end }}

{{/*
Validate configuration
*/}}
{{- define "brain-researcher-istio.validate" -}}
{{- if not .Values.global.brainResearcher.namespace }}
{{- fail "global.brainResearcher.namespace is required" }}
{{- end }}
{{- if not .Values.global.brainResearcher.meshId }}
{{- fail "global.brainResearcher.meshId is required" }}
{{- end }}
{{- end }}