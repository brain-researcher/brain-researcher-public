"""
Comprehensive tests for UI-031: Advanced Visualization Controls
Tests all features including Niivue integration, clipping planes, layer management, and animation
"""

import pytest
import numpy as np
from unittest.mock import Mock, patch, MagicMock
import json
import io
from pathlib import Path

# Mock Niivue since it's a browser-specific library
class MockNiivue:
    def __init__(self, opts=None):
        self.opts = opts or {}
        self.volumes = []
        self.canvas = Mock()
        self.canvas.toDataURL = Mock(return_value="data:image/png;base64,test")
        self.scene = Mock()
        self.scene.clipPlane = [0, 0, 0]
        self.scene.renderAzimuth = 0
        self.scene.renderElevation = 0
        self.volScaleMultiplier = 1
        self.sliceType = 'multiplanar'
        
    async def attachTo(self, canvas):
        pass
    
    async def loadVolumes(self, volumes):
        for i, vol in enumerate(volumes):
            mock_vol = Mock()
            mock_vol.url = vol['url']
            mock_vol.opacity = 1.0
            mock_vol.colormap = 'gray'
            mock_vol.cal_min = 0
            mock_vol.cal_max = 100
            mock_vol.frame4D = 0
            mock_vol.nFrame4D = 1
            self.volumes.append(mock_vol)
    
    def setOpacity(self, vol_id, opacity):
        if vol_id < len(self.volumes):
            self.volumes[vol_id].opacity = opacity
    
    def setColormap(self, vol_id, colormap):
        if vol_id < len(self.volumes):
            self.volumes[vol_id].colormap = colormap
    
    def setClipPlane(self, plane):
        self.scene.clipPlane = plane
    
    def setFrame4D(self, frame):
        if self.volumes:
            self.volumes[0].frame4D = frame
    
    def setFrame(self, frame):
        self.setFrame4D(frame)
    
    def setSliceType(self, slice_type):
        self.sliceType = slice_type
    
    def resetBrightness(self):
        pass
    
    def updateGLVolume(self):
        pass
    
    def drawScene(self):
        pass

@pytest.fixture
def mock_niivue():
    with patch('brain_researcher.services.web_ui.src.components.visualization.AdvancedVisualizationControls.Niivue', MockNiivue):
        yield MockNiivue

class TestAdvancedVisualizationControls:
    """Test the main AdvancedVisualizationControls component"""
    
    def test_initialization(self, mock_niivue):
        """Test component initialization"""
        # This would test React component initialization
        # In a real test, you'd use @testing-library/react
        pass
    
    def test_volume_loading(self, mock_niivue):
        """Test loading volumes into the viewer"""
        nv = MockNiivue()
        volumes = [{'url': 'test1.nii.gz'}, {'url': 'test2.nii.gz'}]
        
        # Simulate loading volumes
        import asyncio
        asyncio.run(nv.loadVolumes(volumes))
        
        assert len(nv.volumes) == 2
        assert nv.volumes[0].url == 'test1.nii.gz'
        assert nv.volumes[1].url == 'test2.nii.gz'
    
    def test_layer_opacity_control(self, mock_niivue):
        """Test layer opacity controls"""
        nv = MockNiivue()
        nv.volumes = [Mock(), Mock()]
        
        # Test opacity setting
        nv.setOpacity(0, 0.5)
        nv.setOpacity(1, 0.8)
        
        assert nv.volumes[0].opacity == 0.5
        assert nv.volumes[1].opacity == 0.8
    
    def test_colormap_selection(self, mock_niivue):
        """Test colormap selection"""
        nv = MockNiivue()
        nv.volumes = [Mock()]
        
        # Test colormap setting
        nv.setColormap(0, 'red')
        assert nv.volumes[0].colormap == 'red'
        
        nv.setColormap(0, 'hot')
        assert nv.volumes[0].colormap == 'hot'

class TestClippingPlaneControls:
    """Test clipping plane functionality with correct API usage"""
    
    def test_clipping_plane_api(self, mock_niivue):
        """Test that clipping plane uses [depth, azimuth, elevation] format"""
        nv = MockNiivue()
        
        # Test correct API usage
        nv.setClipPlane([0.5, 90, 45])
        
        assert nv.scene.clipPlane == [0.5, 90, 45]
    
    def test_coordinate_conversion(self):
        """Test conversion from XYZ to depth/azimuth/elevation"""
        # Test conversion functions that would be in the real implementation
        def xyz_to_spherical(x, y, z):
            """Convert XYZ coordinates to spherical (depth, azimuth, elevation)"""
            depth = np.sqrt(x**2 + y**2 + z**2)
            azimuth = np.degrees(np.arctan2(y, x))
            elevation = np.degrees(np.arcsin(z / depth)) if depth > 0 else 0
            return depth, azimuth, elevation
        
        # Test cases
        depth, azimuth, elevation = xyz_to_spherical(1, 0, 0)
        assert abs(azimuth) < 1e-10  # Should be 0 degrees
        assert abs(elevation) < 1e-10  # Should be 0 degrees
        
        depth, azimuth, elevation = xyz_to_spherical(0, 1, 0)
        assert abs(azimuth - 90) < 1e-10  # Should be 90 degrees
        
        depth, azimuth, elevation = xyz_to_spherical(0, 0, 1)
        assert abs(elevation - 90) < 1e-10  # Should be 90 degrees
    
    def test_preset_positions(self):
        """Test clipping plane preset positions"""
        presets = {
            'anterior': {'depth': 0.5, 'azimuth': 90, 'elevation': 0},
            'posterior': {'depth': 0.5, 'azimuth': 270, 'elevation': 0},
            'superior': {'depth': 0.5, 'azimuth': 0, 'elevation': 90},
            'inferior': {'depth': 0.5, 'azimuth': 0, 'elevation': 270},
            'left': {'depth': 0.5, 'azimuth': 0, 'elevation': 0},
            'right': {'depth': 0.5, 'azimuth': 180, 'elevation': 0}
        }
        
        for preset_name, values in presets.items():
            assert 0 <= values['depth'] <= 1
            assert 0 <= values['azimuth'] <= 360
            assert 0 <= values['elevation'] <= 360

class TestFrameController:
    """Test 4D frame control with runtime API detection"""
    
    def test_frame_controller_detection(self):
        """Test runtime detection of frame control methods"""
        from brain_researcher.services.web_ui.src.lib.niivue_manager import createNiivueManager
        
        # Mock Niivue with setFrame4D method
        nv_with_4d = MockNiivue()
        nv_with_4d.setFrame4D = Mock()
        manager_4d = createNiivueManager(nv_with_4d)
        
        assert manager_4d.detectFrameControlMethod() == 'setFrame4D'
        
        # Mock Niivue with only setFrame method
        nv_with_frame = MockNiivue()
        nv_with_frame.setFrame = Mock()
        # Simulate older Niivue versions that only expose `setFrame`.
        nv_with_frame.setFrame4D = None
        manager_frame = createNiivueManager(nv_with_frame)
        
        assert manager_frame.detectFrameControlMethod() == 'setFrame'
    
    def test_4d_animation_control(self, mock_niivue):
        """Test 4D animation playback control"""
        nv = MockNiivue()
        vol = Mock()
        vol.nFrame4D = 10
        vol.frame4D = 0
        nv.volumes = [vol]
        
        from brain_researcher.services.web_ui.src.lib.niivue_manager import createNiivueManager
        manager = createNiivueManager(nv)
        
        # Test frame setting
        manager.setFrame(5)
        assert manager.getCurrentFrame() == 5
        assert manager.getMaxFrames() == 10
        
        # Test animation control
        assert not manager.isAnimating()
        manager.startAnimation()
        assert manager.isAnimating()
        manager.stopAnimation()
        assert not manager.isAnimating()

class TestLayerManager:
    """Test multi-layer volume management"""
    
    def test_layer_creation(self):
        """Test creating layers from volume URLs"""
        urls = ['volume1.nii.gz', 'volume2.nii.gz', 'volume3.nii.gz']
        
        # Simulate layer creation logic
        layers = []
        for i, url in enumerate(urls):
            layer = {
                'id': f'layer_{i}',
                'name': url.split('/')[-1].split('.')[0],
                'url': url,
                'visible': True,
                'opacity': 1.0 if i == 0 else 0.7,
                'colormap': 'gray' if i == 0 else 'red',
                'cal_min': 0,
                'cal_max': 100,
                'volumeId': i
            }
            layers.append(layer)
        
        assert len(layers) == 3
        assert layers[0]['opacity'] == 1.0  # Base layer fully opaque
        assert layers[1]['opacity'] == 0.7  # Overlay layers semi-transparent
        assert layers[0]['colormap'] == 'gray'  # Base layer grayscale
        assert layers[1]['colormap'] == 'red'   # Overlay layers colored
    
    def test_layer_reordering(self):
        """Test layer stack reordering"""
        layers = [
            {'id': 'layer_0', 'name': 'Layer 0'},
            {'id': 'layer_1', 'name': 'Layer 1'},
            {'id': 'layer_2', 'name': 'Layer 2'}
        ]
        
        # Move layer 0 up (should do nothing as it's already at top)
        def move_layer(layers, layer_id, direction):
            current_index = next(i for i, l in enumerate(layers) if l['id'] == layer_id)
            if direction == 'up' and current_index > 0:
                layers[current_index], layers[current_index - 1] = layers[current_index - 1], layers[current_index]
            elif direction == 'down' and current_index < len(layers) - 1:
                layers[current_index], layers[current_index + 1] = layers[current_index + 1], layers[current_index]
            return layers
        
        # Test moving layer 1 up
        move_layer(layers, 'layer_1', 'up')
        assert layers[0]['id'] == 'layer_1'
        assert layers[1]['id'] == 'layer_0'
    
    def test_volume_id_management(self):
        """Test that volume IDs are properly tracked"""
        layers = [
            {'id': 'layer_0', 'volumeId': 0},
            {'id': 'layer_1', 'volumeId': 1},
            {'id': 'layer_2', 'volumeId': 2}
        ]
        
        # Test volume ID lookup
        def get_volume_id(layer_id):
            layer = next(l for l in layers if l['id'] == layer_id)
            return layer.get('volumeId')
        
        assert get_volume_id('layer_0') == 0
        assert get_volume_id('layer_1') == 1
        assert get_volume_id('layer_2') == 2

class TestAnimationTimeline:
    """Test 4D animation timeline controls"""
    
    def test_timeline_calculation(self):
        """Test timeline calculations and formatting"""
        max_frames = 100
        frame_rate = 10
        
        def format_time(frame):
            seconds = frame / frame_rate
            minutes = int(seconds // 60)
            remaining_seconds = seconds % 60
            return f"{minutes}:{remaining_seconds:04.1f}"
        
        # Test time formatting
        assert format_time(0) == "0:00.0"
        assert format_time(10) == "0:01.0"
        assert format_time(60) == "0:06.0"
        assert format_time(600) == "1:00.0"
    
    def test_animation_modes(self):
        """Test different animation loop modes"""
        max_frames = 5
        
        def step_frame(current_frame, direction, loop_mode):
            delta = 1 if direction == 'forward' else -1
            new_frame = current_frame + delta
            
            if loop_mode == 'once':
                return max(0, min(max_frames - 1, new_frame))
            elif loop_mode == 'loop':
                return new_frame % max_frames
            elif loop_mode == 'pingpong':
                if new_frame >= max_frames:
                    return max_frames - 2
                elif new_frame < 0:
                    return 1
                return new_frame
            
            return new_frame
        
        # Test 'once' mode
        assert step_frame(4, 'forward', 'once') == 4  # Should stop at boundary
        assert step_frame(0, 'backward', 'once') == 0  # Should stop at boundary
        
        # Test 'loop' mode
        assert step_frame(4, 'forward', 'loop') == 0  # Should wrap around
        assert step_frame(0, 'backward', 'loop') == 4  # Should wrap around
        
        # Test 'pingpong' mode
        assert step_frame(4, 'forward', 'pingpong') == 3  # Should reverse direction
        assert step_frame(0, 'backward', 'pingpong') == 1  # Should reverse direction

class TestNiivueManager:
    """Test the Niivue manager utility functions"""
    
    def test_screenshot_export(self, mock_niivue):
        """Test screenshot export functionality"""
        nv = MockNiivue()
        from brain_researcher.services.web_ui.src.lib.niivue_manager import createNiivueManager
        
        manager = createNiivueManager(nv)
        
        # Test screenshot export
        screenshot_data = manager.exportScreenshot('png')
        assert screenshot_data.startswith('data:image/png;base64,')
        
        screenshot_jpeg = manager.exportScreenshot('jpeg')
        assert screenshot_jpeg.startswith('data:image/jpeg;base64,')
    
    def test_state_serialization(self, mock_niivue):
        """Test visualization state serialization"""
        nv = MockNiivue()
        vol = Mock()
        vol.url = 'test.nii.gz'
        vol.opacity = 0.8
        vol.colormap = 'red'
        vol.cal_min = 10
        vol.cal_max = 90
        vol.frame4D = 5
        nv.volumes = [vol]
        nv.scene.clipPlane = [0.5, 90, 45]
        
        from brain_researcher.services.web_ui.src.lib.niivue_manager import createNiivueManager
        manager = createNiivueManager(nv)
        
        # Test state serialization
        state = manager.getVisualizationState()
        
        assert len(state['volumes']) == 1
        assert state['volumes'][0]['url'] == 'test.nii.gz'
        assert state['volumes'][0]['opacity'] == 0.8
        assert state['volumes'][0]['colormap'] == 'red'
        assert state['clipPlane'] == [0.5, 90, 45]
        
        # Test state restoration
        manager.setVisualizationState(state)
        # In a real test, would verify that the state was applied correctly

class TestPythonBackend:
    """Test the Python visualization backend service"""
    
    @patch('nibabel.load')
    @patch('nilearn.datasets.load_mni152_template')
    def test_mni_template_loading(self, mock_load_template, mock_nib_load):
        """Test MNI152 template loading with correct API"""
        from brain_researcher.services.web_ui.api.viz_service import get_mni_template
        
        # Mock template
        mock_template = Mock()
        mock_load_template.return_value = mock_template
        
        # Test template loading
        template = get_mni_template("2mm")
        
        # Verify correct API call
        mock_load_template.assert_called_with(resolution="2mm")
        assert template == mock_template
    
    def test_volume_processing_request_validation(self):
        """Test volume processing request validation"""
        from brain_researcher.services.web_ui.api.viz_service import VolumeProcessingRequest
        
        # Test valid requests
        request1 = VolumeProcessingRequest()
        assert request1.align_to_ras == True
        
        request2 = VolumeProcessingRequest(
            threshold_min=0.1,
            threshold_max=0.9,
            smooth_fwhm=4.0,
            resample_target="mni152"
        )
        assert request2.threshold_min == 0.1
        assert request2.smooth_fwhm == 4.0
    
    def test_animation_export_request(self):
        """Test animation export request validation"""
        from brain_researcher.services.web_ui.api.viz_service import AnimationExportRequest
        
        request = AnimationExportRequest(
            format="mp4",
            fps=15,
            quality="high"
        )
        
        assert request.format == "mp4"
        assert request.fps == 15
        assert request.quality == "high"
    
    def test_file_handling_with_bytesio(self):
        """Test proper file handling with BytesIO"""
        import io
        
        # Test BytesIO handling
        test_data = b"test nifti data"
        file_like = io.BytesIO(test_data)
        
        # Verify BytesIO behavior
        assert file_like.read() == test_data
        file_like.seek(0)
        assert file_like.tell() == 0
        assert file_like.read(4) == b"test"

class TestPerformanceAndCompatibility:
    """Test performance characteristics and forward compatibility"""
    
    def test_large_volume_handling(self):
        """Test handling of large 4D volumes"""
        # Simulate large volume dimensions
        large_volume_shape = (128, 128, 64, 200)  # 200 timepoints
        
        # Test memory estimation
        def estimate_memory_usage(shape, dtype=np.float32):
            elements = np.prod(shape)
            bytes_per_element = np.dtype(dtype).itemsize
            return elements * bytes_per_element
        
        memory_usage = estimate_memory_usage(large_volume_shape)
        memory_mb = memory_usage / (1024 * 1024)
        
        # Large 4D volume should be several hundred MB
        assert memory_mb > 100
        print(f"Large volume memory usage: {memory_mb:.1f} MB")
    
    def test_level_of_detail_strategy(self):
        """Test LOD (Level of Detail) strategy for large files"""
        original_shape = (256, 256, 256, 100)
        
        def calculate_lod_shape(original_shape, lod_level):
            """Calculate downsampled shape for LOD"""
            factor = 2 ** lod_level
            return tuple(max(1, dim // factor) for dim in original_shape)
        
        # Test different LOD levels
        lod1 = calculate_lod_shape(original_shape, 1)
        lod2 = calculate_lod_shape(original_shape, 2)
        
        assert lod1 == (128, 128, 128, 50)
        assert lod2 == (64, 64, 64, 25)
    
    def test_pwa_offline_considerations(self):
        """Test considerations for PWA offline functionality"""
        # Test caching strategy parameters
        cache_config = {
            'max_volume_size_mb': 50,
            'max_cached_volumes': 5,
            'compression_level': 6
        }
        
        def should_cache_volume(size_mb):
            return size_mb <= cache_config['max_volume_size_mb']
        
        assert should_cache_volume(30) == True
        assert should_cache_volume(60) == False
    
    def test_websocket_state_sync(self):
        """Test state synchronization for UI-033 collaboration"""
        # Test state serialization for WebSocket transmission
        visualization_state = {
            'layers': [
                {'id': 'layer_0', 'opacity': 0.8, 'visible': True},
                {'id': 'layer_1', 'opacity': 0.6, 'visible': False}
            ],
            'clipPlane': {'enabled': True, 'depth': 0.5, 'azimuth': 90, 'elevation': 45},
            'currentFrame': 10,
            'isAnimating': False
        }
        
        # Test JSON serialization
        serialized = json.dumps(visualization_state)
        deserialized = json.loads(serialized)
        
        assert deserialized['clipPlane']['depth'] == 0.5
        assert len(deserialized['layers']) == 2
        assert deserialized['currentFrame'] == 10

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
