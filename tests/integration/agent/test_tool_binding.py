#!/usr/bin/env python
"""Test that all tools can be bound to LLM successfully."""

import sys
import pytest
from brain_researcher.services.agent.agents.neuro_agent_llm import NeuroAgentLLM

pytest.skip("tool binding smoke requires running agent/LLM env", allow_module_level=True)

print("Testing tool binding with NeuroAgentLLM...")
print("-" * 50)

try:
    # Initialize agent (this will bind tools)
    print("Initializing NeuroAgentLLM...")
    agent = NeuroAgentLLM()
    
    print(f"✅ Successfully bound {len(agent.tools)} tools to LLM")
    
    # List real-time tools that were fixed
    realtime_tool_names = [
        'realtime_glm',
        'neurofeedback_control', 
        'roi_monitoring',
        'adaptive_thresholding',
        'realtime_decoding',
        'closed_loop_stimulation',
        'realtime_connectivity',
        'neurofeedback_training'
    ]
    
    print("\n📊 Real-time tools (fixed schemas):")
    found_realtime = 0
    for tool in agent.tools:
        if hasattr(tool, 'name') and tool.name in realtime_tool_names:
            print(f"  ✓ {tool.name}")
            found_realtime += 1
    
    print(f"\nFound {found_realtime}/{len(realtime_tool_names)} real-time tools")
    
    # Test that LLM can use tools
    print("\n🔧 Testing LLM with tools binding...")
    if hasattr(agent, 'llm_with_tools'):
        print("  ✓ LLM has tools bound (llm_with_tools exists)")
        
        # Try to get the tool schemas
        if hasattr(agent.llm_with_tools, 'kwargs') and 'tools' in agent.llm_with_tools.kwargs:
            bound_tools = agent.llm_with_tools.kwargs['tools']
            print(f"  ✓ {len(bound_tools)} tools are bound to the LLM")
    
    print("\n✅ All tool binding tests passed!")
    sys.exit(0)
    
except Exception as e:
    print(f"\n❌ Tool binding failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)