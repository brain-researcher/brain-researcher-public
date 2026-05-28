"""Tests for brain simulation tool."""

import json
import numpy as np
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile

from brain_researcher.services.tools.brain_simulation_tool import (
    BrainSimulationTool,
    BrainSimulationArgs
)


class TestBrainSimulationTool:
    """Test brain simulation functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.tool = BrainSimulationTool()
        self.temp_dir = tempfile.mkdtemp()
    
    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_tool_initialization(self):
        """Test tool initializes correctly."""
        assert self.tool.get_tool_name() == "brain_simulation"
        assert "neural dynamics" in self.tool.get_tool_description().lower()
        assert self.tool.get_args_schema() == BrainSimulationArgs
    
    def test_jansen_rit_model(self):
        """Test Jansen-Rit neural mass model."""
        # Test single node
        state = np.zeros(6)
        params = {
            'n_nodes': 1,
            'connectivity': np.array([[0]]),
            'coupling': 0.5,
            'input': 120,
            'A': 3.25, 'B': 22, 'a': 100, 'b': 50,
            'C1': 135, 'C2': 135, 'C3': 135, 'C4': 135,
            'r': 0.56, 'v0': 6, 'e0': 2.5
        }
        
        dydt = self.tool._jansen_rit_model(state, 0, params)
        assert len(dydt) == 6
        assert all(np.isfinite(dydt))
    
    def test_kuramoto_model(self):
        """Test Kuramoto oscillator model."""
        n_oscillators = 10
        theta = np.random.uniform(0, 2*np.pi, n_oscillators)
        omega = np.random.randn(n_oscillators)
        K = np.random.rand(n_oscillators, n_oscillators)
        K = (K + K.T) / 2  # Make symmetric
        
        dtheta_dt = self.tool._kuramoto_model(theta, omega, K)
        
        assert dtheta_dt.shape == (n_oscillators,)
        assert all(np.isfinite(dtheta_dt))
    
    def test_wilson_cowan_model(self):
        """Test Wilson-Cowan model."""
        n_nodes = 5
        state = np.random.rand(n_nodes * 2)
        params = {
            'n_nodes': n_nodes,
            'connectivity': np.random.rand(n_nodes, n_nodes),
            'coupling': 0.5,
            'tau_e': 0.01, 'tau_i': 0.02,
            'w_ee': 12, 'w_ei': 4, 'w_ie': 13, 'w_ii': 11,
            'theta_e': 4, 'theta_i': 3.7
        }
        
        dydt = self.tool._wilson_cowan_model(state, 0, params)
        
        assert len(dydt) == n_nodes * 2
        assert all(np.isfinite(dydt))
    
    def test_simulate_neural_mass(self):
        """Test neural mass simulation."""
        n_nodes = 3
        connectivity = np.random.rand(n_nodes, n_nodes)
        time_points = 100
        
        result = self.tool._simulate_neural_mass(
            n_nodes=n_nodes,
            connectivity=connectivity,
            time_points=time_points,
            dt=0.001,
            model='jansen_rit',
            parameters={}
        )
        
        assert 'time' in result
        assert 'signals' in result
        assert result['signals'].shape == (time_points, n_nodes)
        assert all(np.isfinite(result['signals'].ravel()))
    
    def test_simulate_oscillators(self):
        """Test oscillator simulation."""
        n_oscillators = 8
        coupling_strength = 0.5
        time_points = 50
        
        result = self.tool._simulate_oscillators(
            n_oscillators=n_oscillators,
            coupling_strength=coupling_strength,
            time_points=time_points,
            dt=0.01,
            natural_frequencies=None,
            initial_phases=None
        )
        
        assert 'time' in result
        assert 'phases' in result
        assert 'order_parameter' in result
        assert result['phases'].shape == (time_points, n_oscillators)
        assert len(result['order_parameter']) == time_points
    
    def test_simulate_spiking_network(self):
        """Test spiking network simulation."""
        n_neurons = 50
        time_ms = 100
        
        result = self.tool._simulate_spiking_network(
            n_neurons=n_neurons,
            n_excitatory=40,
            n_inhibitory=10,
            time_ms=time_ms,
            dt=0.1
        )
        
        assert 'spike_times' in result
        assert 'spike_neurons' in result
        assert 'rates' in result
        assert len(result['rates']) == n_neurons
        assert all(r >= 0 for r in result['rates'])
    
    def test_run_neural_mass_simulation(self):
        """Test full neural mass simulation pipeline."""
        args = {
            'simulation_type': 'neural_mass',
            'model_type': 'jansen_rit',
            'n_nodes': 2,
            'connectivity_matrix': [[1.0, 0.5], [0.5, 1.0]],
            'simulation_time': 0.1,
            'dt': 0.001,
            'output_dir': self.temp_dir,
            'save_results': True,
            'visualize': True
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        assert 'outputs' in result.data
        assert 'summary' in result.data
        assert result.data['summary']['simulation_completed']
    
    def test_run_kuramoto_simulation(self):
        """Test full Kuramoto simulation pipeline."""
        args = {
            'simulation_type': 'kuramoto',
            'n_oscillators': 5,
            'coupling_strength': 0.3,
            'simulation_time': 0.05,
            'dt': 0.01,
            'output_dir': self.temp_dir,
            'save_results': True,
            'visualize': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        assert 'outputs' in result.data
        assert 'summary' in result.data
        assert result.data['summary']['simulation_completed']
    
    def test_run_wilson_cowan_simulation(self):
        """Test full Wilson-Cowan simulation pipeline."""
        args = {
            'simulation_type': 'neural_mass',
            'model_type': 'wilson_cowan',
            'n_nodes': 3,
            'connectivity_matrix': [[1, 0.5, 0.2], [0.5, 1, 0.3], [0.2, 0.3, 1]],
            'simulation_time': 0.05,
            'dt': 0.001,
            'output_dir': self.temp_dir,
            'save_results': True,
            'visualize': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        assert 'outputs' in result.data
        assert result.data['summary']['model'] == 'wilson_cowan'
    
    def test_run_spiking_simulation(self):
        """Test full spiking network simulation."""
        args = {
            'simulation_type': 'spiking',
            'n_neurons': 20,
            'n_excitatory': 15,
            'n_inhibitory': 5,
            'simulation_time': 0.05,
            'dt': 0.0001,
            'output_dir': self.temp_dir,
            'save_results': True,
            'visualize': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        assert 'outputs' in result.data
        assert result.data['summary']['mean_firing_rate'] >= 0
    
    def test_error_handling(self):
        """Test error handling."""
        args = {
            'simulation_type': 'invalid_type',
            'output_dir': self.temp_dir
        }
        
        result = self.tool._run(**args)
        
        # Should handle gracefully - defaults to neural_mass
        assert result.status == "success"
    
    def test_phase_coupling_analysis(self):
        """Test phase coupling metrics."""
        n_oscillators = 6
        phases = np.random.uniform(0, 2*np.pi, (100, n_oscillators))
        
        # Compute phase locking value
        plv = np.zeros((n_oscillators, n_oscillators))
        for i in range(n_oscillators):
            for j in range(i+1, n_oscillators):
                phase_diff = phases[:, i] - phases[:, j]
                plv[i, j] = np.abs(np.mean(np.exp(1j * phase_diff)))
                plv[j, i] = plv[i, j]
        
        assert plv.shape == (n_oscillators, n_oscillators)
        assert np.all((plv >= 0) & (plv <= 1))
    
    def test_functional_connectivity_from_simulation(self):
        """Test computing functional connectivity from simulated data."""
        # Simulate data
        args = {
            'simulation_type': 'neural_mass',
            'model_type': 'jansen_rit',
            'n_nodes': 4,
            'connectivity_matrix': [[1, 0.5, 0.2, 0.1],
                                   [0.5, 1, 0.3, 0.2],
                                   [0.2, 0.3, 1, 0.4],
                                   [0.1, 0.2, 0.4, 1]],
            'simulation_time': 0.2,
            'dt': 0.001,
            'output_dir': self.temp_dir,
            'save_results': True,
            'compute_fc': True,
            'visualize': False
        }
        
        result = self.tool._run(**args)
        
        assert result.status == "success"
        if 'functional_connectivity' in result.data['summary']:
            fc = result.data['summary']['functional_connectivity']
            assert fc.shape == (4, 4)
            assert np.all((fc >= -1) & (fc <= 1))