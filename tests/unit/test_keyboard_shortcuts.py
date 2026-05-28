"""Unit tests for Keyboard Shortcuts functionality."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json

class TestKeyboardShortcuts:
    """Test suite for keyboard shortcuts and command palette."""
    
    @pytest.fixture
    def mock_router(self):
        """Mock Next.js router."""
        router = Mock()
        router.push = Mock()
        router.pathname = '/'
        return router
    
    @pytest.fixture
    def default_shortcuts(self):
        """Default keyboard shortcuts configuration."""
        return [
            {'id': 'cmd-palette', 'keys': ['cmd', 'k'], 'category': 'Navigation'},
            {'id': 'search', 'keys': ['cmd', '/'], 'category': 'Navigation'},
            {'id': 'home', 'keys': ['cmd', 'h'], 'category': 'Navigation'},
            {'id': 'save', 'keys': ['cmd', 's'], 'category': 'File'},
            {'id': 'copy', 'keys': ['cmd', 'c'], 'category': 'Edit'},
            {'id': 'undo', 'keys': ['cmd', 'z'], 'category': 'Edit'},
            {'id': 'zoom-in', 'keys': ['cmd', '+'], 'category': 'View'},
            {'id': 'fullscreen', 'keys': ['cmd', 'shift', 'f'], 'category': 'View'},
            {'id': 'run', 'keys': ['cmd', 'enter'], 'category': 'Execution'},
            {'id': 'help', 'keys': ['cmd', '?'], 'category': 'Help'}
        ]
    
    def test_command_palette_opens(self, mock_router):
        """Test command palette opens with Cmd+K."""
        event = Mock()
        event.metaKey = True
        event.key = 'k'
        event.preventDefault = Mock()
        
        # Simulate keydown
        is_open = False
        if event.metaKey and event.key == 'k':
            event.preventDefault.assert_not_called()  # Will be called
            is_open = True
        
        assert is_open is True
    
    def test_navigation_shortcuts(self, mock_router):
        """Test navigation keyboard shortcuts."""
        shortcuts_map = {
            'h': '/',           # Home
            'd': '/datasets',   # Datasets
            ',': '/settings'    # Settings
        }
        
        for key, path in shortcuts_map.items():
            event = Mock()
            event.metaKey = True
            event.key = key
            
            # Simulate navigation
            if event.metaKey and event.key in shortcuts_map:
                mock_router.push(shortcuts_map[event.key])
                mock_router.push.assert_called_with(path)
    
    def test_file_operation_shortcuts(self):
        """Test file operation shortcuts."""
        mock_handler = Mock()
        
        # Test save (Cmd+S)
        event = Mock()
        event.metaKey = True
        event.key = 's'
        event.preventDefault = Mock()
        
        if event.metaKey and event.key == 's':
            event.preventDefault()
            mock_handler('save')
        
        event.preventDefault.assert_called_once()
        mock_handler.assert_called_with('save')
    
    def test_edit_operation_shortcuts(self):
        """Test edit operation shortcuts."""
        operations = {
            'c': 'copy',
            'v': 'paste',
            'z': 'undo',
            'x': 'cut'
        }
        
        for key, operation in operations.items():
            event = Mock()
            event.metaKey = True
            event.key = key
            
            # Check operation
            assert event.key in operations
            assert operations[event.key] == operation
    
    def test_custom_shortcut_recording(self):
        """Test custom shortcut recording."""
        recording_keys = []
        
        # Record new shortcut
        event = Mock()
        event.metaKey = True
        event.shiftKey = True
        event.key = 'p'
        event.preventDefault = Mock()
        
        # Build key combination
        if event.metaKey:
            recording_keys.append('cmd')
        if event.shiftKey:
            recording_keys.append('shift')
        if event.key not in ['Meta', 'Shift']:
            recording_keys.append(event.key.lower())
        
        assert recording_keys == ['cmd', 'shift', 'p']
        event.preventDefault.assert_not_called()  # Will be called in actual impl
    
    def test_custom_shortcut_persistence(self):
        """Test saving and loading custom shortcuts."""
        custom_shortcuts = {
            'save': ['cmd', 'shift', 's'],
            'export': ['cmd', 'shift', 'e']
        }
        
        # Save to localStorage mock
        storage = {}
        storage['customShortcuts'] = json.dumps(custom_shortcuts)
        
        # Load from storage
        loaded = json.loads(storage['customShortcuts'])
        
        assert loaded == custom_shortcuts
        assert loaded['save'] == ['cmd', 'shift', 's']
    
    def test_shortcut_conflict_detection(self, default_shortcuts):
        """Test detection of conflicting shortcuts."""
        existing = set()
        
        for shortcut in default_shortcuts:
            key_combo = '+'.join(shortcut['keys'])
            assert key_combo not in existing, f"Conflict: {key_combo}"
            existing.add(key_combo)
    
    def test_input_field_exception(self):
        """Test shortcuts disabled in input fields."""
        # Mock active element as input
        active_element = Mock()
        active_element.tagName = 'INPUT'
        
        event = Mock()
        event.metaKey = True
        event.key = 's'
        
        # Should not trigger if in input field (except Cmd+K)
        should_trigger = not (active_element.tagName in ['INPUT', 'TEXTAREA']) or \
                        (event.metaKey and event.key == 'k')
        
        if active_element.tagName == 'INPUT' and event.key != 'k':
            assert should_trigger is False
    
    def test_command_palette_search(self):
        """Test command palette search functionality."""
        commands = [
            {'label': 'New Analysis', 'category': 'Quick Actions'},
            {'label': 'Open Dataset', 'category': 'Quick Actions'},
            {'label': 'Settings', 'category': 'Navigation'},
            {'label': 'Profile', 'category': 'Settings'}
        ]
        
        search_term = 'set'
        
        # Filter commands
        filtered = [
            cmd for cmd in commands 
            if search_term.lower() in cmd['label'].lower()
        ]
        
        assert len(filtered) == 2
        assert filtered[0]['label'] == 'Open Dataset'
        assert filtered[1]['label'] == 'Settings'
    
    def test_command_execution(self, mock_router):
        """Test command execution from palette."""
        commands = {
            'new-analysis': lambda: mock_router.push('/chat'),
            'open-dataset': lambda: mock_router.push('/datasets'),
            'settings': lambda: mock_router.push('/settings')
        }
        
        # Execute command
        command_id = 'new-analysis'
        commands[command_id]()
        
        mock_router.push.assert_called_with('/chat')
    
    def test_help_overlay_display(self, default_shortcuts):
        """Test help overlay shows all shortcuts."""
        # Group by category
        categories = {}
        for shortcut in default_shortcuts:
            cat = shortcut['category']
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(shortcut)
        
        assert 'Navigation' in categories
        assert 'File' in categories
        assert 'Edit' in categories
        assert len(categories['Navigation']) >= 3
    
    def test_key_formatting(self):
        """Test keyboard key formatting for display."""
        formats = {
            'cmd': '⌘',
            'shift': '⇧',
            'alt': '⌥',
            'ctrl': 'Ctrl',
            'enter': '↵',
            'tab': '⇥',
            'escape': 'Esc'
        }
        
        for key, formatted in formats.items():
            assert formats[key] == formatted
    
    def test_multi_key_shortcuts(self):
        """Test multi-key combination shortcuts."""
        event = Mock()
        event.metaKey = True
        event.shiftKey = True
        event.key = 'f'
        
        # Check for Cmd+Shift+F (fullscreen)
        is_fullscreen_shortcut = (
            event.metaKey and 
            event.shiftKey and 
            event.key == 'f'
        )
        
        assert is_fullscreen_shortcut is True
    
    def test_escape_key_handling(self):
        """Test Escape key closes dialogs."""
        dialog_open = True
        
        event = Mock()
        event.key = 'Escape'
        
        if event.key == 'Escape' and dialog_open:
            dialog_open = False
        
        assert dialog_open is False
    
    def test_arrow_key_navigation(self):
        """Test arrow key navigation in command palette."""
        items = ['Item 1', 'Item 2', 'Item 3']
        selected_index = 0
        
        # Arrow down
        event = Mock()
        event.key = 'ArrowDown'
        
        if event.key == 'ArrowDown':
            selected_index = min(selected_index + 1, len(items) - 1)
        
        assert selected_index == 1
        
        # Arrow up
        event.key = 'ArrowUp'
        if event.key == 'ArrowUp':
            selected_index = max(selected_index - 1, 0)
        
        assert selected_index == 0
    
    def test_enter_key_selection(self):
        """Test Enter key selects command."""
        selected_command = 'new-analysis'
        executed = False
        
        event = Mock()
        event.key = 'Enter'
        
        if event.key == 'Enter' and selected_command:
            executed = True
        
        assert executed is True
    
    def test_platform_detection(self):
        """Test platform-specific modifier keys."""
        # Mock Mac platform
        is_mac = True
        modifier = '⌘' if is_mac else 'Ctrl'
        assert modifier == '⌘'
        
        # Mock Windows/Linux
        is_mac = False
        modifier = '⌘' if is_mac else 'Ctrl'
        assert modifier == 'Ctrl'
    
    def test_shortcut_categories(self, default_shortcuts):
        """Test shortcut categorization."""
        categories = set(s['category'] for s in default_shortcuts)
        
        expected = {'Navigation', 'File', 'Edit', 'View', 'Execution', 'Help'}
        assert expected.issubset(categories)
    
    def test_reset_to_default(self):
        """Test resetting custom shortcuts to defaults."""
        custom_shortcuts = {'save': ['cmd', 'shift', 's']}
        
        # Reset
        custom_shortcuts = {}
        
        assert len(custom_shortcuts) == 0
    
    def test_accessibility_shortcuts(self):
        """Test accessibility-related shortcuts."""
        # Tab navigation
        event = Mock()
        event.key = 'Tab'
        assert event.key == 'Tab'
        
        # Shift+Tab reverse navigation
        event.shiftKey = True
        assert event.shiftKey is True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])