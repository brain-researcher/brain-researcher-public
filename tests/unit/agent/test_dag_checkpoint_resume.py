from datetime import datetime

from brain_researcher.services.agent.dag_executor import ComplexDAGExecutor, DAGExecution, NodeExecution, ExecutionStatus
from brain_researcher.services.agent.dag_language import DAGDefinition, DAGNode, NodeType
from brain_researcher.services.agent.checkpoint_manager import ExecutionState


def test_apply_checkpoint_marks_completed_nodes():
    dag = DAGDefinition(name="demo")
    dag.add_node(DAGNode(id="n1", type=NodeType.TOOL, tool="t1"))
    dag.add_node(DAGNode(id="n2", type=NodeType.TOOL, tool="t2", dependencies=["n1"]))

    executor = ComplexDAGExecutor(checkpoint_manager=None)
    exec_state = DAGExecution(
        execution_id="exec1",
        dag=dag,
        node_executions={},
        global_context={},
        start_time=datetime.now(),
    )

    state = ExecutionState(
        execution_id="exec1",
        current_step=1,
        completed_steps=["n1"],
        step_results={"n1": {"status": "success", "result": {"ok": True}, "error": None}},
        variables={"global_context": {"foo": "bar"}},
        timestamp=datetime.now().timestamp(),
        metadata={},
    )

    executor._apply_checkpoint_state(exec_state, state)

    assert "n1" in exec_state.completed_nodes
    assert exec_state.node_executions["n1"].status == ExecutionStatus.SUCCESS
    assert exec_state.node_executions["n1"].result == {"ok": True}
    assert exec_state.global_context["foo"] == "bar"
