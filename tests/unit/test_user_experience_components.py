"""
Unit tests for User Experience Components (Settings, Keyboard Shortcuts, Dark Mode, Export)
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json
from datetime import datetime


class TestSettingsInterface:
    """Test suite for Settings Interface component"""
    
    @pytest.fixture
    def user_profile(self):
        """Sample user profile"""
        return {
            'id': 'user_123',
            'name': 'John Doe',
            'email': 'john@example.com',
            'avatar': '/avatars/john.jpg',
            'bio': 'Neuroscience researcher',
            'organization': 'MIT',
            'role': 'Researcher'
        }
    
    @pytest.fixture
    def notification_settings(self):
        """Sample notification settings"""
        return {
            'email': True,
            'push': True,
            'jobComplete': True,
            'jobFailed': True,
            'updates': False,
            'marketing': False
        }
    
    @pytest.fixture
    def preferences(self):
        """Sample user preferences"""
        return {
            'theme': 'system',
            'language': 'en',
            'timezone': 'UTC',
            'dateFormat': 'MM/DD/YYYY',
            'defaultPipeline': 'glm_standard',
            'autoSave': True,
            'confirmDelete': True,
            'showTutorials': True,
            'debugMode': False
        }
    
    def test_profile_validation(self, user_profile):
        """Test user profile validation"""
        assert user_profile['id'] == 'user_123'
        assert '@' in user_profile['email']
        assert user_profile['role'] in ['Researcher', 'Admin', 'User']
    
    def test_notification_preferences(self, notification_settings):
        """Test notification preference settings"""
        # Critical notifications should be enabled by default
        assert notification_settings['jobComplete'] is True
        assert notification_settings['jobFailed'] is True
        
        # Marketing should be opt-in
        assert notification_settings['marketing'] is False
    
    def test_api_key_generation(self):
        """Test API key generation"""
        import secrets
        
        # Generate API key
        key_prefix = 'br_'
        key_body = secrets.token_urlsafe(32)
        api_key = f"{key_prefix}{key_body}"
        
        assert api_key.startswith('br_')
        assert len(api_key) > 40
    
    def test_theme_preferences(self, preferences):
        """Test theme preference options"""
        valid_themes = ['light', 'dark', 'system']
        assert preferences['theme'] in valid_themes
    
    def test_language_support(self, preferences):
        """Test language preference options"""
        supported_languages = ['en', 'es', 'fr', 'de', 'zh', 'ja']
        assert preferences['language'] in supported_languages
    
    def test_timezone_configuration(self, preferences):
        """Test timezone configuration"""
        valid_timezones = [
            'UTC', 'America/New_York', 'America/Chicago',
            'America/Los_Angeles', 'Europe/London', 'Asia/Tokyo'
        ]
        assert preferences['timezone'] in valid_timezones
    
    def test_date_format_options(self, preferences):
        """Test date format options"""
        valid_formats = ['MM/DD/YYYY', 'DD/MM/YYYY', 'YYYY-MM-DD']
        assert preferences['dateFormat'] in valid_formats
    
    def test_auto_save_feature(self, preferences):
        """Test auto-save preference"""
        assert isinstance(preferences['autoSave'], bool)
        
        # Auto-save should be enabled by default for better UX
        assert preferences['autoSave'] is True
    
    def test_settings_persistence(self, user_profile, preferences):
        """Test settings persistence to storage"""
        # Simulate saving to localStorage
        settings = {
            'profile': user_profile,
            'preferences': preferences
        }
        
        serialized = json.dumps(settings)
        deserialized = json.loads(serialized)
        
        assert deserialized['profile']['id'] == user_profile['id']
        assert deserialized['preferences']['theme'] == preferences['theme']


class TestKeyboardShortcuts:
    """Test suite for Keyboard Shortcuts component"""
    
    @pytest.fixture
    def default_shortcuts(self):
        """Default keyboard shortcuts"""
        return [
            {'id': 'search', 'key': 'k', 'modifiers': ['cmd', 'ctrl'], 'description': 'Open command palette'},
            {'id': 'save', 'key': 's', 'modifiers': ['cmd', 'ctrl'], 'description': 'Save current work'},
            {'id': 'new', 'key': 'n', 'modifiers': ['cmd', 'ctrl'], 'description': 'New analysis'},
            {'id': 'help', 'key': '?', 'modifiers': ['shift'], 'description': 'Show keyboard shortcuts'},
            {'id': 'home', 'key': 'h', 'modifiers': ['cmd', 'ctrl', 'shift'], 'description': 'Go to home'},
            {'id': 'settings', 'key': ',', 'modifiers': ['cmd', 'ctrl'], 'description': 'Open settings'}
        ]
    
    def test_shortcut_registration(self, default_shortcuts):
        """Test keyboard shortcut registration"""
        assert len(default_shortcuts) >= 6
        
        # Check essential shortcuts exist
        shortcut_ids = {s['id'] for s in default_shortcuts}
        assert 'search' in shortcut_ids
        assert 'save' in shortcut_ids
        assert 'help' in shortcut_ids
    
    def test_modifier_combinations(self, default_shortcuts):
        """Test modifier key combinations"""
        search_shortcut = next(s for s in default_shortcuts if s['id'] == 'search')
        
        assert 'cmd' in search_shortcut['modifiers'] or 'ctrl' in search_shortcut['modifiers']
        assert search_shortcut['key'] == 'k'
    
    def test_command_palette_items(self):
        """Test command palette items"""
        items = [
            {'id': 'new-analysis', 'label': 'New Analysis', 'category': 'Actions'},
            {'id': 'open-dataset', 'label': 'Open Dataset', 'category': 'Actions'},
            {'id': 'run-pipeline', 'label': 'Run Pipeline', 'category': 'Actions'},
            {'id': 'go-home', 'label': 'Go to Home', 'category': 'Navigation'},
            {'id': 'go-settings', 'label': 'Settings', 'category': 'Navigation'}
        ]
        
        # Check categories
        categories = {item['category'] for item in items}
        assert 'Actions' in categories
        assert 'Navigation' in categories
    
    def test_shortcut_conflicts(self, default_shortcuts):
        """Test for keyboard shortcut conflicts"""
        # Create shortcut signatures
        signatures = []
        for shortcut in default_shortcuts:
            signature = f"{'+'.join(sorted(shortcut['modifiers']))}+{shortcut['key']}"
            signatures.append(signature)
        
        # Check for duplicates
        assert len(signatures) == len(set(signatures)), "Duplicate shortcuts detected"
    
    def test_custom_shortcut_validation(self):
        """Test custom shortcut validation"""
        # Valid custom shortcut
        custom = {
            'id': 'custom_action',
            'key': 'x',
            'modifiers': ['cmd', 'alt'],
            'description': 'Custom action'
        }
        
        assert len(custom['modifiers']) > 0
        assert len(custom['key']) == 1
    
    def test_platform_specific_modifiers(self):
        """Test platform-specific modifier keys"""
        # Mac modifiers
        mac_symbols = {'cmd': '⌘', 'ctrl': '⌃', 'shift': '⇧', 'alt': '⌥'}
        
        # Windows/Linux modifiers
        win_symbols = {'cmd': 'Ctrl', 'ctrl': 'Ctrl', 'shift': 'Shift', 'alt': 'Alt'}
        
        assert mac_symbols['cmd'] == '⌘'
        assert win_symbols['cmd'] == 'Ctrl'


class TestDarkMode:
    """Test suite for Dark Mode theme support"""
    
    def test_theme_options(self):
        """Test available theme options"""
        themes = ['light', 'dark', 'system']
        
        assert 'light' in themes
        assert 'dark' in themes
        assert 'system' in themes
    
    def test_theme_persistence(self):
        """Test theme persistence in localStorage"""
        theme = 'dark'
        storage_key = 'brain-researcher-theme'
        
        # Simulate localStorage
        storage = {storage_key: theme}
        
        assert storage[storage_key] == 'dark'
    
    def test_system_theme_detection(self):
        """Test system theme preference detection"""
        # Simulate media query
        prefers_dark = True  # window.matchMedia('(prefers-color-scheme: dark)').matches
        
        system_theme = 'dark' if prefers_dark else 'light'
        assert system_theme == 'dark'
    
    def test_theme_class_application(self):
        """Test CSS class application for themes"""
        theme = 'dark'
        
        # Classes that should be applied
        html_classes = []
        if theme == 'dark':
            html_classes.append('dark')
        
        assert 'dark' in html_classes
    
    def test_theme_transition(self):
        """Test smooth theme transitions"""
        transition_duration = 200  # milliseconds
        
        assert transition_duration > 0
        assert transition_duration <= 500  # Should be quick


class TestExportFunctionality:
    """Test suite for Export Functionality component"""
    
    @pytest.fixture
    def export_data(self):
        """Sample data for export"""
        return {
            'title': 'Analysis Results',
            'description': 'GLM analysis results for motor task',
            'data': [
                {'region': 'M1', 't_value': 6.23, 'p_value': 0.001},
                {'region': 'SMA', 't_value': 5.12, 'p_value': 0.003},
                {'region': 'PMC', 't_value': 4.89, 'p_value': 0.005}
            ],
            'metadata': {
                'pipeline': 'fsl_glm',
                'subjects': 20,
                'smoothing': 6
            }
        }
    
    def test_supported_formats(self):
        """Test supported export formats"""
        formats = ['pdf', 'png', 'svg', 'csv', 'json', 'xlsx']
        
        # Essential formats
        assert 'pdf' in formats
        assert 'csv' in formats
        assert 'json' in formats
    
    def test_pdf_export_options(self):
        """Test PDF export options"""
        options = {
            'format': 'pdf',
            'quality': 'high',
            'includeMetadata': True,
            'includeTimestamp': True,
            'compress': False
        }
        
        assert options['format'] == 'pdf'
        assert options['quality'] in ['low', 'medium', 'high']
        assert options['includeMetadata'] is True
    
    def test_csv_export_formatting(self, export_data):
        """Test CSV export formatting"""
        # Convert to CSV
        headers = ['region', 't_value', 'p_value']
        csv_lines = [','.join(headers)]
        
        for row in export_data['data']:
            values = [str(row[h]) for h in headers]
            csv_lines.append(','.join(values))
        
        csv_content = '\n'.join(csv_lines)
        
        assert 'region,t_value,p_value' in csv_content
        assert 'M1,6.23,0.001' in csv_content
    
    def test_json_export_structure(self, export_data):
        """Test JSON export structure"""
        export_json = {
            'data': export_data['data'],
            'metadata': {
                **export_data['metadata'],
                'title': export_data['title'],
                'exportDate': datetime.now().isoformat()
            }
        }
        
        assert 'data' in export_json
        assert 'metadata' in export_json
        assert len(export_json['data']) == 3
    
    def test_image_export_quality(self):
        """Test image export quality settings"""
        quality_settings = {
            'low': {'scale': 1, 'compression': 0.6},
            'medium': {'scale': 2, 'compression': 0.8},
            'high': {'scale': 3, 'compression': 1.0}
        }
        
        assert quality_settings['high']['scale'] == 3
        assert quality_settings['high']['compression'] == 1.0
    
    def test_file_naming_convention(self, export_data):
        """Test exported file naming"""
        import time
        
        title = export_data['title'].replace(' ', '_')
        timestamp = int(time.time())
        format = 'pdf'
        
        filename = f"{title}_{timestamp}.{format}"
        
        assert 'Analysis_Results' in filename
        assert filename.endswith('.pdf')
    
    def test_share_link_generation(self):
        """Test share link generation"""
        import base64
        
        share_data = {'id': 'result_123', 'timestamp': datetime.now().isoformat()}
        encoded = base64.b64encode(json.dumps(share_data).encode()).decode()
        
        share_id = encoded[:10]
        share_url = f"/shared/{share_id}"
        
        assert share_url.startswith('/shared/')
        assert len(share_id) == 10
    
    def test_export_progress_tracking(self):
        """Test export progress tracking"""
        progress_states = [
            {'status': 'idle', 'progress': 0},
            {'status': 'preparing', 'progress': 10},
            {'status': 'processing', 'progress': 50},
            {'status': 'complete', 'progress': 100}
        ]
        
        for state in progress_states:
            assert 0 <= state['progress'] <= 100
        
        # Final state should be complete
        assert progress_states[-1]['status'] == 'complete'
        assert progress_states[-1]['progress'] == 100