{{/*
Expand the name of the chart.
*/}}
{{- define "brain-researcher.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "brain-researcher.fullname" -}}
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
{{- define "brain-researcher.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "brain-researcher.labels" -}}
helm.sh/chart: {{ include "brain-researcher.chart" . }}
{{ include "brain-researcher.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: brain-researcher-platform
{{- end }}

{{/*
Selector labels
*/}}
{{- define "brain-researcher.selectorLabels" -}}
app.kubernetes.io/name: {{ include "brain-researcher.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Component labels for specific services
*/}}
{{- define "brain-researcher.componentLabels" -}}
{{- $component := . -}}
app.kubernetes.io/component: {{ $component }}
{{- end }}

{{/*
Create the name of the service account to use for nginx
*/}}
{{- define "brain-researcher.nginx.serviceAccountName" -}}
{{- if .Values.nginx.serviceAccount.create }}
{{- default (printf "%s-nginx" (include "brain-researcher.fullname" .)) .Values.nginx.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.nginx.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create the name of the service account to use for orchestrator
*/}}
{{- define "brain-researcher.orchestrator.serviceAccountName" -}}
{{- if .Values.orchestrator.serviceAccount.create }}
{{- default (printf "%s-orchestrator" (include "brain-researcher.fullname" .)) .Values.orchestrator.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.orchestrator.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create the name of the service account to use for agent
*/}}
{{- define "brain-researcher.agent.serviceAccountName" -}}
{{- if .Values.agent.serviceAccount.create }}
{{- default (printf "%s-agent" (include "brain-researcher.fullname" .)) .Values.agent.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.agent.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create the name of the service account to use for neurokg
*/}}
{{- define "brain-researcher.neurokg.serviceAccountName" -}}
{{- if .Values.neurokg.serviceAccount.create }}
{{- default (printf "%s-neurokg" (include "brain-researcher.fullname" .)) .Values.neurokg.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.neurokg.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create the name of the service account to use for niclip
*/}}
{{- define "brain-researcher.niclip.serviceAccountName" -}}
{{- if .Values.niclip.serviceAccount.create }}
{{- default (printf "%s-niclip" (include "brain-researcher.fullname" .)) .Values.niclip.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.niclip.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create the name of the service account to use for web-ui
*/}}
{{- define "brain-researcher.webUi.serviceAccountName" -}}
{{- if .Values.webUi.serviceAccount.create }}
{{- default (printf "%s-web-ui" (include "brain-researcher.fullname" .)) .Values.webUi.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.webUi.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Generate fully qualified names for each service
*/}}
{{- define "brain-researcher.nginx.fullname" -}}
{{- printf "%s-nginx" (include "brain-researcher.fullname" .) }}
{{- end }}

{{- define "brain-researcher.orchestrator.fullname" -}}
{{- printf "%s-orchestrator" (include "brain-researcher.fullname" .) }}
{{- end }}

{{- define "brain-researcher.agent.fullname" -}}
{{- printf "%s-agent" (include "brain-researcher.fullname" .) }}
{{- end }}

{{- define "brain-researcher.neurokg.fullname" -}}
{{- printf "%s-neurokg" (include "brain-researcher.fullname" .) }}
{{- end }}

{{- define "brain-researcher.niclip.fullname" -}}
{{- printf "%s-niclip" (include "brain-researcher.fullname" .) }}
{{- end }}

{{- define "brain-researcher.webUi.fullname" -}}
{{- printf "%s-web-ui" (include "brain-researcher.fullname" .) }}
{{- end }}

{{- define "brain-researcher.postgres.fullname" -}}
{{- printf "%s-postgres" (include "brain-researcher.fullname" .) }}
{{- end }}

{{- define "brain-researcher.redis.fullname" -}}
{{- printf "%s-redis" (include "brain-researcher.fullname" .) }}
{{- end }}

{{- define "brain-researcher.prometheus.fullname" -}}
{{- printf "%s-prometheus" (include "brain-researcher.fullname" .) }}
{{- end }}

{{- define "brain-researcher.grafana.fullname" -}}
{{- printf "%s-grafana" (include "brain-researcher.fullname" .) }}
{{- end }}

{{/*
Generate service names
*/}}
{{- define "brain-researcher.nginx.serviceName" -}}
{{- printf "%s-service" (include "brain-researcher.nginx.fullname" .) }}
{{- end }}

{{- define "brain-researcher.orchestrator.serviceName" -}}
{{- include "brain-researcher.orchestrator.fullname" . }}
{{- end }}

{{- define "brain-researcher.agent.serviceName" -}}
{{- printf "%s-service" (include "brain-researcher.agent.fullname" .) }}
{{- end }}

{{- define "brain-researcher.neurokg.serviceName" -}}
{{- printf "%s-service" (include "brain-researcher.neurokg.fullname" .) }}
{{- end }}

{{- define "brain-researcher.niclip.serviceName" -}}
{{- printf "%s-service" (include "brain-researcher.niclip.fullname" .) }}
{{- end }}

{{- define "brain-researcher.webUi.serviceName" -}}
{{- printf "%s-service" (include "brain-researcher.webUi.fullname" .) }}
{{- end }}

{{- define "brain-researcher.postgres.serviceName" -}}
{{- printf "%s-service" (include "brain-researcher.postgres.fullname" .) }}
{{- end }}

{{- define "brain-researcher.redis.serviceName" -}}
{{- printf "%s-service" (include "brain-researcher.redis.fullname" .) }}
{{- end }}

{{- define "brain-researcher.prometheus.serviceName" -}}
{{- printf "%s-service" (include "brain-researcher.prometheus.fullname" .) }}
{{- end }}

{{- define "brain-researcher.grafana.serviceName" -}}
{{- printf "%s-service" (include "brain-researcher.grafana.fullname" .) }}
{{- end }}

{{/*
Generate namespace names
*/}}
{{- define "brain-researcher.coreNamespace" -}}
{{- .Values.namespaces.core | default "brain-researcher-core" }}
{{- end }}

{{- define "brain-researcher.dataNamespace" -}}
{{- .Values.namespaces.data | default "brain-researcher-data" }}
{{- end }}

{{- define "brain-researcher.monitoringNamespace" -}}
{{- .Values.namespaces.monitoring | default "brain-researcher-monitoring" }}
{{- end }}

{{/*
Generate ConfigMap names
*/}}
{{- define "brain-researcher.nginx.configMapName" -}}
{{- printf "%s-config" (include "brain-researcher.nginx.fullname" .) }}
{{- end }}

{{- define "brain-researcher.orchestrator.configMapName" -}}
{{- printf "%s-config" (include "brain-researcher.orchestrator.fullname" .) }}
{{- end }}

{{- define "brain-researcher.agent.configMapName" -}}
{{- printf "%s-config" (include "brain-researcher.agent.fullname" .) }}
{{- end }}

{{- define "brain-researcher.neurokg.configMapName" -}}
{{- printf "%s-config" (include "brain-researcher.neurokg.fullname" .) }}
{{- end }}

{{- define "brain-researcher.niclip.configMapName" -}}
{{- printf "%s-config" (include "brain-researcher.niclip.fullname" .) }}
{{- end }}

{{- define "brain-researcher.webUi.configMapName" -}}
{{- printf "%s-config" (include "brain-researcher.webUi.fullname" .) }}
{{- end }}

{{/*
Generate Secret names
*/}}
{{- define "brain-researcher.llmApiKeys.secretName" -}}
{{- printf "%s-llm-api-keys" (include "brain-researcher.fullname" .) }}
{{- end }}

{{- define "brain-researcher.databaseCredentials.secretName" -}}
{{- printf "%s-database-credentials" (include "brain-researcher.fullname" .) }}
{{- end }}

{{- define "brain-researcher.jwtSecrets.secretName" -}}
{{- printf "%s-jwt-secrets" (include "brain-researcher.fullname" .) }}
{{- end }}

{{- define "brain-researcher.tlsCertificates.secretName" -}}
{{- printf "%s-tls-certificates" (include "brain-researcher.fullname" .) }}
{{- end }}

{{- define "brain-researcher.oauthCredentials.secretName" -}}
{{- printf "%s-oauth-credentials" (include "brain-researcher.fullname" .) }}
{{- end }}

{{- define "brain-researcher.monitoringCredentials.secretName" -}}
{{- printf "%s-monitoring-credentials" (include "brain-researcher.fullname" .) }}
{{- end }}

{{- define "brain-researcher.externalServices.secretName" -}}
{{- printf "%s-external-services" (include "brain-researcher.fullname" .) }}
{{- end }}

{{/*
Generate PVC names
*/}}
{{- define "brain-researcher.neurokg.vectorCachePvcName" -}}
{{- printf "%s-vector-cache" (include "brain-researcher.neurokg.fullname" .) }}
{{- end }}

{{- define "brain-researcher.agent.sessionPvcName" -}}
{{- printf "%s-session-storage" (include "brain-researcher.agent.fullname" .) }}
{{- end }}

{{- define "brain-researcher.agent.logsPvcName" -}}
{{- printf "%s-logs-storage" (include "brain-researcher.agent.fullname" .) }}
{{- end }}

{{- define "brain-researcher.niclip.modelPvcName" -}}
{{- printf "%s-model-storage" (include "brain-researcher.niclip.fullname" .) }}
{{- end }}

{{- define "brain-researcher.niclip.dataCachePvcName" -}}
{{- printf "%s-data-cache" (include "brain-researcher.niclip.fullname" .) }}
{{- end }}

{{- define "brain-researcher.postgres.dataPvcName" -}}
{{- printf "%s-data-storage" (include "brain-researcher.postgres.fullname" .) }}
{{- end }}

{{- define "brain-researcher.redis.dataPvcName" -}}
{{- printf "%s-data-storage" (include "brain-researcher.redis.fullname" .) }}
{{- end }}

{{- define "brain-researcher.sharedDataPvcName" -}}
{{- printf "%s-shared-data-storage" (include "brain-researcher.fullname" .) }}
{{- end }}

{{/*
Generate image pull secrets
*/}}
{{- define "brain-researcher.imagePullSecrets" -}}
{{- if .Values.global.imagePullSecrets }}
imagePullSecrets:
{{- range .Values.global.imagePullSecrets }}
  {{- /* Accept either a string (\"regcred\") or an object ({name: regcred}). */}}
  - name: {{- if kindIs "string" . -}}{{ . }}{{- else -}}{{ .name }}{{- end }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Generate pod security context
*/}}
{{- define "brain-researcher.podSecurityContext" -}}
{{- if .Values.global.podSecurityContext }}
securityContext:
  {{- toYaml .Values.global.podSecurityContext | nindent 2 }}
{{- end }}
{{- end }}

{{/*
Generate container security context
*/}}
{{- define "brain-researcher.securityContext" -}}
{{- if .Values.global.securityContext }}
securityContext:
  {{- toYaml .Values.global.securityContext | nindent 2 }}
{{- end }}
{{- end }}

{{/*
Create the name of the service account to use (Global)
*/}}
{{- define "brain-researcher.serviceAccountName" -}}
{{- if .Values.serviceAccount -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "brain-researcher.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- else -}}
default
{{- end -}}
{{- end -}}

{{/*
Generate node selector
*/}}
{{- define "brain-researcher.nodeSelector" -}}
{{- if .Values.global.nodeSelector }}
nodeSelector:
  {{- toYaml .Values.global.nodeSelector | nindent 2 }}
{{- end }}
{{- end }}

{{/*
Generate tolerations
*/}}
{{- define "brain-researcher.tolerations" -}}
{{- if .Values.global.tolerations }}
tolerations:
  {{- toYaml .Values.global.tolerations | nindent 2 }}
{{- end }}
{{- end }}

{{/*
Generate affinity
*/}}
{{- define "brain-researcher.affinity" -}}
{{- if .Values.global.affinity }}
affinity:
  {{- toYaml .Values.global.affinity | nindent 2 }}
{{- end }}
{{- end }}

{{/*
Validate required values
*/}}
{{- define "brain-researcher.validateValues" -}}
{{- if not .Values.global.domain }}
{{- fail "global.domain is required" }}
{{- end }}
{{- if and .Values.ingress.enabled (not .Values.ingress.hosts) }}
{{- fail "ingress.hosts is required when ingress is enabled" }}
{{- end }}
{{- end }}

{{/*
Generate resource limits and requests
*/}}
{{- define "brain-researcher.resources" -}}
{{- $resources := . -}}
{{- if $resources }}
resources:
  {{- if $resources.limits }}
  limits:
    {{- if $resources.limits.cpu }}
    cpu: {{ $resources.limits.cpu }}
    {{- end }}
    {{- if $resources.limits.memory }}
    memory: {{ $resources.limits.memory }}
    {{- end }}
    {{- if $resources.limits.gpu }}
    nvidia.com/gpu: {{ $resources.limits.gpu }}
    {{- end }}
  {{- end }}
  {{- if $resources.requests }}
  requests:
    {{- if $resources.requests.cpu }}
    cpu: {{ $resources.requests.cpu }}
    {{- end }}
    {{- if $resources.requests.memory }}
    memory: {{ $resources.requests.memory }}
    {{- end }}
  {{- end }}
{{- end }}
{{- end }}
