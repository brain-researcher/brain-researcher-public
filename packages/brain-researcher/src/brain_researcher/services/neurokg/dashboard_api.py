"""
Dashboard API for PI monitoring and metrics aggregation
"""

from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
import json

dashboard_bp = Blueprint('dashboard', __name__)

def generate_mock_metrics():
    """Generate dashboard metrics (placeholder data removed)"""
    now = datetime.now()

    # Return empty/minimal data structure
    # In production, this should query real data from Neo4j/database

    # Queue status - will be populated by orchestrator from real job data
    queue_status = {
        'running': 0,
        'queued': 0,
        'completed': 0,
        'failed': 0
    }

    # Cluster status - basic structure, orchestrator will override with real data
    cluster_status = {
        'nodes': {
            'total': 0,
            'active': 0,
            'idle': 0,
            'maintenance': 0
        },
        'cpus': {
            'total': 0,
            'allocated': 0,
            'available': 0
        },
        'memory': {
            'total': 0,
            'allocated': 0,
            'available': 0
        }
    }

    return {
        'timestamp': now.isoformat(),
        'gpuUtilization': [],  # Will be populated by orchestrator from nvidia-smi
        'queueStatus': queue_status,
        'projects': [],  # TODO: Query real projects from Neo4j
        'teamActivity': [],  # TODO: Query real activity from job logs
        'storage': {  # Will be populated by orchestrator from filesystem
            'primary': {'used': 0, 'total': 0, 'percentage': 0},
            'archive': {'used': 0, 'total': 0, 'percentage': 0},
            'scratch': {'used': 0, 'total': 0, 'percentage': 0}
        },
        'outputs': [],  # TODO: Query real outputs from job artifacts
        'clusterStatus': cluster_status
    }

@dashboard_bp.route('/api/dashboard/metrics', methods=['GET'])
def get_dashboard_metrics():
    """Get current dashboard metrics"""
    try:
        metrics = generate_mock_metrics()
        return jsonify(metrics), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/api/dashboard/projects/<project_id>', methods=['GET'])
def get_project_details(project_id):
    """Get detailed information for a specific project"""
    try:
        # Generate mock project details
        project = {
            'id': project_id,
            'name': 'Alzheimer Biomarkers Study',
            'description': 'Multi-modal neuroimaging study investigating early biomarkers of Alzheimer\'s disease',
            'pi': 'Dr. Sarah Chen',
            'team': [
                {'name': 'Dr. Sarah Chen', 'role': 'Principal Investigator'},
                {'name': 'Dr. Mike Zhang', 'role': 'Co-Investigator'},
                {'name': 'Emma Liu', 'role': 'Research Assistant'}
            ],
            'progress': 75,
            'subjects': {
                'total': 120,
                'completed': 90,
                'inProgress': 20,
                'failed': 10
            },
            'pipelines': [
                {'name': 'fMRIPrep', 'version': '23.1.4', 'status': 'active'},
                {'name': 'FreeSurfer', 'version': '7.3.2', 'status': 'active'},
                {'name': 'FSL FEAT', 'version': '6.0.5', 'status': 'completed'}
            ],
            'datasets': [
                {'id': 'ds000114', 'name': 'Motor Task fMRI', 'subjects': 60},
                {'id': 'ds000117', 'name': 'Visual Task fMRI', 'subjects': 60}
            ],
            'timeline': {
                'start': '2025-01-01',
                'end': '2025-06-30',
                'milestones': [
                    {'date': '2025-02-01', 'name': 'Data collection complete', 'status': 'completed'},
                    {'date': '2025-03-15', 'name': 'Preprocessing complete', 'status': 'inProgress'},
                    {'date': '2025-05-01', 'name': 'Statistical analysis', 'status': 'pending'},
                    {'date': '2025-06-30', 'name': 'Final report', 'status': 'pending'}
                ]
            },
            'resources': {
                'storage': {'used': 512, 'allocated': 1024},  # GB
                'compute': {'cpuHours': 1250, 'gpuHours': 450}
            }
        }
        return jsonify(project), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/api/dashboard/activity', methods=['GET'])
def get_activity_log():
    """Get team activity log with pagination"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        # Generate mock activity log
        activities = []
        now = datetime.now()
        
        for i in range(per_page):
            activity_idx = (page - 1) * per_page + i
            activities.append({
                'id': f'act-{activity_idx}',
                'timestamp': (now - timedelta(minutes=activity_idx * 30)).isoformat(),
                'user': random.choice(['Dr. Sarah Chen', 'Prof. Mike Zhang', 'Dr. Emma Liu', 'Dr. Alex Wang']),
                'action': random.choice([
                    'Started preprocessing pipeline',
                    'Completed statistical analysis',
                    'Uploaded new dataset',
                    'Modified analysis parameters',
                    'Exported results'
                ]),
                'type': random.choice(['start', 'complete', 'upload', 'modify', 'export']),
                'details': {
                    'project': random.choice(['proj-alzheimer-2025', 'proj-motor-fmri', 'proj-resting-dmn']),
                    'dataset': random.choice(['ds000114', 'ds000117', 'ds000228'])
                }
            })
        
        return jsonify({
            'activities': activities,
            'page': page,
            'per_page': per_page,
            'total': 100  # Mock total count
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/api/dashboard/resources', methods=['GET'])
def get_resource_status():
    """Get current resource utilization status"""
    try:
        resources = {
            'timestamp': datetime.now().isoformat(),
            'gpu': {
                'devices': [
                    {'id': 0, 'name': 'NVIDIA A100', 'utilization': 85, 'memory': 75, 'temperature': 65},
                    {'id': 1, 'name': 'NVIDIA A100', 'utilization': 72, 'memory': 60, 'temperature': 62},
                    {'id': 2, 'name': 'NVIDIA A100', 'utilization': 45, 'memory': 40, 'temperature': 58},
                    {'id': 3, 'name': 'NVIDIA A100', 'utilization': 90, 'memory': 85, 'temperature': 68}
                ]
            },
            'queue': {
                'jobs': [
                    {'id': 'job-001', 'name': 'fMRIPrep preprocessing', 'status': 'running', 'progress': 65, 'eta': '2h 30m'},
                    {'id': 'job-002', 'name': 'FSL FEAT GLM', 'status': 'running', 'progress': 30, 'eta': '4h 15m'},
                    {'id': 'job-003', 'name': 'FreeSurfer recon-all', 'status': 'queued', 'position': 1},
                    {'id': 'job-004', 'name': 'Connectivity analysis', 'status': 'queued', 'position': 2}
                ]
            },
            'storage': {
                'filesystems': [
                    {'name': 'Primary', 'path': '/data/primary', 'used': 2.4, 'total': 5, 'unit': 'TB'},
                    {'name': 'Archive', 'path': '/data/archive', 'used': 8.1, 'total': 20, 'unit': 'TB'},
                    {'name': 'Scratch', 'path': '/scratch', 'used': 312, 'total': 1024, 'unit': 'GB'}
                ]
            }
        }
        return jsonify(resources), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@dashboard_bp.route('/api/dashboard/summary', methods=['GET'])
def get_dashboard_summary():
    """Get high-level dashboard summary"""
    try:
        summary = {
            'timestamp': datetime.now().isoformat(),
            'overview': {
                'activeProjects': 4,
                'runningJobs': 4,
                'queuedJobs': 7,
                'activeUsers': 5,
                'totalSubjects': 425,
                'completedAnalyses': 156
            },
            'alerts': [
                {'level': 'warning', 'message': 'Primary storage at 48% capacity', 'timestamp': datetime.now().isoformat()},
                {'level': 'info', 'message': 'Scheduled maintenance on GPU node 3 tomorrow', 'timestamp': datetime.now().isoformat()}
            ],
            'recentAchievements': [
                'Completed 100th analysis this month',
                'Published dataset to OpenNeuro',
                'New team member onboarded'
            ]
        }
        return jsonify(summary), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500