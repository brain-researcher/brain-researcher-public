from datetime import datetime

import streamlit as st

from ..graph.graph_database import BRKGGraphDB

DB_PATH = "../data/br-kg/db/br_kg_full.db"


def load_edges(db):
    candidates = []
    for s, e, data in db.find_relationships(rel_type="HAS_CONCEPT"):
        util = data.get("utility")
        if util is not None and 0.4 <= util <= 0.6:
            candidates.append((s, e, data))
    return candidates


def update_edge(db, start, end, edge_data):
    """Persist reviewer updates to the graph database."""
    props = {k: v for k, v in edge_data.items() if k != "type"}
    db.update_relationship(start, end, edge_data["type"], props)


def main():
    st.title("Contrast-Concept Edge Review")
    username = st.sidebar.text_input("Reviewer")

    db = BRKGGraphDB(DB_PATH)
    edges = load_edges(db)

    if not edges:
        st.info("No edges requiring review.")
        return

    for idx, (start, end, data) in enumerate(edges):
        contrast = db.graph.nodes[start]
        concept = db.graph.nodes[end]
        st.subheader(f"Edge {idx+1}")
        st.write(f"**Task:** {contrast.get('task_name','N/A')}")
        st.write(f"**Contrast:** {contrast.get('name','')}")
        st.write(f"**Concept:** {concept.get('name','')}")
        st.write(f"**Utility:** {data.get('utility')}")
        st.write(f"**Source:** {data.get('source','')}")
        st.write(f"**Annotation:** {contrast.get('description','')}")

        decision = st.radio("Decision", ("Accept", "Reject"), key=f"dec{idx}")
        rating = st.selectbox("Rating", ["A", "B", "C", "D"], key=f"rat{idx}")
        comment = st.text_input("Comment", key=f"com{idx}")

        if st.button("Save", key=f"save{idx}") and username:
            data["validated"] = decision == "Accept"
            data["reviewer"] = username
            data["validation_rating"] = rating
            data["reviewed_at"] = datetime.utcnow().isoformat()
            if comment:
                data["comment"] = comment
            update_edge(db, start, end, data)
            st.success("Saved")
        st.markdown("---")


if __name__ == "__main__":
    main()
